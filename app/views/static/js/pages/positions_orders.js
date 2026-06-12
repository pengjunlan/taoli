import { bindListPagination, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

const POLL_INTERVAL_MS = 5000;

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

function renderPositionsRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="7" class="spread-metric">当前还没有规则命中的候选持仓。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.status || "候选中")}</span>
            </div>
          </td>
          <td>${escapeHtml(row.strategy)}</td>
          <td>
            <div class="pair-cell pair-cell--spread">
              <span class="pair-cell__line is-positive">主腿 / ${escapeHtml(row.long_exchange)}</span>
              <span class="pair-cell__line is-negative">对冲 / ${escapeHtml(row.short_exchange)}</span>
            </div>
          </td>
          <td class="spread-metric spread-metric--strong">${escapeHtml(row.size)}</td>
          <td>
            <span class="pill pill--warning">${escapeHtml(row.hedge)}</span>
          </td>
          <td class="spread-value">${escapeHtml(row.pnl)}</td>
          <td>${escapeHtml(row.reason || "--")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderOrderRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="8" class="spread-metric">当前还没有候选执行记录。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td class="spread-metric">${escapeHtml(row.time)}</td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.strategy || "--")}</span>
            </div>
          </td>
          <td>${escapeHtml(row.exchange)}</td>
          <td class="spread-value">${escapeHtml(row.side)}</td>
          <td><span class="pill pill--${escapeHtml(row.status_tone || "brand")}">${escapeHtml(row.status)}</span></td>
          <td class="spread-metric">${escapeHtml(row.size)}</td>
          <td>${escapeHtml(row.reason || "--")}</td>
          <td class="spread-metric">未下单</td>
        </tr>
      `,
    )
    .join("");
}

function renderFillRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="6" class="spread-metric">真实成交回报尚未接入，当前只展示规则命中与候选执行记录。</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td class="spread-metric">${escapeHtml(row.time)}</td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.symbol).replace("USDT", "/USDT")}</span>
            </div>
          </td>
          <td>${escapeHtml(row.exchange)}</td>
          <td class="spread-value">${escapeHtml(row.side)}</td>
          <td class="spread-metric">${escapeHtml(row.price)}</td>
          <td class="spread-metric">${escapeHtml(row.size)}</td>
        </tr>
      `,
    )
    .join("");
}

async function refreshRuntimeRows({ silent = false } = {}) {
  const result = await getJson("/api/strategy-runtime");
  if (!result.success) {
    if (!silent) {
      throw new Error(result.message || "读取策略运行态失败。");
    }
    return;
  }

  updateSummaryCards(result.summary_cards || []);
  updateRuntimeStatus(result.runtime_status);

  const positionsBody = document.querySelector("[data-positions-table-body]");
  const ordersBody = document.querySelector("[data-orders-table-body]");
  const fillsBody = document.querySelector("[data-fills-table-body]");
  const generatedAt = document.querySelector("[data-runtime-generated-at]");
  const candidateCount = document.querySelector("[data-runtime-candidate-count]");

  if (positionsBody) positionsBody.innerHTML = renderPositionsRows(result.positions_rows || []);
  if (ordersBody) ordersBody.innerHTML = renderOrderRows(result.order_rows || []);
  if (fillsBody) fillsBody.innerHTML = renderFillRows(result.fill_rows || []);
  if (generatedAt) generatedAt.textContent = `最近生成：${String(result.generated_at || "--")}`;
  if (candidateCount) candidateCount.textContent = `候选 ${Number((result.candidate_rows || []).length)} 条`;

  refreshListPagination(document);
}

bindListPagination();
bindLogoutAction();
refreshRuntimeRows().catch((error) => {
  showToast(error?.message || "读取策略运行态失败，请稍后再试。");
});
window.setInterval(() => {
  refreshRuntimeRows({ silent: true }).catch(() => {});
}, POLL_INTERVAL_MS);
