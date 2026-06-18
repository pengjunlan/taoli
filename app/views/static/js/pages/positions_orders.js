import { createLiveSocket } from "../core/live-socket.js";
import { bindListPagination, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

let liveSocket = null;
let latestPayload = {};
let isClosingExecution = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

async function postJson(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    body: JSON.stringify(payload),
    credentials: "same-origin",
  });

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { success: false, message: "服务响应格式错误。" };
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

function updateSummaryCards(cards) {
  const list = Array.isArray(cards) ? cards : [];
  list.forEach((card) => {
    const key = String(card?.key || "").trim();
    if (!key) return;

    const container = document.querySelector(`[data-summary-card="${key}"]`);
    if (!container) return;

    const label = container.querySelector("[data-summary-label]");
    const value = container.querySelector("[data-summary-value]");
    const change = container.querySelector("[data-summary-change]");

    if (label) label.textContent = String(card.label || "");
    if (value) value.textContent = String(card.value || "");
    if (change) change.textContent = String(card.change || "");

    container.className = `stats-card stats-card--${String(card.tone || "brand")}`;
  });
}

function updateRuntimeStatus(runtimeStatus) {
  const card = document.querySelector("[data-runtime-status-card]");
  if (!card) return;

  const status = runtimeStatus || {};
  const state = String(status.state || "").trim();
  const pill = card.querySelector("[data-runtime-status-pill]");
  const label = card.querySelector("[data-runtime-status-label]");
  const message = card.querySelector("[data-runtime-status-message]");
  const meta = card.querySelector("[data-runtime-status-meta]");

  if (state === "ready") {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  if (pill) {
    pill.textContent = String(status.label || "预热中");
    pill.className = `pill pill--${String(status.tone || "neutral")}`;
  }
  if (label) {
    label.textContent = state === "stale" ? "当前展示历史快照" : "当前正在初始化策略运行态";
  }
  if (message) {
    message.textContent = String(status.message || "");
  }
  if (meta) {
    meta.textContent = `最近生成 ${String(status.generated_at || "--")} / 最近刷新 ${String(status.updated_at || "--")}`;
  }
}

function renderActivePositionRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="13" class="spread-metric">当前还没有进入真实套利中的持仓组合。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td class="spread-metric">${escapeHtml(row.rank)}</td>
          <td><span class="pill pill--${escapeHtml(row.type_tone || "brand")}">${escapeHtml(row.type_label)}</span></td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.status || "--")}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--spread">
              <span class="pair-cell__line is-positive">${escapeHtml(row.pair_primary_text)}</span>
              <span class="pair-cell__line is-negative">${escapeHtml(row.pair_secondary_text)}</span>
            </div>
          </td>
          <td class="spread-metric">${escapeHtml(row.net_spread || "--")}</td>
          <td class="spread-metric">${escapeHtml(row.net_rate || "--")}</td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.current_price_primary || "--")}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.current_price_secondary || "--")}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.funding_rate_primary || "--")}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.funding_rate_secondary || "--")}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.fee_rate_primary || "--")}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.fee_rate_secondary || "--")}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.position_qty_primary || "--")}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.position_qty_secondary || "--")}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive spread-metric--strong">${escapeHtml(row.position_value_primary || "--")}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative spread-metric--strong">${escapeHtml(row.position_value_secondary || "--")}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-metric spread-metric--strong">${escapeHtml(row.key_field_value || "--")}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.key_field_label || "--")}</span>
            </div>
          </td>
          <td>
            <button
              class="table-action table-action--danger runtime-close-action"
              type="button"
              data-runtime-close
              data-execution-id="${escapeHtml(row.execution_id || 0)}"
              ${row.can_close ? "" : "disabled"}
            >
              ${escapeHtml(row.close_button_text || "一键平仓")}
            </button>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderActiveOrderRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="14" class="spread-metric">当前没有正在挂单或等待成交的实际订单。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td class="spread-metric">${escapeHtml(row.row_code || row.pair_key || "--")}</td>
          <td class="spread-metric">${escapeHtml(row.time)}</td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.strategy)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.exchange)}</td>
          <td>${escapeHtml(row.leg_role)}</td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge">${escapeHtml(row.execution_action)}</span>
              <span class="pair-cell__line pair-cell__line--hedge">${escapeHtml(row.action)}</span>
            </div>
          </td>
          <td><span class="pill pill--${escapeHtml(row.status_tone || "brand")}">${escapeHtml(row.status)}</span></td>
          <td class="spread-metric">${escapeHtml(row.requested_price)}</td>
          <td class="spread-metric">${escapeHtml(row.requested_quantity)}</td>
          <td class="spread-metric">${escapeHtml(row.filled_quantity)}</td>
          <td class="spread-metric">${escapeHtml(row.requested_value)}</td>
          <td class="spread-metric">${escapeHtml(row.filled_value)}</td>
          <td class="spread-metric">${escapeHtml(row.retry_count)}</td>
          <td>${escapeHtml(row.reason || "--")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderHistoryOrderRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="12" class="spread-metric">当前还没有历史订单记录。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td class="spread-metric">${escapeHtml(row.row_code || row.pair_key || "--")}</td>
          <td class="spread-metric">${escapeHtml(row.time)}</td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.strategy)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.exchange)}</td>
          <td>${escapeHtml(row.leg_role)}</td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge">${escapeHtml(row.execution_action)}</span>
              <span class="pair-cell__line pair-cell__line--hedge">${escapeHtml(row.action)}</span>
            </div>
          </td>
          <td><span class="pill pill--${escapeHtml(row.status_tone || "brand")}">${escapeHtml(row.status)}</span></td>
          <td class="spread-metric">${escapeHtml(row.avg_fill_price)}</td>
          <td class="spread-metric">${escapeHtml(row.filled_quantity)}</td>
          <td class="spread-metric">${escapeHtml(row.filled_value)}</td>
          <td class="spread-metric">${escapeHtml(row.fill_count)}</td>
          <td>${escapeHtml(row.result || "--")}</td>
        </tr>
      `,
    )
    .join("");
}

function bindRuntimeTabs() {
  const triggers = Array.from(document.querySelectorAll("[data-runtime-tab-trigger]"));
  const panels = Array.from(document.querySelectorAll("[data-runtime-tab-panel]"));
  if (!triggers.length || !panels.length) return;

  const activateTab = (tabKey) => {
    triggers.forEach((trigger) => {
      const isActive = trigger.getAttribute("data-runtime-tab-trigger") === tabKey;
      trigger.classList.toggle("is-active", isActive);
      trigger.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    panels.forEach((panel) => {
      const isActive = panel.getAttribute("data-runtime-tab-panel") === tabKey;
      panel.classList.toggle("is-active", isActive);
      panel.hidden = !isActive;
    });

    refreshListPagination(document);
  };

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      activateTab(trigger.getAttribute("data-runtime-tab-trigger"));
    });
  });
}

function bindCloseActions() {
  document.querySelectorAll("[data-runtime-close]").forEach((button) => {
    button.addEventListener("click", async () => {
      const executionId = Number(button.dataset.executionId || 0);
      if (!executionId || isClosingExecution || button.disabled) return;

      const confirmed = window.confirm("确认对当前套利组合发起一键平仓吗？");
      if (!confirmed) return;

      isClosingExecution = true;
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = "提交中...";

      try {
        const result = await postJson(`/api/strategy-runtime/${executionId}/close`);
        if (!result.success) {
          throw new Error(result.message || "发起一键平仓失败。");
        }
        showToast(result.message || "已发起一键平仓。");
        await refreshRuntimeRows();
      } catch (error) {
        button.disabled = false;
        button.textContent = originalText;
        showToast(error?.message || "发起一键平仓失败，请稍后再试。");
      } finally {
        isClosingExecution = false;
      }
    });
  });
}

function applyPayload(result) {
  latestPayload = result || {};

  updateSummaryCards(latestPayload.summary_cards || []);
  updateRuntimeStatus(latestPayload.runtime_status);

  const activePositionsBody = document.querySelector("[data-runtime-active-positions-body]");
  const activeOrdersBody = document.querySelector("[data-runtime-active-orders-body]");
  const historyOrdersBody = document.querySelector("[data-runtime-history-orders-body]");
  const generatedAt = document.querySelector("[data-runtime-generated-at]");
  const activePositionCount = document.querySelector("[data-runtime-active-position-count]");
  const activeOrderCount = document.querySelector("[data-runtime-active-order-count]");
  const historyOrderCount = document.querySelector("[data-runtime-history-order-count]");

  if (activePositionsBody) {
    activePositionsBody.innerHTML = renderActivePositionRows(latestPayload.active_positions_rows || []);
  }
  if (activeOrdersBody) {
    activeOrdersBody.innerHTML = renderActiveOrderRows(latestPayload.active_order_rows || []);
  }
  if (historyOrdersBody) {
    historyOrdersBody.innerHTML = renderHistoryOrderRows(latestPayload.history_order_rows || []);
  }
  if (generatedAt) {
    generatedAt.textContent = `最近生成：${String(latestPayload.generated_at || "--")}`;
  }
  if (activePositionCount) {
    activePositionCount.textContent = `共 ${Number((latestPayload.active_positions_rows || []).length)} 个组合`;
  }
  if (activeOrderCount) {
    activeOrderCount.textContent = `共 ${Number((latestPayload.active_order_rows || []).length)} 条当前订单`;
  }
  if (historyOrderCount) {
    historyOrderCount.textContent = `共 ${Number((latestPayload.history_order_rows || []).length)} 条历史订单`;
  }

  refreshListPagination(document);
  bindCloseActions();
}

async function refreshRuntimeRows() {
  const result = await getJson("/api/strategy-runtime");
  if (!result.success) {
    throw new Error(result.message || "读取策略运行态失败。");
  }
  applyPayload(result);
}

function startLiveUpdates() {
  liveSocket?.close();
  liveSocket = createLiveSocket({
    channel: "strategy-runtime",
    suppressErrorToast: true,
    onMessage(payload) {
      if (!payload?.success) {
        return;
      }
      applyPayload(payload);
    },
  });
}

bindListPagination();
bindLogoutAction();
bindRuntimeTabs();
refreshRuntimeRows()
  .then(() => {
    startLiveUpdates();
  })
  .catch((error) => {
    showToast(error?.message || "读取策略运行态失败，请稍后再试。");
    startLiveUpdates();
  });

window.addEventListener("beforeunload", () => {
  liveSocket?.close();
});
