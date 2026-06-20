import { refreshListPagination } from "../../core/prototype.js";
import { fetchAccountsList } from "./api.js";
import { escapeHtml } from "./formatters.js";
import { getLatestAccountsResult, setLatestAccountsResult } from "./state.js";

function formatFeeRate(value) {
  const raw = String(value ?? "").trim().replace(/%$/u, "");
  const numeric = Number.parseFloat(raw);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "0.05%";
  }
  const normalized = raw.includes(".")
    ? raw.replace(/0+$/u, "").replace(/\.$/u, "")
    : raw;
  return `${normalized || numeric.toString()}%`;
}

export function findBalanceRowById(accountId) {
  const rows = Array.isArray(getLatestAccountsResult().balance_rows) ? getLatestAccountsResult().balance_rows : [];
  return rows.find((item) => String(item.id || "") === String(accountId || ""));
}

export async function resolveBalanceAccountId(button) {
  const row = button.closest("tr");
  const nameElement = row?.querySelector(".spread-symbol strong");
  const exchangeElement = row?.querySelector(".spread-symbol__hint");
  const accountName = String(nameElement?.textContent || "").trim();
  const exchangeName = String(exchangeElement?.textContent || "").trim();

  if (!accountName) {
    return "";
  }

  const latestAccountsResult = getLatestAccountsResult();
  const result = latestAccountsResult?.account_rows?.length ? latestAccountsResult : await fetchAccountsList();
  if (!result.success && !Array.isArray(result.account_rows)) {
    throw new Error(result.message || "读取账户列表失败。");
  }

  const matched = (result.account_rows || []).find((item) => {
    const sameName = String(item.name || "").trim() === accountName;
    const sameExchange = !exchangeName || String(item.exchange || "").trim() === exchangeName;
    return sameName && sameExchange;
  });

  return String(matched?.id || "").trim();
}

export function updateSummaryCards(cards) {
  const list = Array.isArray(cards) ? cards : [];
  list.forEach((card) => {
    const key = String(card?.key || "").trim();
    if (!key) return;

    const container = document.querySelector(`[data-summary-card="${key}"]`);
    if (!container) return;

    const label = container.querySelector("[data-summary-label]");
    const value = container.querySelector("[data-summary-value]");
    const change = container.querySelector("[data-summary-change]");

    if (label) {
      label.textContent = String(card.label || "");
    }
    if (value) {
      value.textContent = String(card.value || "");
    }
    if (change) {
      change.textContent = String(card.change || "");
    }

    container.className = `stats-card stats-card--${String(card.tone || "neutral")}`;
  });
}

export function renderBalanceTableRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="14" class="spread-metric">暂无账户资金分布数据</td>
      </tr>
    `;
  }

  return rows
    .map((row) => {
      const transferActionHint = "提交后仅创建手动划转记录，实际执行由后台进程处理。";

      return `
        <tr data-balance-row="${escapeHtml(row.id || "")}">
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.name)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.exchange)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.market_type)}</td>
          <td class="spread-metric spread-metric--strong">${escapeHtml(row.available)}</td>
          <td class="spread-metric">${escapeHtml(row.current_balance || row.available)}</td>
          <td class="spread-metric">${escapeHtml(row.allocation_ratio || "0%")}</td>
          <td class="spread-metric">${escapeHtml(row.target)}</td>
          <td class="spread-metric">${escapeHtml(row.auto_trigger_value || "$0")}</td>
          <td class="spread-value ${String(row.deviation || "").includes("+") ? "is-positive" : "is-negative"}">${escapeHtml(row.deviation)}</td>
          <td>
            <span class="pill pill--${escapeHtml(row.address_status_tone)}">${escapeHtml(row.address_status)}</span>
          </td>
          <td>
            <span class="pill pill--${escapeHtml(row.connection_test_status_tone)}">${escapeHtml(row.connection_test_status)}</span>
          </td>
          <td class="spread-metric">${escapeHtml(formatFeeRate(row.maker_fee_rate))}</td>
          <td class="spread-metric">${escapeHtml(formatFeeRate(row.taker_fee_rate))}</td>
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-balance-config="${escapeHtml(row.id || "")}" data-balance-config-value="${escapeHtml(row.funding_ratio_percent || 0)}">配置</button>
              <button
                class="table-action"
                type="button"
                data-balance-action="${escapeHtml(row.id || "")}"
                data-balance-action-reason="${escapeHtml(transferActionHint)}"
                title="${escapeHtml(transferActionHint)}"
              >调拨</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

export function renderAccountTableRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="9" class="spread-metric">暂无已配置账户</td>
      </tr>
    `;
  }

  return rows
    .map(
      (account) => `
        <tr data-account-row="${escapeHtml(account.id || "")}">
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(account.name)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(account.exchange)}</span>
            </div>
          </td>
          <td>${escapeHtml(account.market_type)}</td>
          <td class="spread-metric">${escapeHtml(account.api_key)}</td>
          <td class="spread-metric">${escapeHtml(account.api_secret)}</td>
          <td>${escapeHtml(account.api_passphrase)}</td>
          <td>
            <span class="pill pill--${escapeHtml(account.address_status_tone)}">${escapeHtml(account.address_status)}</span>
          </td>
          <td>
            <span class="pill pill--${escapeHtml(account.connection_test_status_tone)}">${escapeHtml(account.connection_test_status)}</span>
          </td>
          <td class="spread-metric">${escapeHtml(account.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-account-test-row="${escapeHtml(account.id || "")}">连接测试</button>
              <button class="table-action" type="button" data-account-edit="${escapeHtml(account.id || "")}">编辑</button>
              <button class="table-action" type="button" data-account-delete="${escapeHtml(account.id || "")}">删除</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

export function renderAddressTableRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="6" class="spread-metric">暂无地址配置</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.account)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.exchange)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.network)}</td>
          <td class="spread-metric">${escapeHtml(row.address)}</td>
          <td>${escapeHtml(row.memo)}</td>
          <td class="spread-metric">${escapeHtml(row.created_at)}</td>
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
        </tr>
      `,
    )
    .join("");
}

export function applyAccountsPayload(result) {
  setLatestAccountsResult(result || {});

  const balanceBody = document.querySelector("[data-balance-table-body]");
  const accountBody = document.querySelector("[data-account-table-body]");
  const addressBody = document.querySelector("[data-address-table-body]");
  const accountCount = document.querySelector("[data-account-count]");
  const addressCount = document.querySelector("[data-address-count]");

  updateSummaryCards(result.summary_cards || []);

  if (balanceBody) {
    balanceBody.innerHTML = renderBalanceTableRows(result.balance_rows || []);
  }

  if (accountBody) {
    accountBody.innerHTML = renderAccountTableRows(result.account_rows || []);
  }

  if (addressBody) {
    addressBody.innerHTML = renderAddressTableRows(result.address_rows || []);
  }

  if (accountCount) {
    accountCount.textContent = `共 ${Number(result.account_count || 0)} 个账户`;
  }

  if (addressCount) {
    addressCount.textContent = `共 ${Number(result.address_count || 0)} 条地址配置`;
  }

  refreshListPagination(document);
}

export async function refreshAccountTables() {
  const result = await fetchAccountsList();
  if (!result.success) {
    throw new Error(result.message || "刷新账户列表失败。");
  }

  applyAccountsPayload(result);
  return result;
}
