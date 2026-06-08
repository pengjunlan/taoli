param(
    [ValidateSet("cleanup", "status")]
    [string]$Mode = "status",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$venvPython = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".venv\Scripts\python.exe"))

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

    foreach ($processId in Get-ListenerPids) {
        [void]$targets.Add([int]$processId)

        $current = $processMap[[int]$processId]
        while ($current -and $current.ParentProcessId -and $processMap.ContainsKey([int]$current.ParentProcessId)) {
            $parent = $processMap[[int]$current.ParentProcessId]
            $isProjectLauncher = Test-SamePath -Left $parent.ExecutablePath -Right $venvPython
            $isUvicornPython = $parent.Name -eq "python.exe" -and $parent.CommandLine -like "*uvicorn*app.main:app*--port $Port*"

            if (-not ($isProjectLauncher -or $isUvicornPython)) {
                break
            }

            [void]$targets.Add([int]$parent.ProcessId)
            $current = $parent
        }
    }

    $projectLaunchers = Get-CimInstance Win32_Process | Where-Object {
        (Test-SamePath -Left $_.ExecutablePath -Right $venvPython) -and
        $_.CommandLine -like "*uvicorn*app.main:app*--port $Port*"
    }

    foreach ($process in $projectLaunchers) {
        [void]$targets.Add([int]$process.ProcessId)
    }

    return @($targets)
}

function Show-Status {
    $processMap = Get-ProcessMap
    $listenerPids = Get-ListenerPids

    Write-Host ("Project root : " + $projectRoot)
    Write-Host ("Venv python  : " + $venvPython)
    Write-Host ("Port         : " + $Port)

    if (-not $listenerPids.Count) {
        Write-Host "Listener     : none"
        return
    }

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

            if (Test-SamePath -Left $parent.ExecutablePath -Right $venvPython) {
                Write-Host "Note         : listener is owned by the current project's venv launcher."
                Write-Host "               Seeing both the venv python.exe and the base python.exe"
                Write-Host "               at the same time is normal for this service chain."
            }
        }
    }
}

function Cleanup-Port {
    $targets = Get-TargetPids
    if (-not $targets.Count) {
        Write-Host ("No matching web service found on port " + $Port + ".")
        return
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
    } else {
        Write-Host ("Port " + $Port + " is now free.")
    }
}

switch ($Mode) {
    "cleanup" { Cleanup-Port }
    "status" { Show-Status }
}
