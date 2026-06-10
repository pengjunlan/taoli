import { bindListPagination, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

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
    data = { success: false, message: "服务响应格式错误" };
  }

  if (!data.message && typeof data.detail === "string" && data.detail.trim()) {
    data.message = data.detail.trim();
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试";
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

    container.className = `stats-card stats-card--${String(card.tone || "neutral")}`;
  });
}

function renderDashboardRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="11" class="spread-metric">暂无可用机会</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.rank)}</td>
          <td><span class="pill pill--${escapeHtml(row.type_tone || "brand")}">${escapeHtml(row.type)}</span></td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.symbol)}/USDT</span>
            </div>
          </td>
          <td>
            <div class="pair-cell">
              <span class="pair-cell__line ${row.line_a_tone === "positive" ? "is-positive" : "is-negative"}">${escapeHtml(row.line_a)}</span>
              <span class="pair-cell__line ${row.line_b_tone === "positive" ? "is-positive" : "is-negative"}">${escapeHtml(row.line_b)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-value">${escapeHtml(row.yield_value)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.yield_label)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-fee">${escapeHtml(row.metric_value)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.metric_label)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="${row.edge_tone === "positive" ? "is-positive" : row.edge_tone === "negative" ? "is-negative" : ""}">${escapeHtml(row.edge_value)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.edge_label)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive"><span>${escapeHtml(row.qty_long)}</span></span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative"><span>${escapeHtml(row.qty_short)}</span></span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive"><span>${escapeHtml(row.avg_long)}</span></span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative"><span>${escapeHtml(row.avg_short)}</span></span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive spread-metric--strong"><span>${escapeHtml(row.value_long)}</span></span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative spread-metric--strong"><span>${escapeHtml(row.value_short)}</span></span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-metric">${escapeHtml(row.highlight_value)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.highlight_label)}</span>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

async function refreshDashboard() {
  const result = await getJson("/api/dashboard");
  if (!result.success) {
    throw new Error(result.message || "读取首页数据失败");
  }

  updateSummaryCards(result.summary_cards || []);

  const body = document.querySelector("[data-dashboard-table-body]");
  const count = document.querySelector("[data-dashboard-count]");
  if (body) {
    body.innerHTML = renderDashboardRows(result.dashboard_rows || []);
  }
  if (count) {
    count.textContent = `共 ${Number(result.dashboard_count || 0)} 个机会`;
  }

  refreshListPagination(document);
}

bindListPagination();
bindLogoutAction();
refreshDashboard().catch((error) => {
  showToast(error?.message || "读取首页数据失败，请稍后再试");
});
