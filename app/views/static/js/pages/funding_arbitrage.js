import { createLiveSocket } from "../core/live-socket.js";
import { bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

const PAGE_SIZE = 5;

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
        <tr data-row-key="${escapeHtml(row.market_pair_key || "")}">
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
              <strong class="spread-value ${String(row.spread || "").includes("+") ? "is-positive" : "is-negative"}">${escapeHtml(row.spread)}</strong>
              <span class="spread-symbol__hint">价差率</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-fee">${escapeHtml(row.net_rate)}</strong>
              <span class="spread-symbol__hint">净资金费率</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.long_exchange)} ${escapeHtml(row.avg_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.short_exchange)} ${escapeHtml(row.avg_short)}</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.long_exchange)} ${escapeHtml(row.long_funding_rate)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.short_exchange)} ${escapeHtml(row.short_funding_rate)}</span>
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
              <span class="pair-cell__line pair-cell__line--hedge is-positive spread-metric--strong">${escapeHtml(row.value_long)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative spread-metric--strong">${escapeHtml(row.value_short)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-metric spread-metric--strong">${escapeHtml(row.settlement)}</strong>
              <span class="spread-symbol__hint">距离结算</span>
            </div>
          </td>
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
  const count = document.querySelector("[data-funding-count]");
  if (!count) return;
  count.textContent = `共 ${Number(latestOpportunityCount || 0)} 个机会 · ${getStatusSuffix()}`;
}

function renderCurrentPage() {
  const body = document.querySelector("[data-funding-table-body]");
  const pager = document.querySelector("[data-funding-pagination]");
  const totalRows = Number(latestOpportunityCount || 0);
  const pageCount = Math.max(1, Number(latestPageCount || 1));

  if (body) {
    body.innerHTML = renderFundingRows(latestRows);
  }
  updateCountLabel();
  if (pager) {
    pager.innerHTML = renderPagination(totalRows, currentPage, pageCount);
    bindPagination(pageCount);
  }
  updateRuntimeBanner(latestRuntimeStatus, latestDiagnostics);
}

function bindPagination(pageCount) {
  const host = document.querySelector("[data-funding-pagination]");
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
  const body = document.querySelector("[data-funding-table-body]");
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
    template.innerHTML = renderFundingRows([row]).trim();
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

async function loadFundingPage() {
  const currentToken = requestToken + 1;
  requestToken = currentToken;
  liveSocket?.close();
  liveSocket = null;
  activeSocketPage = 0;
  lockedRowKeys = [];

  const result = await getJson(`/api/funding-opportunities?page=${currentPage}&page_size=${PAGE_SIZE}`);
  if (currentToken !== requestToken) {
    return;
  }
  if (!result.success) {
    throw new Error(result.message || "读取资金费套利机会失败。");
  }

  applyPayload(result, { fromLive: false });
  startLiveUpdates();
}

async function reloadCurrentPage() {
  try {
    await loadFundingPage();
  } catch (error) {
    showToast(error?.message || "读取资金费套利机会失败，请稍后再试。");
  }
}

function startLiveUpdates() {
  liveSocket?.close();
  activeSocketPage = currentPage;
  liveSocket = createLiveSocket({
    channel: "funding",
    query: {
      page: currentPage,
      page_size: PAGE_SIZE,
    },
    suppressErrorToast: true,
    onMessage(payload) {
      if (!payload?.success) return;
      applyPayload(payload, { fromLive: true });
    },
  });
}

bindPrototypeActions();
bindLogoutAction();
reloadCurrentPage();

window.addEventListener("beforeunload", () => {
  liveSocket?.close();
});
