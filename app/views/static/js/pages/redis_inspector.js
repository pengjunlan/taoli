import { bindLogoutAction, showToast } from "../core/utils.js";

const POLL_INTERVAL_MS = 8000;
const REQUEST_TIMEOUT_MS = 4000;
const START_REQUEST_TIMEOUT_MS = 300000;
const REDIS_RESTART_POLL_ATTEMPTS = 12;
const REDIS_RESTART_POLL_INTERVAL_MS = 2000;
const PAGE_SIZE = 20;

let hasLoadedRedisData = false;
let lastOverview = null;
let currentGroups = [];
let currentRows = [];
let activeGroupKey = "";
let currentPage = 1;
let currentTotalRows = 0;
let currentTotalPages = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function getJson(url) {
  return requestJson(url, { method: "GET", timeoutMs: REQUEST_TIMEOUT_MS });
}

async function postJson(url) {
  return requestJson(url, { method: "POST", timeoutMs: START_REQUEST_TIMEOUT_MS });
}

async function requestJson(url, { method, timeoutMs }) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      return { success: false, message: "读取 Redis 数据超时，请检查 Redis 服务状态。" };
    }
    return { success: false, message: "读取 Redis 数据失败，请稍后再试。" };
  } finally {
    window.clearTimeout(timeoutId);
  }

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

function setRedisStartButtonVisible(visible) {
  const button = document.querySelector("[data-redis-start]");
  if (!button) return;
  button.classList.toggle("is-hidden", !visible);
}

function updateSummaryCards(cards) {
  const items = Array.isArray(cards) ? cards : [];
  items.forEach((card) => {
    const root = document.querySelector(`[data-summary-card="${card.key}"]`);
    if (!root) return;

    const value = root.querySelector("[data-summary-value]");
    const change = root.querySelector("[data-summary-change]");
    if (value) value.textContent = card.value ?? "--";
    if (change) change.textContent = card.change ?? "";
  });
}

function normalizeValue(entry) {
  const fields = Array.isArray(entry?.field_rows) ? entry.field_rows : [];
  if (fields.length === 1 && String(fields[0]?.field || "") === "value") {
    return fields[0]?.value ?? entry?.preview ?? "--";
  }

  if (fields.length > 0) {
    return fields
      .map((field) => `${field.field || "--"}: ${field.value || "--"}`)
      .join(" | ");
  }

  if (entry?.preview) {
    return entry.preview;
  }

  return "--";
}

function getGroupKey(group) {
  return String(group?.group_key || group?.group_label || "");
}

function getGroupLabel(group) {
  return group?.group_label || group?.group_key || "--";
}

function getGroupItemCount(group) {
  const numericCount = Number(group?.key_count);
  return Number.isFinite(numericCount) && numericCount >= 0 ? numericCount : 0;
}

function findActiveGroup() {
  return currentGroups.find((group) => getGroupKey(group) === activeGroupKey) || null;
}

function renderGroupSummary() {
  const summary = document.querySelector("[data-redis-group-summary]");
  if (!summary) return;

  const group = findActiveGroup();
  if (!group) {
    summary.textContent = currentGroups.length ? "当前分组暂无可展示的数据。" : "当前没有可展示的 Redis 分组。";
    return;
  }

  summary.textContent = `当前分组：${getGroupLabel(group)} · ${getGroupItemCount(group)} 条数据`;
}

function renderGroupTabs() {
  const container = document.querySelector("[data-redis-group-tabs]");
  if (!container) return;

  if (!currentGroups.length) {
    container.innerHTML = `<div class="redis-group-tabs__empty">当前没有可展示的 Redis 分组</div>`;
    renderGroupSummary();
    return;
  }

  container.innerHTML = currentGroups
    .map((group) => {
      const groupKey = getGroupKey(group);
      const isActive = groupKey === activeGroupKey;
      return `
        <button
          class="redis-group-tab${isActive ? " is-active" : ""}"
          type="button"
          role="tab"
          aria-selected="${isActive}"
          data-redis-group-tab="${escapeHtml(groupKey)}"
        >
          ${escapeHtml(getGroupLabel(group))}
        </button>
      `;
    })
    .join("");

  renderGroupSummary();
}

function updateRefreshNote(result) {
  const note = document.querySelector("[data-redis-refresh-note]");
  if (!note) return;

  const snapshot = result || {};
  const keyCount = Number(snapshot.key_count || 0);
  const groupCount = Number(snapshot.group_count || 0);
  const status = snapshot.is_available ? "Redis 已连接" : "Redis 不可用";
  note.textContent = `${status} · ${groupCount} 个分组 · ${keyCount} 个键`;
  setRedisStartButtonVisible(!snapshot.is_available);
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

function renderPagination() {
  const host = document.querySelector("[data-redis-pagination]");
  if (!host) return;

  const total = currentTotalRows;
  const totalPages = currentTotalPages;
  const page = currentPage;
  const start = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const end = total === 0 ? 0 : Math.min(page * PAGE_SIZE, total);
  const pageItems = totalPages > 0 ? buildPageItems(page, totalPages) : [];

  host.innerHTML = `
    <div class="pagination-bar redis-pagination-bar">
      <div class="pagination-bar__meta">共 ${total} 条，当前显示 ${start}-${end}</div>
      <div class="pagination-bar__actions">
        <button class="table-action table-action--primary pagination-bar__more" type="button" data-page-action="more"${page >= totalPages ? " disabled" : ""}>更多</button>
        <button class="table-action pagination-bar__prev" type="button" data-page-action="prev"${page <= 1 ? " disabled" : ""}>上一页</button>
        <div class="pagination-bar__pages">
          ${pageItems
            .map((item) => {
              if (typeof item !== "number") return `<span class="pagination-bar__ellipsis">...</span>`;
              return `<button class="table-action pagination-bar__page${item === page ? " is-active" : ""}" type="button" data-page-number="${item}">${item}</button>`;
            })
            .join("")}
        </div>
        <button class="table-action pagination-bar__next" type="button" data-page-action="next"${page >= totalPages ? " disabled" : ""}>下一页</button>
      </div>
    </div>
  `;

  bindPagination();
}

function renderTableRows(rows) {
  const tbody = document.querySelector("[data-redis-table-body]");
  if (!tbody) return;

  if (!Array.isArray(rows) || !rows.length) {
    tbody.innerHTML = `
      <tr>
        <td class="redis-empty" colspan="5">当前没有可展示的 Redis 数据</td>
      </tr>
    `;
    renderPagination();
    return;
  }

  const startIndex = (currentPage - 1) * PAGE_SIZE;
  tbody.innerHTML = rows
    .map(
      (row, index) => `
        <tr>
          <td>${startIndex + index + 1}</td>
          <td>
            <div class="redis-key-cell" title="${escapeHtml(row.redisKey || row.key)}">${escapeHtml(row.key)}</div>
            ${
              row.hashField
                ? `<div class="redis-subkey" title="${escapeHtml(row.hashField)}">${escapeHtml(row.hashField)}</div>`
                : row.redisKey
                  ? `<div class="redis-subkey" title="${escapeHtml(row.redisKey)}">${escapeHtml(row.redisKey)}</div>`
                  : ""
            }
          </td>
          <td>
            <div class="redis-value-cell" title="${escapeHtml(row.value)}">${escapeHtml(row.value)}</div>
          </td>
          <td>${escapeHtml(`${row.type} / ${row.source}`)}</td>
          <td>${escapeHtml(row.ttl)}</td>
        </tr>
      `,
    )
    .join("");

  renderPagination();
}

function mapRows(items) {
  return (Array.isArray(items) ? items : []).map((entry) => ({
    key: entry?.key || "--",
    value: normalizeValue(entry),
    type: entry?.type || "--",
    source: entry?.source || "--",
    ttl: entry?.ttl_label || "--",
    redisKey: entry?.redis_key || "",
    hashField: entry?.hash_field || "",
  }));
}

function renderUnavailableState(message, { preserveData = false } = {}) {
  updateSummaryCards([
    {
      key: "redis_status",
      value: "不可用",
      change: message || "Redis 当前不可用，页面暂时无法读取缓存数据。",
    },
    {
      key: "redis_keys",
      value: "0",
      change: "当前没有读取到可展示的 Redis 键。",
    },
    {
      key: "runtime_keys",
      value: "0",
      change: "运行时缓存暂时不可读。",
    },
    {
      key: "session_keys",
      value: "0",
      change: "会话缓存暂时不可读取。",
    },
  ]);

  if (!preserveData) {
    currentGroups = [];
    activeGroupKey = "";
    currentRows = [];
    currentPage = 1;
    currentTotalRows = 0;
    currentTotalPages = 0;
    renderGroupTabs();
    renderTableRows([]);
  }

  updateRefreshNote({
    is_available: false,
    group_count: preserveData && lastOverview ? lastOverview.group_count : 0,
    key_count: preserveData && lastOverview ? lastOverview.key_count : 0,
  });
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

let refreshLock = false;

async function refreshGroupPage(page, { silent = false } = {}) {
  if (!activeGroupKey) {
    currentRows = [];
    currentPage = 1;
    currentTotalRows = 0;
    currentTotalPages = 0;
    renderTableRows([]);
    return;
  }

  const url = `/api/redis/group?group_key=${encodeURIComponent(activeGroupKey)}&page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(PAGE_SIZE)}`;
  try {
    const result = await getJson(url);
    if (!result.success) {
      throw new Error(result.message || "读取 Redis 分组数据失败。");
    }
    currentRows = mapRows(result.items);
    currentPage = Number(result.page || 1);
    currentTotalRows = Number(result.key_count || 0);
    currentTotalPages = Number(result.page_count || 0);
    renderTableRows(currentRows);
  } catch (error) {
    if (!silent) {
      showToast(error?.message || "读取 Redis 分组数据失败，请稍后再试。");
    }
  }
}

async function refreshRedisOverview({ silent = false, resetPage = false } = {}) {
  if (refreshLock) return;
  refreshLock = true;

  try {
    const result = await getJson("/api/redis/overview");
    if (!result.success) {
      throw new Error(result.message || "读取 Redis 数据失败。");
    }

    const groups = Array.isArray(result.groups) ? result.groups : [];
    const shouldPreserveData =
      hasLoadedRedisData &&
      !result.is_available &&
      !groups.length &&
      Number(result.key_count || 0) <= 0;

    updateSummaryCards(result.summary_cards || []);

    if (!shouldPreserveData) {
      currentGroups = groups;
      const hasActiveGroup = currentGroups.some((group) => getGroupKey(group) === activeGroupKey);
      activeGroupKey = hasActiveGroup ? activeGroupKey : currentGroups[0] ? getGroupKey(currentGroups[0]) : "";
      renderGroupTabs();
      lastOverview = result;
      hasLoadedRedisData = hasLoadedRedisData || groups.length > 0 || Number(result.key_count || 0) > 0;
      await refreshGroupPage(resetPage ? 1 : currentPage || 1, { silent });
    } else if (lastOverview) {
      currentGroups = Array.isArray(lastOverview.groups) ? lastOverview.groups : [];
      renderGroupTabs();
      renderTableRows(currentRows);
    }

    updateRefreshNote(
      shouldPreserveData && lastOverview
        ? {
            ...result,
            group_count: lastOverview.group_count,
            key_count: lastOverview.key_count,
          }
        : result,
    );
  } catch (error) {
    renderUnavailableState(error?.message, { preserveData: hasLoadedRedisData });
    if (!silent) {
      showToast(error?.message || "读取 Redis 数据失败，请稍后再试。");
    }
  } finally {
    refreshLock = false;
  }
}

function bindRefreshAction() {
  const button = document.querySelector("[data-redis-refresh]");
  if (!button) return;

  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await refreshRedisOverview({ resetPage: true });
    } finally {
      button.disabled = false;
    }
  });
}

function bindGroupTabsAction() {
  const container = document.querySelector("[data-redis-group-tabs]");
  if (!container) return;

  container.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-redis-group-tab]");
    if (!button) return;

    const nextGroupKey = button.dataset.redisGroupTab || "";
    if (!nextGroupKey || nextGroupKey === activeGroupKey) return;

    activeGroupKey = nextGroupKey;
    currentPage = 1;
    currentRows = [];
    currentTotalRows = 0;
    currentTotalPages = 0;
    renderGroupTabs();
    renderTableRows([]);
    await refreshGroupPage(1);
  });
}

function bindPaginationActions() {
  renderPagination();
}

function bindPagination() {
  const host = document.querySelector("[data-redis-pagination]");
  if (!host) return;

  host.querySelectorAll("[data-page-number]").forEach((button) => {
    button.addEventListener("click", async () => {
      await refreshGroupPage(Number(button.dataset.pageNumber || 1));
    });
  });

  host.querySelectorAll("[data-page-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = String(button.dataset.pageAction || "");
      if (action === "prev" && currentPage > 1) {
        await refreshGroupPage(currentPage - 1);
        return;
      }
      if (action === "next" && currentPage < currentTotalPages) {
        await refreshGroupPage(currentPage + 1);
        return;
      }
      if (action === "more" && currentPage < currentTotalPages) {
        await refreshGroupPage(Math.min(currentPage + 5, currentTotalPages));
      }
    });
  });
}

function bindRedisStartAction() {
  const button = document.querySelector("[data-redis-start]");
  if (!button) return;

  button.addEventListener("click", async () => {
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "启动中...";

    try {
      const result = await postJson("/api/redis/start");
      if (!result.success) {
        throw new Error(result.message || "启动 Redis 失败。");
      }

      showToast(result.message || "Redis 启动命令已发送。");

      for (let attempt = 0; attempt < REDIS_RESTART_POLL_ATTEMPTS; attempt += 1) {
        await sleep(REDIS_RESTART_POLL_INTERVAL_MS);
        const overview = await getJson("/api/redis/overview");
        if (overview.success && overview.is_available) {
          await refreshRedisOverview({ resetPage: true });
          showToast("Redis 已恢复可用。");
          return;
        }
      }

      await refreshRedisOverview({ resetPage: true });
      throw new Error("Redis 启动命令已执行，但暂时还没有检测到服务可用。");
    } catch (error) {
      renderUnavailableState(error?.message, { preserveData: hasLoadedRedisData });
      showToast(error?.message || "启动 Redis 失败，请稍后再试。");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });
}

bindLogoutAction();
bindRefreshAction();
bindGroupTabsAction();
bindPaginationActions();
bindRedisStartAction();
refreshRedisOverview({ resetPage: true }).catch(() => {});
window.setInterval(() => {
  refreshRedisOverview({ silent: true }).catch(() => {});
}, POLL_INTERVAL_MS);
