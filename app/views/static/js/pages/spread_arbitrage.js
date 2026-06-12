import { bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction, showToast } from "../core/utils.js";

const PAGE_SIZE = 5;
let currentPage = 1;

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

function renderSpreadRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="11">
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
        <tr>
          <td class="spread-rank">${escapeHtml(row.rank)}</td>
          <td><span class="pill pill--positive">价差套利</span></td>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.symbol)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.symbol)}/USDT</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--spread">
              <span class="pair-cell__line is-positive">买入 ${escapeHtml(row.symbol)}/USDT / ${escapeHtml(row.buy_exchange)}</span>
              <span class="pair-cell__line is-negative">卖出 ${escapeHtml(row.symbol)}/USDT / ${escapeHtml(row.sell_exchange)}</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="spread-value">${escapeHtml(row.latest_spread)}</strong>
              <span class="spread-symbol__hint">最新价差</span>
            </div>
          </td>
          <td>
            <div class="spread-symbol">
              <strong class="${String(row.net_spread || "").includes("+") ? "is-positive" : "is-negative"} spread-value">${escapeHtml(row.net_spread)}</strong>
              <span class="spread-symbol__hint">净价差</span>
            </div>
          </td>
          <td>
            <div class="pair-cell pair-cell--hedge">
              <span class="pair-cell__line pair-cell__line--hedge is-positive">${escapeHtml(row.buy_exchange)} ${escapeHtml(row.buy_fee_rate)}</span>
              <span class="pair-cell__line pair-cell__line--hedge is-negative">${escapeHtml(row.sell_exchange)} ${escapeHtml(row.sell_fee_rate)}</span>
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
              <strong class="spread-metric spread-metric--strong">${escapeHtml(row.opportunity_time)}</strong>
              <span class="spread-symbol__hint">机会时间</span>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderPagination(totalItems, page, pageCount) {
  const start = totalItems === 0 ? 0 : ((page - 1) * PAGE_SIZE) + 1;
  const end = Math.min(page * PAGE_SIZE, totalItems);
  return `
    <div class="pagination-bar">
      <div class="pagination-bar__meta">显示 ${start}-${end} / 共 ${totalItems} 条</div>
      <div class="pagination-bar__actions">
        <button class="table-action table-action--primary pagination-bar__more" type="button" data-page-action="more"${page >= pageCount ? " disabled" : ""}>更多</button>
        <button class="table-action pagination-bar__prev" type="button" data-page-action="prev"${page <= 1 ? " disabled" : ""}>上一页</button>
        <div class="pagination-bar__pages">
          ${Array.from({ length: pageCount }, (_, index) => index + 1)
            .map((item) => `<button class="table-action pagination-bar__page${item === page ? " is-active" : ""}" type="button" data-page-number="${item}">${item}</button>`)
            .join("")}
        </div>
        <button class="table-action pagination-bar__next" type="button" data-page-action="next"${page >= pageCount ? " disabled" : ""}>下一页</button>
      </div>
    </div>
  `;
}

function bindPagination(pageCount) {
  const host = document.querySelector("[data-spread-pagination]");
  if (!host) return;

  host.querySelectorAll("[data-page-number]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = Number(button.dataset.pageNumber || 1);
      if (page === currentPage) return;
      currentPage = page;
      refreshSpreadRows().catch((error) => {
        showToast(error?.message || "读取价差套利机会失败，请稍后再试。");
      });
    });
  });

  host.querySelectorAll("[data-page-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = String(button.dataset.pageAction || "");
      if (action === "prev" && currentPage > 1) {
        currentPage -= 1;
      } else if ((action === "next" || action === "more") && currentPage < pageCount) {
        currentPage += 1;
      } else {
        return;
      }
      refreshSpreadRows().catch((error) => {
        showToast(error?.message || "读取价差套利机会失败，请稍后再试。");
      });
    });
  });
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

async function refreshSpreadRows() {
  const result = await getJson(`/api/spread-opportunities?page=${currentPage}&page_size=${PAGE_SIZE}`);
  if (!result.success) {
    throw new Error(result.message || "读取价差套利机会失败。");
  }

  const body = document.querySelector("[data-spread-table-body]");
  const count = document.querySelector("[data-spread-count]");
  const pager = document.querySelector("[data-spread-pagination]");

  if (body) {
    body.innerHTML = renderSpreadRows(result.rows || []);
  }
  if (count) {
    const runtimeStatus = result.runtime_status || {};
    const suffix = runtimeStatus.is_ready ? "实时" : runtimeStatus.state === "stale" ? "快照" : "预热";
    count.textContent = `共 ${Number(result.opportunity_count || 0)} 个机会 · ${suffix}`;
  }
  if (pager) {
    pager.innerHTML = renderPagination(
      Number(result.opportunity_count || 0),
      Number(result.page || 1),
      Number(result.page_count || 1),
    );
    bindPagination(Number(result.page_count || 1));
  }

  updateRuntimeBanner(result.runtime_status, result.diagnostics);
}

bindPrototypeActions();
bindLogoutAction();
refreshSpreadRows().catch((error) => {
  showToast(error?.message || "读取价差套利机会失败，请稍后再试。");
});
