param(
    [ValidateSet("start", "cleanup", "status")]
    [string]$Mode = "status",
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$venvPython = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".venv\Scripts\python.exe"))
$loginUrl = "http://${BindHost}:${Port}/login"
$envFilePath = Join-Path $projectRoot ".env"

function Get-ProcessMap {
    $map = @{}
    foreach ($process in Get-CimInstance Win32_Process) {
        $map[[int]$process.ProcessId] = $process
    }
    return $map
}

function Test-SamePath {
    param(
        [string]$Left,
        [string]$Right
    )

    if (-not $Left -or -not $Right) {
        return $false
    }

    return [System.IO.Path]::GetFullPath($Left).Equals(
        [System.IO.Path]::GetFullPath($Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Test-AnySamePath {
    param(
        [string]$Candidate,
        [string[]]$Paths
    )

    if (-not $Candidate -or -not $Paths) {
        return $false
    }

    foreach ($path in $Paths) {
        if (Test-SamePath -Left $Candidate -Right $path) {
            return $true
        }
    }

    return $false
}

function ConvertTo-BoolSetting {
    param(
        [AllowNull()]
        [string]$Value,
        [bool]$Default = $false
    )

    if ($null -eq $Value) {
        return $Default
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if (-not $normalized) {
        return $Default
    }

    return $normalized -notin @("0", "false", "no", "off")
}

function Read-EnvSettings {
    $settings = @{}

    if (-not (Test-Path -LiteralPath $envFilePath)) {
        return $settings
    }

    foreach ($rawLine in Get-Content -LiteralPath $envFilePath -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            $settings[$key] = $value
        }
    }

    return $settings
}

function ConvertTo-AbsolutePath {
    param(
        [AllowNull()]
        [string]$PathValue
    )

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $PathValue))
}

function Get-RedisServerPathCandidates {
    param(
        [AllowNull()]
        [string]$ConfiguredPath
    )

    $candidates = New-Object "System.Collections.Generic.List[string]"
    $bundledRedisRoot = Join-Path $projectRoot "redis"

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredPath)) {
        [void]$candidates.Add($ConfiguredPath)
    }

    [void]$candidates.Add((Join-Path $projectRoot "redis-server.exe"))
    [void]$candidates.Add((Join-Path $bundledRedisRoot "redis-server.exe"))

    if (Test-Path -LiteralPath $bundledRedisRoot) {
        foreach ($directory in Get-ChildItem -LiteralPath $bundledRedisRoot -Directory -ErrorAction SilentlyContinue) {
            [void]$candidates.Add((Join-Path $directory.FullName "redis-server.exe"))
        }
    }

    foreach ($candidate in @(
        "C:\Redis\redis-server.exe",
        "C:\Program Files\Redis\redis-server.exe",
        "C:\Program Files\Memurai\redis-server.exe"
    )) {
        [void]$candidates.Add($candidate)
    }

    foreach ($commandName in @("redis-server.exe", "redis-server")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Path) {
            [void]$candidates.Add([string]$command.Path)
        }
    }

    return $candidates
}

function Resolve-RedisServerPath {
    param(
        [AllowNull()]
        [string]$ConfiguredPath
    )

    foreach ($candidate in Get-RedisServerPathCandidates -ConfiguredPath $ConfiguredPath) {
        try {
            $absoluteCandidate = ConvertTo-AbsolutePath -PathValue $candidate
            if (-not [string]::IsNullOrWhiteSpace($absoluteCandidate) -and (Test-Path -LiteralPath $absoluteCandidate)) {
                return $absoluteCandidate
            }
        } catch {
            continue
        }
    }

    return $null
}

function Get-RedisStartupConfig {
    $settings = Read-EnvSettings
    $redisEnabledRaw = if ($settings.ContainsKey("ARBI_REDIS_ENABLED")) { [string]$settings["ARBI_REDIS_ENABLED"] } else { $null }
    $runtimeEnabledRaw = if ($settings.ContainsKey("ARBI_REDIS_RUNTIME_ENABLED")) { [string]$settings["ARBI_REDIS_RUNTIME_ENABLED"] } else { $redisEnabledRaw }
    $sessionEnabledRaw = if ($settings.ContainsKey("ARBI_REDIS_SESSION_ENABLED")) { [string]$settings["ARBI_REDIS_SESSION_ENABLED"] } else { $redisEnabledRaw }

    $runtimeEnabled = ConvertTo-BoolSetting -Value $runtimeEnabledRaw -Default $true
    $sessionEnabled = ConvertTo-BoolSetting -Value $sessionEnabledRaw -Default $true
    $redisNeeded = $runtimeEnabled -or $sessionEnabled

    $redisHost = "127.0.0.1"
    if ($settings.ContainsKey("ARBI_REDIS_HOST") -and [string]::IsNullOrWhiteSpace([string]$settings["ARBI_REDIS_HOST"]) -eq $false) {
        $redisHost = [string]$settings["ARBI_REDIS_HOST"]
    }

    $port = 6379
    if ($settings.ContainsKey("ARBI_REDIS_PORT")) {
        $rawPort = [string]$settings["ARBI_REDIS_PORT"]
        if ($rawPort -match '^\d+$') {
            $port = [int]$rawPort
        }
    }

    $configuredServerPath = $null
    if ($settings.ContainsKey("ARBI_REDIS_SERVER_PATH")) {
        $rawPath = [string]$settings["ARBI_REDIS_SERVER_PATH"]
        if (-not [string]::IsNullOrWhiteSpace($rawPath)) {
            $configuredServerPath = ConvertTo-AbsolutePath -PathValue $rawPath
        }
    }
    $serverPath = Resolve-RedisServerPath -ConfiguredPath $configuredServerPath

    return @{
        Needed = $redisNeeded
        RuntimeEnabled = $runtimeEnabled
        SessionEnabled = $sessionEnabled
        Host = $redisHost
        Port = $port
        ConfiguredServerPath = $configuredServerPath
        ServerPath = $serverPath
    }
}

function Test-TcpEndpoint {
    param(
        [string]$EndpointHost,
        [int]$EndpointPort,
        [int]$TimeoutMilliseconds = 500
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $asyncResult = $client.BeginConnect($EndpointHost, $EndpointPort, $null, $null)
        if (-not $asyncResult.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            return $false
        }

        $client.EndConnect($asyncResult)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
        if ($asyncResult -and $asyncResult.AsyncWaitHandle) {
            $asyncResult.AsyncWaitHandle.Close()
        }
    }
}

function Start-RedisIfNeeded {
    $redisConfig = Get-RedisStartupConfig
    if (-not $redisConfig.Needed) {
        Write-Host "[INFO] Redis auto-start skipped: runtime/session cache is disabled by current .env settings."
        return
    }

    if (Test-TcpEndpoint -EndpointHost $redisConfig.Host -EndpointPort $redisConfig.Port) {
        Write-Host ("[INFO] Redis already available at {0}:{1}. Skip auto-start." -f $redisConfig.Host, $redisConfig.Port)
        return
    }

    if ([string]::IsNullOrWhiteSpace([string]$redisConfig.ServerPath)) {
        if ([string]::IsNullOrWhiteSpace([string]$redisConfig.ConfiguredServerPath)) {
            Write-Host "[WARN] Redis is enabled, but no local redis-server.exe was found."
        } else {
            Write-Host ("[WARN] Redis is enabled, but redis-server.exe was not found at the configured path: " + $redisConfig.ConfiguredServerPath)
        }
        Write-Host "[WARN] Continuing startup without Redis bootstrap. The web app will still start, and Redis-backed cache features will remain degraded until Redis is available."
        return
    }

    Write-Host ("[INFO] Redis is not listening on {0}:{1}. Starting local redis-server.exe..." -f $redisConfig.Host, $redisConfig.Port)
    try {
        Start-Process -FilePath $redisConfig.ServerPath -WorkingDirectory (Split-Path -Parent $redisConfig.ServerPath) -WindowStyle Hidden -ArgumentList @(
            "--bind", $redisConfig.Host,
            "--port", [string]$redisConfig.Port,
            "--appendonly", "no"
        ) | Out-Null
    } catch {
        Write-Host ("[WARN] Failed to start redis-server.exe: " + $_.Exception.Message)
        Write-Host "[WARN] Continuing startup without Redis bootstrap. The web app will still start, and Redis-backed cache features will remain degraded until Redis is available."
        return
    }

    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-TcpEndpoint -EndpointHost $redisConfig.Host -EndpointPort $redisConfig.Port) {
            Write-Host ("[INFO] Redis started successfully: " + $redisConfig.ServerPath)
            return
        }
    }

    Write-Host ("[WARN] Redis start command was executed, but {0}:{1} is still unavailable." -f $redisConfig.Host, $redisConfig.Port)
    Write-Host "[WARN] Continuing startup without Redis bootstrap. The web app will still start, and Redis-backed cache features will remain degraded until Redis is available."
}

function Get-ListenerPids {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) {
        return @()
    }

    return @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Get-TargetPids {
    $processMap = Get-ProcessMap
    $targets = New-Object "System.Collections.Generic.HashSet[int]"
    $mainAllPattern = "*-m app.main all*--port $Port*"
    $workerPattern = "*-m app.main worker*"
    $webPattern = "*-m app.main web*--port $Port*"
    $legacyUvicornPattern = "*uvicorn*app.main:app*--port $Port*"

    foreach ($processId in Get-ListenerPids) {
        [void]$targets.Add([int]$processId)

        $current = $processMap[[int]$processId]
        while ($current -and $current.ParentProcessId -and $processMap.ContainsKey([int]$current.ParentProcessId)) {
            $parent = $processMap[[int]$current.ParentProcessId]
            $isProjectPython = Test-SamePath -Left $parent.ExecutablePath -Right $venvPython
            $isMainPython = $parent.Name -eq "python.exe" -and (
                $parent.CommandLine -like $mainAllPattern -or
                $parent.CommandLine -like $webPattern
            )
            $isUvicornPython = $parent.Name -eq "python.exe" -and $parent.CommandLine -like $legacyUvicornPattern

            if (-not ($isProjectPython -or $isMainPython -or $isUvicornPython)) {
                break
            }

            [void]$targets.Add([int]$parent.ProcessId)
            $current = $parent
        }
    }

    $projectProcesses = Get-CimInstance Win32_Process | Where-Object {
        $commandLine = [string]$_.CommandLine
        $matchesManagedCommand = (
            $commandLine -like $mainAllPattern -or
            $commandLine -like $webPattern -or
            $commandLine -like $workerPattern -or
            $commandLine -like $legacyUvicornPattern
        )
        if (-not $matchesManagedCommand) {
            return $false
        }

        return $_.Name -eq "python.exe"
    }

    foreach ($process in $projectProcesses) {
        [void]$targets.Add([int]$process.ProcessId)
    }

    return @($targets)
}

function Show-Status {
    $processMap = Get-ProcessMap
    $listenerPids = Get-ListenerPids
    $managedProcesses = Get-CimInstance Win32_Process | Where-Object {
        (Test-SamePath -Left $_.ExecutablePath -Right $venvPython) -and
        $_.CommandLine -like "*-m app.main*"
    }

    Write-Host ("Project root : " + $projectRoot)
    Write-Host ("Venv python  : " + $venvPython)
    Write-Host ("Host         : " + $BindHost)
    Write-Host ("Port         : " + $Port)

    if (-not $listenerPids.Count) {
        Write-Host "Listener     : none"
    } else {
        foreach ($processId in $listenerPids) {
            $process = $processMap[[int]$processId]
            if (-not $process) {
                continue
            }

            Write-Host ""
            Write-Host ("Listener PID : " + $process.ProcessId)
            Write-Host ("Executable   : " + $process.ExecutablePath)
            Write-Host ("CommandLine  : " + $process.CommandLine)

            if ($process.ParentProcessId -and $processMap.ContainsKey([int]$process.ParentProcessId)) {
                $parent = $processMap[[int]$process.ParentProcessId]
                Write-Host ("Parent PID   : " + $parent.ProcessId)
                Write-Host ("Parent EXE   : " + $parent.ExecutablePath)
                Write-Host ("Parent CMD   : " + $parent.CommandLine)
            }
        }
    }

    if ($managedProcesses) {
        Write-Host ""
        Write-Host "Managed processes:"
        foreach ($process in $managedProcesses) {
            Write-Host ("  PID " + $process.ProcessId + " : " + $process.CommandLine)
        }
    }
}

function Cleanup-Port {
    $targets = Get-TargetPids
    if (-not $targets.Count) {
        Write-Host ("No matching service found on port " + $Port + ".")
        return $true
    }

    foreach ($processId in ($targets | Sort-Object -Descending)) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host ("Stopped PID  : " + $processId)
        } catch {
            Write-Host ("Skip PID     : " + $processId + " (" + $_.Exception.Message + ")")
        }
    }

    Start-Sleep -Seconds 2

    if (Get-ListenerPids) {
        Write-Host ("Warning      : port " + $Port + " is still occupied.")
        return $false
    }

    Write-Host ("Port " + $Port + " is now free.")
    return $true
}

function Start-LoginProbe {
    $probeCommand = @"
$ProgressPreference='SilentlyContinue'
for (`$i = 0; `$i -lt 30; `$i++) {
    try {
        `$resp = Invoke-WebRequest -Uri '$loginUrl' -UseBasicParsing -TimeoutSec 2
        if (`$resp.StatusCode -eq 200) {
            Start-Process '$loginUrl'
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}
"@

    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", $probeCommand
    ) | Out-Null
}

function Start-ServiceChain {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw ("Missing virtual environment python: " + $venvPython)
    }

    Write-Host ""
    Write-Host "=========================================="
    Write-Host "  Arbitrage system starting..."
    Write-Host ("  URL: " + $loginUrl)
    Write-Host "=========================================="
    Write-Host ""

    $targets = Get-TargetPids
    if ($targets.Count) {
        Write-Host ("[INFO] Detected " + $targets.Count + " residual process(es). Cleaning up before restart...")
        if (-not (Cleanup-Port)) {
            throw ("Port " + $Port + " is still occupied after cleanup.")
        }
    } else {
        Write-Host "[INFO] No residual process detected. Starting directly..."
    }

    Start-RedisIfNeeded

    Write-Host "[INFO] Starting unified entrypoint (Web + Worker)..."
    Write-Host "[INFO] Initialization, Web, and Worker are all started via app.main."
    Start-LoginProbe
    & $venvPython -m app.main all --host $BindHost --port $Port
}

switch ($Mode) {
    "start" { Start-ServiceChain }
    "cleanup" { Cleanup-Port }
    "status" { Show-Status }
}
