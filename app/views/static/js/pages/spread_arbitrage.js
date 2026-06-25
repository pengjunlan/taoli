import { createLiveSocket } from "../core/live-socket.js";
import { bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

const PAGE_SIZE = 5;
const BEIJING_TIME_ZONE = "Asia/Shanghai";

let currentPage = 1;
let latestRows = [];
let latestRuntimeStatus = {};
let latestDiagnostics = {};
let latestOpportunityCount = 0;
let latestPageCount = 1;
let lockedRowKeys = [];
let liveSocket = null;
let activeSocketPage = 0;
let requestToken = 0;
let settlementClockHandle = null;

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
    headers: { "X-Requested-With": "XMLHttpRequest" },
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

function toSettlementMs(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

function formatSettlementCountdown(settlementAtMs) {
  if (!Number.isFinite(settlementAtMs) || settlementAtMs <= 0) {
    return "--";
  }
  const diffMs = Math.max(0, settlementAtMs - Date.now());
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatSettlementTime(settlementAtMs) {
  if (!Number.isFinite(settlementAtMs) || settlementAtMs <= 0) {
    return "--";
  }
  const date = new Date(settlementAtMs);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function getStatusMeta(statusCode) {
  const normalized = Number(statusCode || 0);
  if (normalized === 1) return { label: "正常", tone: "positive" };
  if (normalized === 2) return { label: "数据过期", tone: "warning" };
  if (normalized === 3) return { label: "价差过大", tone: "negative" };
  if (normalized === 4) return { label: "数据缺失", tone: "neutral" };
  if (normalized === 5) return { label: "冻结", tone: "neutral" };
  return { label: "--", tone: "neutral" };
}

function formatStatusTime(statusTimeMs, fallbackText) {
  const numeric = Number(statusTimeMs);
  if (Number.isFinite(numeric) && numeric > 0) {
    const date = new Date(numeric);
    return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
  }
  const normalizedFallback = String(fallbackText || "").trim();
  return normalizedFallback || "--";
}

function formatRawPrice(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "--";
  }
  return String(value);
}

function renderSettlementCell(row) {
  const buySettlementAtMs = toSettlementMs(row.buy_settlement_at_ms ?? row.settlement_at_ms);
  const sellSettlementAtMs = toSettlementMs(row.sell_settlement_at_ms ?? row.settlement_at_ms);
  const buySettlementAttr = buySettlementAtMs ? ` data-settlement-ms="${buySettlementAtMs}"` : "";
  const sellSettlementAttr = sellSettlementAtMs ? ` data-settlement-ms="${sellSettlementAtMs}"` : "";
  return `
    <div class="pair-cell pair-cell--hedge">
      <div class="spread-symbol"${buySettlementAttr}>
        <strong class="pair-cell__line pair-cell__line--hedge is-positive" data-settlement-countdown>${escapeHtml(formatSettlementCountdown(buySettlementAtMs))}</strong>
      </div>
      <div class="spread-symbol"${sellSettlementAttr}>
        <strong class="pair-cell__line pair-cell__line--hedge is-negative" data-settlement-countdown>${escapeHtml(formatSettlementCountdown(sellSettlementAtMs))}</strong>
      </div>
    </div>
  `;
}

function renderSettlementTimeCell(row) {
  const buySettlementAtMs = toSettlementMs(row.buy_settlement_at_ms ?? row.settlement_at_ms);
  const sellSettlementAtMs = toSettlementMs(row.sell_settlement_at_ms ?? row.settlement_at_ms);
  return `
    <div class="pair-cell pair-cell--hedge">
      <div class="spread-symbol">
        <strong class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(formatSettlementTime(buySettlementAtMs))}</strong>
      </div>
      <div class="spread-symbol">
        <strong class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(formatSettlementTime(sellSettlementAtMs))}</strong>
      </div>
    </div>
  `;
}

function refreshSettlementCountdowns() {
  document.querySelectorAll("[data-settlement-countdown][data-settlement-ms]").forEach((node) => {
    const settlementAtMs = toSettlementMs(node.dataset.settlementMs);
    if (!settlementAtMs) return;
    node.textContent = formatSettlementCountdown(settlementAtMs);
  });
}

function ensureSettlementClock() {
  if (settlementClockHandle !== null) return;
  settlementClockHandle = window.setInterval(refreshSettlementCountdowns, 1000);
}

function getOpenCandidateClass(row) {
  return row.open_candidate ? "opportunity-row--open-candidate" : "";
}

function getOpenCandidateTitle(row) {
  if (!row.open_candidate) return "";
  const title = row.open_candidate_reason || row.open_candidate_rule_name || "满足当前用户策略开仓条件";
  return ` title="${escapeHtml(title)}"`;
}

function renderSpreadRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="13">
          <div class="table-empty-state">
            <div class="table-empty-state__icon" aria-hidden="true"></div>
            <div class="table-empty-state__title">暂无可用价差机会</div>
            <p class="table-empty-state__text">请调整筛选条件，或等待新的机会出现。</p>
          </div>
        </td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr class="${getOpenCandidateClass(row)}" data-row-key="${escapeHtml(row.market_pair_key || "")}"${getOpenCandidateTitle(row)}>
          <td class="spread-rank">${escapeHtml(row.rank)}</td>
          <td>
            <div class="status-cell">
              <span class="pill pill--${escapeHtml(getStatusMeta(row.status_code).tone)}">${escapeHtml(getStatusMeta(row.status_code).label)}</span>
              <span class="status-cell__time">${escapeHtml(formatStatusTime(row.status_time_ms, row.status_time))}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.symbol)}/USDT</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--spread">
              <span class="pair-cell__line is-positive">${escapeHtml(row.buy_exchange)}</span>
              <span class="pair-cell__line is-negative">${escapeHtml(row.sell_exchange)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="${String(row.latest_spread || "").includes("+") ? "is-positive" : "is-negative"} spread-value">${escapeHtml(row.latest_spread)}</strong>
              <span class="spread-symbol__hint">价差率</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-fee">${escapeHtml(row.net_rate)}</strong>
              <span class="spread-symbol__hint">4小时净资率</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(formatRawPrice(row.left_price_value))}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(formatRawPrice(row.right_price_value))}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.buy_funding_rate)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.sell_funding_rate)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.buy_fee_rate)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.sell_fee_rate)}</span>
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
              <span class="pair-cell__line pair-cell__line--hedge is-positive spread-metric--strong">${escapeHtml(row.value_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative spread-metric--strong">${escapeHtml(row.value_short)}</span>
            </div>
          </td>
          <td>${renderSettlementTimeCell(row)}</td>
          <td>${renderSettlementCell(row)}</td>
        </tr>
      `,
    )
    .join("");
}

function buildPageItems(page, pageCount) {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const items = [1];
  const start = Math.max(2, page - 2);
  const end = Math.min(pageCount - 1, page + 2);

  if (start > 2) items.push("ellipsis-left");
  for (let value = start; value <= end; value += 1) items.push(value);
  if (end < pageCount - 1) items.push("ellipsis-right");

  items.push(pageCount);
  return items;
}

function renderPagination(totalItems, page, pageCount) {
  const start = totalItems === 0 ? 0 : ((page - 1) * PAGE_SIZE) + 1;
  const end = Math.min(page * PAGE_SIZE, totalItems);
  const pageItems = buildPageItems(page, pageCount);

  return `
    <div class="pagination-bar">
      <div class="pagination-bar__meta">显示 ${start}-${end} / 共 ${totalItems} 条</div>
      <div class="pagination-bar__actions">
        <button class="table-action table-action--primary pagination-bar__more" type="button" data-page-action="more"${page >= pageCount ? " disabled" : ""}>更多</button>
        <button class="table-action pagination-bar__prev" type="button" data-page-action="prev"${page <= 1 ? " disabled" : ""}>上一页</button>
        <div class="pagination-bar__pages">
          ${pageItems
            .map((item) => {
              if (typeof item !== "number") return `<span class="pagination-bar__ellipsis">...</span>`;
              return `<button class="table-action pagination-bar__page${item === page ? " is-active" : ""}" type="button" data-page-number="${item}">${item}</button>`;
            })
            .join("")}
        </div>
        <button class="table-action pagination-bar__next" type="button" data-page-action="next"${page >= pageCount ? " disabled" : ""}>下一页</button>
      </div>
    </div>
  `;
}

function getStatusSuffix() {
  return latestRuntimeStatus.is_ready ? "实时" : latestRuntimeStatus.state === "stale" ? "快照" : "预热";
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

function updateCountLabel() {
  const count = document.querySelector("[data-spread-count]");
  if (!count) return;
  count.textContent = `共 ${Number(latestOpportunityCount || 0)} 个机会 · ${getStatusSuffix()}`;
}

function renderCurrentPage() {
  const body = document.querySelector("[data-spread-table-body]");
  const pager = document.querySelector("[data-spread-pagination]");
  const totalRows = Number(latestOpportunityCount || 0);
  const pageCount = Math.max(1, Number(latestPageCount || 1));

  if (body) {
    body.innerHTML = renderSpreadRows(latestRows);
  }
  updateCountLabel();
  if (pager) {
    pager.innerHTML = renderPagination(totalRows, currentPage, pageCount);
    bindPagination(pageCount);
  }
  updateRuntimeBanner(latestRuntimeStatus, latestDiagnostics);
  refreshSettlementCountdowns();
}

function bindPagination(pageCount) {
  const host = document.querySelector("[data-spread-pagination]");
  if (!host) return;

  host.querySelectorAll("[data-page-number]").forEach((button) => {
    button.addEventListener("click", async () => {
      const page = Number(button.dataset.pageNumber || 1);
      if (page === currentPage) return;
      currentPage = page;
      await reloadCurrentPage();
    });
  });

  host.querySelectorAll("[data-page-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = String(button.dataset.pageAction || "");
      if (action === "prev" && currentPage > 1) {
        currentPage -= 1;
      } else if (action === "next" && currentPage < pageCount) {
        currentPage += 1;
      } else if (action === "more" && currentPage < pageCount) {
        currentPage = Math.min(currentPage + 5, pageCount);
      } else {
        return;
      }
      await reloadCurrentPage();
    });
  });
}

function collectLockedRowKeys(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map((row) => String(row?.market_pair_key || "").trim())
    .filter((key) => key);
}

function replaceRowsInPlace(rows) {
  const body = document.querySelector("[data-spread-table-body]");
  if (!body || !Array.isArray(rows) || !rows.length || !lockedRowKeys.length) {
    return false;
  }

  const rowMap = new Map(
    rows
      .map((row) => [String(row?.market_pair_key || "").trim(), row])
      .filter(([key]) => key),
  );

  let updatedCount = 0;
  body.querySelectorAll("tr[data-row-key]").forEach((tr) => {
    const rowKey = String(tr.dataset.rowKey || "").trim();
    const row = rowMap.get(rowKey);
    if (!row) return;

    const template = document.createElement("template");
    template.innerHTML = renderSpreadRows([row]).trim();
    const nextRow = template.content.firstElementChild;
    if (nextRow) {
      tr.replaceWith(nextRow);
      updatedCount += 1;
    }
  });

  return updatedCount > 0;
}

function applyPayload(result, { fromLive = false } = {}) {
  if (fromLive && activeSocketPage !== currentPage) {
    return;
  }

  const incomingRows = Array.isArray(result.rows) ? result.rows : [];
  latestRuntimeStatus = result.runtime_status || {};
  latestDiagnostics = result.diagnostics || {};
  latestOpportunityCount = Number(result.opportunity_count || incomingRows.length || 0);
  latestPageCount = Math.max(1, Number(result.page_count || 1));

  currentPage = Math.min(Math.max(1, Number(result.page || currentPage || 1)), latestPageCount);
  latestRows = incomingRows;
  lockedRowKeys = collectLockedRowKeys(incomingRows);
  renderCurrentPage();
}

async function loadSpreadPage() {
  const currentToken = requestToken + 1;
  requestToken = currentToken;
  liveSocket?.close();
  liveSocket = null;
  activeSocketPage = 0;
  lockedRowKeys = [];

  const result = await getJson(`/api/spread-opportunities?page=${currentPage}&page_size=${PAGE_SIZE}`);
  if (currentToken !== requestToken) {
    return;
  }
  if (!result.success) {
    throw new Error(result.message || "读取价差套利机会失败。");
  }

  applyPayload(result, { fromLive: false });
  startLiveUpdates();
}

async function reloadCurrentPage() {
  try {
    await loadSpreadPage();
  } catch (error) {
    showToast(error?.message || "读取价差套利机会失败，请稍后再试。");
  }
}

function startLiveUpdates() {
  liveSocket?.close();
  activeSocketPage = currentPage;
  const query = {
    page: currentPage,
    page_size: PAGE_SIZE,
  };
  if (lockedRowKeys.length) {
    query.keys = lockedRowKeys.join(",");
  }
  liveSocket = createLiveSocket({
    channel: "spread",
    query,
    suppressErrorToast: true,
    onMessage(payload) {
      if (!payload?.success) return;
      applyPayload(payload, { fromLive: true });
    },
  });
}

bindPrototypeActions();
bindLogoutAction();
ensureSettlementClock();
reloadCurrentPage();

window.addEventListener("beforeunload", () => {
  liveSocket?.close();
  if (settlementClockHandle !== null) {
    window.clearInterval(settlementClockHandle);
    settlementClockHandle = null;
  }
});
