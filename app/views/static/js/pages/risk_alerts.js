import { bindLogoutAction, showToast } from "../core/utils.js";

const POLL_INTERVAL_MS = 5000;
const MAX_LOG_LINES = 1000;

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
      const errorText = worker.last_error_message ? escapeHtml(worker.last_error_message) : "无";
      const detailText = worker.detail ? escapeHtml(worker.detail) : "暂无状态明细";

      return `
        <article class="worker-card">
          <div class="worker-card__head">
            <div>
              <h3>${escapeHtml(worker.name || worker.key || "--")}</h3>
              <p>${escapeHtml(worker.category || "未分类")} / ${escapeHtml(worker.thread_name || "--")}</p>
            </div>
            <span class="worker-status worker-status--${tone}">${escapeHtml(getStatusLabel(worker.status))}</span>
          </div>

          <div class="monitor-grid worker-card__grid">
            <article class="monitor-item">
              <div class="monitor-item__label">线程标识</div>
              <div class="monitor-item__value">${escapeHtml(worker.key || "--")}</div>
              <div class="monitor-item__meta">统一接入监控中心后的唯一标识。</div>
            </article>
            <article class="monitor-item">
              <div class="monitor-item__label">轮询间隔</div>
              <div class="monitor-item__value">${escapeHtml(worker.interval_seconds || 0)} 秒</div>
              <div class="monitor-item__meta">线程当前循环执行间隔。</div>
            </article>
            <article class="monitor-item">
              <div class="monitor-item__label">最近心跳</div>
              <div class="monitor-item__value">${escapeHtml(worker.last_heartbeat_at || "--")}</div>
              <div class="monitor-item__meta">${detailText}</div>
            </article>
            <article class="monitor-item">
              <div class="monitor-item__label">最近成功</div>
              <div class="monitor-item__value">${escapeHtml(worker.last_success_at || "--")}</div>
              <div class="monitor-item__meta">最近一次成功执行时间。</div>
            </article>
            <article class="monitor-item">
              <div class="monitor-item__label">最近异常</div>
              <div class="monitor-item__value">${escapeHtml(worker.last_error_at || "--")}</div>
              <div class="monitor-item__meta">${errorText}</div>
            </article>
          </div>
        </article>
      `;
    })
    .join("");
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
    ? `最近心跳：${heartbeatList[heartbeatList.length - 1]}`
    : "暂未收到线程心跳";
}

function renderLogs(workers) {
  const container = document.querySelector("[data-risk-log-list]");
  const counter = document.querySelector("[data-risk-log-count]");
  if (!container) return;

  const logs = Array.isArray(workers)
    ? workers
        .flatMap((worker) =>
          (Array.isArray(worker.logs) ? worker.logs : []).map((log) => ({
            workerName: worker.name || worker.key || "--",
            threadName: worker.thread_name || "--",
            time: log.time || "--",
            level: String(log.level || "INFO").toUpperCase(),
            message: log.message || "",
          })),
        )
        .sort((left, right) => String(left.time).localeCompare(String(right.time)))
        .slice(-MAX_LOG_LINES)
    : [];

  if (counter) {
    counter.textContent = `${logs.length} / ${MAX_LOG_LINES}`;
  }

  if (!logs.length) {
    container.innerHTML = `<div class="risk-console__empty">暂无线程日志</div>`;
    return;
  }

  container.innerHTML = logs
    .map((log) => {
      const levelClass =
        log.level === "ERROR" ? "is-error" : log.level === "WARNING" ? "is-warning" : "is-info";
      return `
        <div class="risk-console__line">
          <span class="risk-console__time">[${escapeHtml(log.time)}]</span>
          <span class="risk-console__level ${levelClass}">${escapeHtml(log.level)}</span>
          <span class="risk-console__worker">${escapeHtml(log.workerName)}</span>
          <span class="risk-console__thread">(${escapeHtml(log.threadName)})</span>
          <span class="risk-console__message">${escapeHtml(log.message)}</span>
        </div>
      `;
    })
    .join("");

  container.scrollTop = container.scrollHeight;
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
    renderWorkerCards(workers);
    renderLogs(workers);
    updateRefreshNote(workers);
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
