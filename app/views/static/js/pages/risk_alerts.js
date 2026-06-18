import { bindLogoutAction, showToast } from "../core/utils.js";

const POLL_INTERVAL_MS = 5000;
const MAX_LOG_LINES = 1000;
let hasLoadedRiskWorkers = false;
let lastRiskWorkers = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function getStatusTone(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "running") return "positive";
  if (normalized === "error") return "negative";
  if (normalized === "starting") return "brand";
  return "idle";
}

function getStatusLabel(status) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "running") return "运行中";
  if (normalized === "error") return "异常";
  if (normalized === "starting") return "启动中";
  if (normalized === "idle") return "空闲";
  if (normalized === "primed") return "已初始化";
  return status || "--";
}

function getLevelClass(level) {
  const normalized = String(level || "").trim().toUpperCase();
  if (normalized === "ERROR") return "is-error";
  if (normalized === "WARNING") return "is-warning";
  return "is-info";
}

function normalizeLogs(logs) {
  if (!Array.isArray(logs)) return [];
  return logs
    .map((log) => ({
      time: log?.time || "--",
      level: String(log?.level || "INFO").toUpperCase(),
      message: log?.message || "",
    }))
    .sort((left, right) => String(left.time).localeCompare(String(right.time)))
    .slice(-MAX_LOG_LINES);
}

async function getJson(url) {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
    },
    credentials: "same-origin",
  });

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { success: false, message: "服务响应格式错误。" };
  }

  if (!data.message && typeof data.detail === "string" && data.detail.trim()) {
    data.message = data.detail.trim();
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

function buildWorkerLogs(worker) {
  const logs = normalizeLogs(worker.logs);

  if (!logs.length) {
    return `<div class="risk-console__empty">暂无线程日志</div>`;
  }

  return logs
    .map((log) => {
      const levelClass = getLevelClass(log.level);
      return `
        <div class="risk-console__line">
          <span class="risk-console__time">[${escapeHtml(log.time)}]</span>
          <span class="risk-console__level ${levelClass}">${escapeHtml(log.level)}</span>
          <span class="risk-console__message">${escapeHtml(log.message)}</span>
        </div>
      `;
    })
    .join("");
}

function renderWorkerCards(workers) {
  const container = document.querySelector("[data-risk-worker-list]");
  if (!container) return;

  if (!Array.isArray(workers) || !workers.length) {
    container.innerHTML = `
      <article class="worker-card worker-card--empty">
        <div class="worker-card__head">
          <div>
            <h3>暂无线程</h3>
            <p>当前监控中心还没有注册后台线程。</p>
          </div>
          <span class="worker-status worker-status--idle">未接入</span>
        </div>
      </article>
    `;
    return;
  }

  container.innerHTML = workers
    .map((worker) => {
      const tone = getStatusTone(worker.status);
      const detailText = worker.detail ? escapeHtml(worker.detail) : "--";
      const errorText = worker.last_error_message ? escapeHtml(worker.last_error_message) : "无";
      const logs = normalizeLogs(worker.logs);

      return `
        <article class="worker-card">
          <div class="worker-card__topline">
            <div class="worker-card__identity">
              <h3>${escapeHtml(worker.name || worker.key || "--")}</h3>
              <p>${escapeHtml(worker.category || "--")} / ${escapeHtml(worker.thread_name || "--")}</p>
            </div>
            <div class="worker-card__summary">
              <span>轮询间隔: <strong>${escapeHtml(worker.interval_seconds || 0)} 秒</strong></span>
              <span>最近心跳: <strong>${escapeHtml(worker.last_heartbeat_at || "--")}</strong></span>
              <span>最近成功: <strong>${escapeHtml(worker.last_success_at || "--")}</strong></span>
              <span>最近异常: <strong>${escapeHtml(worker.last_error_at || "无")}</strong></span>
            </div>
            <span class="worker-status worker-status--${tone}">${escapeHtml(getStatusLabel(worker.status))}</span>
          </div>

          <div class="worker-card__meta">
            <span>线程标识: ${escapeHtml(worker.key || "--")}</span>
            <span>状态说明: ${detailText}</span>
            <span>异常说明: ${errorText}</span>
            <span>日志条数: ${logs.length} / ${MAX_LOG_LINES}</span>
          </div>

          <div class="risk-console risk-console--embedded">
            <div class="risk-console__toolbar">
              <span class="risk-console__dot risk-console__dot--danger"></span>
              <span class="risk-console__dot risk-console__dot--warning"></span>
              <span class="risk-console__dot risk-console__dot--success"></span>
              <span class="risk-console__title">worker-log-console</span>
            </div>
            <div class="risk-console__body">${buildWorkerLogs(worker)}</div>
          </div>
        </article>
      `;
    })
    .join("");

  container.querySelectorAll(".risk-console__body").forEach((element) => {
    element.scrollTop = element.scrollHeight;
  });
}

function updateRefreshNote(workers) {
  const note = document.querySelector("[data-risk-refresh-note]");
  if (!note) return;

  const heartbeatList = Array.isArray(workers)
    ? workers
        .map((item) => String(item.last_heartbeat_at || "--"))
        .filter((item) => item && item !== "--")
        .sort()
    : [];

  note.textContent = heartbeatList.length
    ? `最近心跳: ${heartbeatList[heartbeatList.length - 1]}`
    : "暂未收到线程心跳";
}

let refreshLock = false;

async function refreshRiskWorkers({ silent = false } = {}) {
  if (refreshLock) return;
  refreshLock = true;

  try {
    const result = await getJson("/api/risk/workers");
    if (!result.success) {
      throw new Error(result.message || "读取线程监控数据失败。");
    }

    const workers = Array.isArray(result.workers) ? result.workers : [];
    const shouldPreserveWorkers = hasLoadedRiskWorkers && workers.length === 0;

    if (!shouldPreserveWorkers) {
      renderWorkerCards(workers);
      lastRiskWorkers = workers;
      hasLoadedRiskWorkers = hasLoadedRiskWorkers || workers.length > 0;
    } else {
      renderWorkerCards(lastRiskWorkers);
    }
    updateRefreshNote(shouldPreserveWorkers ? lastRiskWorkers : workers);
  } catch (error) {
    if (!silent) {
      showToast(error?.message || "读取线程监控数据失败，请稍后再试。");
    }
  } finally {
    refreshLock = false;
  }
}

function bindRefreshAction() {
  const button = document.querySelector("[data-risk-refresh]");
  if (!button) return;

  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await refreshRiskWorkers();
    } finally {
      button.disabled = false;
    }
  });
}

bindLogoutAction();
bindRefreshAction();
refreshRiskWorkers().catch(() => {});
window.setInterval(() => {
  refreshRiskWorkers({ silent: true }).catch(() => {});
}, POLL_INTERVAL_MS);
