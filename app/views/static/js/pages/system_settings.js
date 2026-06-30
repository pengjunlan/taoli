import { bindListPagination, bindPrototypeActions, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, postJson, showToast } from "../core/utils.js";

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

  if (!data.message && typeof data.detail === "string" && data.detail.trim()) {
    data.message = data.detail.trim();
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

function renderRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="11" class="spread-metric">暂无系统交易所配置</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.exchange_label)}</td>
          <td><span class="pill pill--${escapeHtml(row.status_tone)}">${escapeHtml(row.status_label)}</span></td>
          <td class="spread-metric">${escapeHtml(row.mode_label)}</td>
          <td><span class="pill pill--${escapeHtml(row.config_tone)}">${escapeHtml(row.config_status)}</span></td>
          <td>
            <button
              class="pill pill--${escapeHtml(row.market_feed_status_tone)} system-settings-table__status-button"
              type="button"
              data-system-symbols-open="${escapeHtml(row.exchange_code)}"
              title="${escapeHtml(row.market_feed_status_detail)}"
            >${escapeHtml(row.market_feed_status_label)}</button>
          </td>
          <td class="spread-metric">${escapeHtml(row.api_key)}</td>
          <td class="spread-metric">${escapeHtml(row.api_secret)}</td>
          <td class="spread-metric">${escapeHtml(row.api_passphrase)}</td>
          <td class="spread-metric">${escapeHtml(row.remark)}</td>
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-system-config-edit="${escapeHtml(row.exchange_code)}">配置</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderBlacklistTags(assets) {
  const list = Array.isArray(assets) ? assets : [];
  if (!list.length) {
    return `<div class="system-settings-blacklist-tags__empty">当前没有黑名单币种</div>`;
  }

  return list
    .map((asset) => `<span class="pill pill--neutral">${escapeHtml(asset)}</span>`)
    .join("");
}

let latestRows = [];
let systemConfigsRefreshLock = false;
let assetBlacklistDirty = false;
let assetBlacklistSaving = false;

function applyAssetBlacklist(detail) {
  const payload = detail || {};
  const assets = Array.isArray(payload.assets) ? payload.assets : [];
  const form = document.querySelector("[data-asset-blacklist-form]");
  const count = document.querySelector("[data-asset-blacklist-count]");
  const updated = document.querySelector("[data-asset-blacklist-updated]");
  const tags = document.querySelector("[data-asset-blacklist-tags]");

  if (form?.elements?.asset_blacklist && !assetBlacklistDirty && !assetBlacklistSaving) {
    form.elements.asset_blacklist.value = String(payload.asset_blacklist || "");
  }
  if (count) {
    count.textContent = `共 ${Number(payload.asset_count || assets.length || 0)} 个币种`;
  }
  if (updated) {
    updated.textContent = `最近更新：${String(payload.updated_at || "--")}`;
  }
  if (tags) {
    tags.innerHTML = renderBlacklistTags(assets);
  }
}

async function refreshSystemConfigs() {
  if (systemConfigsRefreshLock) {
    return;
  }
  systemConfigsRefreshLock = true;
  const result = await getJson("/api/system-exchanges/list");
  try {
    if (!result.success) {
      throw new Error(result.message || "读取系统交易所配置失败。");
    }

    latestRows = Array.isArray(result.config_rows) ? result.config_rows : [];
    updateSummaryCards(result.summary_cards || []);
    applyAssetBlacklist(result.asset_blacklist || {});

    const body = document.querySelector("[data-system-config-table-body]");
    const count = document.querySelector("[data-system-config-count]");
    if (body) {
      body.innerHTML = renderRows(latestRows);
    }
    if (count) {
      count.textContent = `共 ${Number(result.config_count || 0)} 个交易所`;
    }

    refreshListPagination(document);
  } finally {
    systemConfigsRefreshLock = false;
  }
}

function bindAssetBlacklistForm() {
  const form = document.querySelector("[data-asset-blacklist-form]");
  const submitButton = form?.querySelector('button[type="submit"]');
  if (!form || !submitButton) {
    return;
  }

  if (form.elements.asset_blacklist) {
    form.elements.asset_blacklist.addEventListener("input", () => {
      assetBlacklistDirty = true;
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    assetBlacklistSaving = true;

    try {
      const payload = {
        asset_blacklist: String(form.elements.asset_blacklist?.value || "").trim(),
      };
      const result = await postJson("/api/system-settings/asset-blacklist", payload);
      if (!result.success) {
        showToast(result.message || "保存币种黑名单失败。");
        return;
      }

      assetBlacklistDirty = false;
      applyAssetBlacklist(result.asset_blacklist || {});
      await refreshSystemConfigs();
      showToast(result.message || "币种黑名单已保存。");
    } catch (error) {
      showToast(error?.message || "保存币种黑名单失败，请稍后再试。");
    } finally {
      assetBlacklistSaving = false;
      submitButton.disabled = false;
    }
  });
}

function bindSystemConfigModal() {
  const modal = document.querySelector("[data-system-config-modal]");
  const form = document.querySelector("[data-system-config-form]");
  const closeButtons = document.querySelectorAll("[data-system-config-modal-close]");
  const publicApiCheckbox = document.querySelector("[data-system-public-api]");
  const privateFields = document.querySelectorAll("[data-system-private-field]");
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!modal || !form || !publicApiCheckbox || !submitButton) {
    return;
  }

  const syncPrivateFields = () => {
    const usePublicApi = Boolean(publicApiCheckbox.checked);
    privateFields.forEach((field) => {
      field.classList.toggle("is-hidden", usePublicApi);
      const input = field.querySelector("input");
      if (input) {
        input.disabled = usePublicApi;
      }
    });
  };

  const openModal = () => {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeModal = () => {
    modal.hidden = true;
    document.body.style.overflow = "";
    form.reset();
    syncPrivateFields();
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-system-config-edit]");
    if (!button) return;

    const exchangeCode = String(button.getAttribute("data-system-config-edit") || "").trim();
    button.disabled = true;
    try {
      const result = await getJson(`/api/system-exchanges/${exchangeCode}`);
      if (!result.success || !result.config) {
        showToast(result.message || "未找到该交易所配置。");
        return;
      }

      const row = result.config;
      form.elements.exchange_code.value = row.exchange_code || "";
      form.elements.exchange_label.value = row.exchange_label || "";
      form.elements.is_enabled.checked = Boolean(row.is_enabled);
      form.elements.use_public_api.checked = Boolean(row.use_public_api);
      form.elements.api_key.value = String(row.api_key || "");
      form.elements.api_secret.value = String(row.api_secret || "");
      form.elements.api_passphrase.value = String(row.api_passphrase || "");
      form.elements.remark.value = String(row.remark || "");

      syncPrivateFields();
      openModal();
    } catch (error) {
      showToast(error?.message || "读取系统交易所配置失败，请稍后再试。");
    } finally {
      button.disabled = false;
    }
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  publicApiCheckbox.addEventListener("change", syncPrivateFields);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;

    const formData = new FormData(form);
    const payload = {
      exchange_code: String(formData.get("exchange_code") || "").trim(),
      is_enabled: form.elements.is_enabled.checked,
      use_public_api: form.elements.use_public_api.checked,
      api_key: String(formData.get("api_key") || "").trim(),
      api_secret: String(formData.get("api_secret") || "").trim(),
      api_passphrase: String(formData.get("api_passphrase") || "").trim(),
      remark: String(formData.get("remark") || "").trim(),
    };

    try {
      const result = await postJson("/api/system-exchanges", payload);
      if (!result.success) {
        showToast(result.message || "保存系统交易所配置失败。");
        return;
      }

      await refreshSystemConfigs();
      showToast(result.message || "系统交易所配置已保存。");
      closeModal();
    } catch (error) {
      showToast(error?.message || "保存系统交易所配置失败，请稍后再试。");
    } finally {
      submitButton.disabled = false;
    }
  });

  syncPrivateFields();
}

function renderSwapSymbols(symbols) {
  const items = Array.isArray(symbols) ? symbols : [];
  if (!items.length) {
    return `<div class="system-symbols-modal__empty">当前没有可展示的永续交易对</div>`;
  }

  return items
    .map(
      (symbol) => `
        <div class="system-symbols-modal__item">${escapeHtml(symbol)}</div>
      `,
    )
    .join("");
}

function bindSystemSymbolsModal() {
  const modal = document.querySelector("[data-system-symbols-modal]");
  const summary = document.querySelector("[data-system-symbols-summary]");
  const list = document.querySelector("[data-system-symbols-list]");
  const closeButtons = document.querySelectorAll("[data-system-symbols-close]");
  const refreshButton = document.querySelector("[data-system-symbols-refresh]");
  let activeExchangeCode = "";

  if (!modal || !summary || !list) {
    return;
  }

  const openModal = () => {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeModal = () => {
    modal.hidden = true;
    document.body.style.overflow = "";
    activeExchangeCode = "";
    summary.textContent = "正在读取数据库中的永续交易对...";
    list.innerHTML = `<div class="system-symbols-modal__empty">加载中...</div>`;
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-system-symbols-open]");
    if (!button) return;

    const exchangeCode = String(button.getAttribute("data-system-symbols-open") || "").trim();
    activeExchangeCode = exchangeCode;
    button.disabled = true;
    openModal();
    try {
      const result = await getJson(`/api/system-exchanges/${exchangeCode}/swap-symbols`);
      if (!result.success) {
        summary.textContent = result.message || "读取永续交易对失败。";
        list.innerHTML = `<div class="system-symbols-modal__empty">暂无数据</div>`;
        return;
      }

      summary.textContent = `${String(result.exchange_label || exchangeCode)} 共 ${Number(result.symbol_count || 0)} 个永续交易对`;
      list.innerHTML = renderSwapSymbols(result.symbols || []);
    } catch (error) {
      summary.textContent = error?.message || "读取永续交易对失败。";
      list.innerHTML = `<div class="system-symbols-modal__empty">暂无数据</div>`;
    } finally {
      button.disabled = false;
    }
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });

  if (refreshButton) {
    refreshButton.addEventListener("click", async () => {
      if (!activeExchangeCode) {
        showToast("请先选择一个交易所");
        return;
      }

      refreshButton.disabled = true;
      const originalLabel = refreshButton.textContent;
      refreshButton.textContent = "更新中...";
      summary.textContent = "正在从交易所拉取最新永续交易对并更新数据库...";
      try {
        const result = await postJson(`/api/system-exchanges/${activeExchangeCode}/swap-symbols/refresh`, {});
        if (!result.success) {
          showToast(result.message || "更新永续交易对失败。");
          summary.textContent = result.message || "更新永续交易对失败。";
          return;
        }

        summary.textContent =
          `${String(result.exchange_label || activeExchangeCode)} 共 ${Number(result.symbol_count || 0)} 个永续交易对` +
          `，新增 ${Number(result.added_count || 0)}，恢复 ${Number(result.reactivated_count || 0)}，停用 ${Number(result.marked_inactive_count || 0)}`;
        list.innerHTML = renderSwapSymbols(result.symbols || []);
        await refreshSystemConfigs();
        showToast(result.message || "永续交易对更新成功。");
      } catch (error) {
        const message = error?.message || "更新永续交易对失败，请稍后再试。";
        summary.textContent = message;
        showToast(message);
      } finally {
        refreshButton.textContent = originalLabel;
        refreshButton.disabled = false;
      }
    });
  }
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindAssetBlacklistForm();
bindSystemConfigModal();
bindSystemSymbolsModal();
refreshSystemConfigs().catch((error) => {
  showToast(error?.message || "读取系统配置失败，请稍后再试。");
});
window.setInterval(() => {
  refreshSystemConfigs().catch(() => {});
}, 5000);
