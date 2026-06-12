import { bindListPagination, bindPrototypeActions, refreshListPagination } from "../core/prototype.js";
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
    data = { success: false, message: "服务响应格式错误。" };
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

function renderFundingRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="12" class="spread-metric">暂无可用资金费套利机会</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.rank)}</td>
          <td><span class="pill pill--brand">资金费套利</span></td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.symbol)}/USDT</span>
            </div>
          </td>
          <td>
            <div class="pair-cell">
              <span class="pair-cell__line is-positive">做多 ${escapeHtml(row.symbol)}/USDT / ${escapeHtml(row.long_exchange)}</span>
              <span class="pair-cell__line is-negative">做空 ${escapeHtml(row.symbol)}/USDT / ${escapeHtml(row.short_exchange)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-value is-positive">${escapeHtml(row.annual)}</strong>
              <span class="spread-symbol__hint">当前年化</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-fee">${escapeHtml(row.net_rate)}</strong>
              <span class="spread-symbol__hint">净资金费率</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-value ${String(row.spread || "").includes("+") ? "is-positive" : "is-negative"}">${escapeHtml(row.spread)}</strong>
              <span class="spread-symbol__hint">价差率</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.long_exchange)} ${escapeHtml(row.long_fee_rate)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.short_exchange)} ${escapeHtml(row.short_fee_rate)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.qty_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.qty_short)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.avg_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.avg_short)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive spread-metric--strong">${escapeHtml(row.value_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative spread-metric--strong">${escapeHtml(row.value_short)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-metric">${escapeHtml(row.settlement)}</strong>
              <span class="spread-symbol__hint">距离结算</span>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function updateRuntimeBanner(runtimeStatus, diagnostics) {
  const banner = document.querySelector("[data-runtime-banner]");
  if (!banner) return;

  const status = runtimeStatus || {};
  const state = String(status.state || "").trim();
  const pill = banner.querySelector("[data-runtime-banner-pill]");
  const label = banner.querySelector("[data-runtime-banner-label]");
  const message = banner.querySelector("[data-runtime-banner-message]");
  const meta = banner.querySelector("[data-runtime-banner-meta]");

  if (state === "ready") {
    banner.hidden = true;
    return;
  }

  banner.hidden = false;
  if (pill) {
    pill.textContent = String(status.label || "预热中");
    pill.className = `pill pill--${String(status.tone || "neutral")}`;
  }
  if (label) {
    label.textContent = state === "stale" ? "当前展示历史快照" : "当前正在初始化机会链路";
  }
  if (message) {
    message.textContent = String(status.message || "");
  }
  if (meta) {
    const generatedAt = String(status.generated_at || "--");
    const pairCount = Number(diagnostics?.active_pair_count || 0);
    meta.textContent = `配对 ${pairCount} 条 / 数据时间 ${generatedAt}`;
  }
}

async function refreshFundingRows() {
  const result = await getJson("/api/funding-opportunities");
  if (!result.success) {
    throw new Error(result.message || "读取资金费套利机会失败。");
  }

  const body = document.querySelector("[data-funding-table-body]");
  const count = document.querySelector("[data-funding-count]");
  if (body) {
    body.innerHTML = renderFundingRows(result.rows || []);
  }
  if (count) {
    const runtimeStatus = result.runtime_status || {};
    const suffix = runtimeStatus.is_ready ? "实时" : runtimeStatus.state === "stale" ? "快照" : "预热";
    count.textContent = `共 ${Number(result.opportunity_count || 0)} 个机会 · ${suffix}`;
  }

  updateRuntimeBanner(result.runtime_status, result.diagnostics);
  refreshListPagination(document);
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
refreshFundingRows().catch((error) => {
  showToast(error?.message || "读取资金费套利机会失败，请稍后再试。");
});
