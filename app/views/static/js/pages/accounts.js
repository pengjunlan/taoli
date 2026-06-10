import { bindListPagination, bindPrototypeActions, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, postJson, showToast } from "../core/utils.js";

let latestAccountsResult = {
  summary_cards: [],
  account_rows: [],
  address_rows: [],
  balance_rows: [],
  account_count: 0,
  address_count: 0,
};

let latestAutoTransferConfig = {
  is_enabled: false,
  trigger_ratio: 0.5,
};

function parseMoney(value) {
  const normalized = String(value || "")
    .trim()
    .toUpperCase()
    .replaceAll("$", "")
    .replaceAll(",", "");
  if (!normalized) return 0;
  if (normalized.endsWith("K")) return Number(normalized.slice(0, -1)) * 1000;
  if (normalized.endsWith("M")) return Number(normalized.slice(0, -1)) * 1000000;
  return Number(normalized);
}

function formatMoney(value) {
  const amount = Number(value || 0);
  if (amount >= 1000000) {
    return `$${(amount / 1000000).toFixed(2).replace(/\.?0+$/, "")}M`;
  }
  if (amount >= 1000) {
    return `$${(amount / 1000).toFixed(amount % 1000 === 0 ? 0 : 1).replace(/\.?0+$/, "")}K`;
  }
  return `$${amount.toFixed(2).replace(/\.?0+$/, "")}`;
}

function findBalanceRowById(accountId) {
  const rows = Array.isArray(latestAccountsResult.balance_rows) ? latestAccountsResult.balance_rows : [];
  return rows.find((item) => String(item.id || "") === String(accountId || ""));
}

function syncAutoTransferToggleUi() {
  const toggle = document.querySelector("[data-auto-transfer-toggle]");
  const label = document.querySelector("[data-auto-transfer-toggle-label]");
  if (!toggle || !label) return;

  const isEnabled = Boolean(latestAutoTransferConfig?.is_enabled);
  toggle.classList.toggle("is-enabled", isEnabled);
  toggle.setAttribute("aria-pressed", isEnabled ? "true" : "false");
  label.textContent = isEnabled ? "自动调拨已开启" : "自动调拨已关闭";
}

async function refreshAutoTransferConfig() {
  const result = await getJson("/api/accounts/auto-transfer-config");
  if (!result.success) {
    throw new Error(result.message || "读取自动调拨配置失败。");
  }

  latestAutoTransferConfig = {
    is_enabled: Boolean(result.config?.is_enabled),
    trigger_ratio: Number(result.config?.trigger_ratio || 0.5),
  };
  syncAutoTransferToggleUi();
  return latestAutoTransferConfig;
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

async function resolveBalanceAccountId(button) {
  const row = button.closest("tr");
  const nameElement = row?.querySelector(".spread-symbol strong");
  const exchangeElement = row?.querySelector(".spread-symbol__hint");
  const accountName = String(nameElement?.textContent || "").trim();
  const exchangeName = String(exchangeElement?.textContent || "").trim();

  if (!accountName) {
    return "";
  }

  const result = latestAccountsResult?.account_rows?.length
    ? latestAccountsResult
    : await getJson("/api/accounts/list");
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
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

function renderBalanceTableRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="11" class="spread-metric">暂无账户资金分布数据</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr data-balance-row="${escapeHtml(row.id || "")}">
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.name)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.exchange)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.market_type)}</td>
          <td class="spread-metric spread-metric--strong">${escapeHtml(row.available)}</td>
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
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-balance-config="${escapeHtml(row.id || "")}" data-balance-config-value="${escapeHtml(row.funding_ratio_percent || 0)}">配置</button>
              <button class="table-action" type="button" data-balance-action="${escapeHtml(row.id || "")}">调拨</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderAccountTableRows(rows) {
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
              <button class="table-action" type="button" data-account-test-row="${escapeHtml(account.id || "")}">链接测试</button>
              <button class="table-action" type="button" data-account-edit="${escapeHtml(account.id || "")}">编辑</button>
              <button class="table-action" type="button" data-account-delete="${escapeHtml(account.id || "")}">删除</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderAddressTableRows(rows) {
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

async function refreshAccountTables() {
  const result = await getJson("/api/accounts/list");
  if (!result.success) {
    throw new Error(result.message || "刷新账户列表失败。");
  }

  latestAccountsResult = result;

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

function bindAccountTabs() {
  const triggers = Array.from(document.querySelectorAll("[data-account-tab-trigger]"));
  const panels = Array.from(document.querySelectorAll("[data-account-tab-panel]"));

  if (!triggers.length || !panels.length) return;

  const activateTab = (tabKey) => {
    triggers.forEach((trigger) => {
      const isActive = trigger.getAttribute("data-account-tab-trigger") === tabKey;
      trigger.classList.toggle("is-active", isActive);
      trigger.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    panels.forEach((panel) => {
      const isActive = panel.getAttribute("data-account-tab-panel") === tabKey;
      panel.classList.toggle("is-active", isActive);
      panel.hidden = !isActive;
    });

    refreshListPagination(document);
  };

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      activateTab(trigger.getAttribute("data-account-tab-trigger"));
    });
  });
}

function bindAccountModal() {
  const modal = document.querySelector("[data-account-modal]");
  const balanceConfigModal = document.querySelector("[data-balance-config-modal]");
  const balanceConfigForm = document.querySelector("[data-balance-config-form]");
  const balanceConfigSave = document.querySelector("[data-balance-config-save]");
  const balanceConfigCloseButtons = document.querySelectorAll("[data-balance-config-close]");
  const autoTransferModal = document.querySelector("[data-auto-transfer-modal]");
  const autoTransferForm = document.querySelector("[data-auto-transfer-form]");
  const autoTransferOpenButton = document.querySelector("[data-auto-transfer-open]");
  const autoTransferToggleButton = document.querySelector("[data-auto-transfer-toggle]");
  const autoTransferSaveButton = document.querySelector("[data-auto-transfer-save]");
  const autoTransferCloseButtons = document.querySelectorAll("[data-auto-transfer-close]");
  const transferModal = document.querySelector("[data-transfer-modal]");
  const transferForm = document.querySelector("[data-transfer-form]");
  const transferSave = document.querySelector("[data-transfer-save]");
  const transferCloseButtons = document.querySelectorAll("[data-transfer-close]");
  const transferPreview = document.querySelector("[data-transfer-preview]");
  const transferDefaultHint = document.querySelector("[data-transfer-default-hint]");
  const confirmModal = document.querySelector("[data-account-confirm]");
  const confirmMessage = document.querySelector("[data-account-confirm-message]");
  const confirmAccept = document.querySelector("[data-account-confirm-accept]");
  const confirmCancelButtons = document.querySelectorAll("[data-account-confirm-cancel]");
  const openButton = document.querySelector("[data-account-modal-open]");
  const closeButtons = document.querySelectorAll("[data-account-modal-close]");
  const form = document.querySelector("[data-account-form]");
  const testButton = document.querySelector("[data-account-test]");
  const title = document.getElementById("account-modal-title");
  const hiddenAccountId = form?.querySelector('input[name="account_id"]');
  const hiddenConnectionStatus = form?.querySelector('input[name="connection_test_status"]');
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!modal || !openButton || !form || !hiddenAccountId || !hiddenConnectionStatus || !title || !submitButton) return;

  const connectionFieldNames = ["market_type", "exchange_code", "api_key", "api_secret", "api_passphrase"];
  let originalConnectionSnapshot = null;
  let currentTransferContext = null;

  const syncBodyScrollLock = () => {
    const hasVisibleLayer = [modal, confirmModal, balanceConfigModal, autoTransferModal, transferModal].some((element) => element && !element.hidden);
    document.body.style.overflow = hasVisibleLayer ? "hidden" : "";
  };

  const readConnectionSnapshot = () =>
    Object.fromEntries(
      connectionFieldNames.map((name) => [name, String(form.elements[name]?.value || "").trim()]),
    );

  const hasConnectionConfigChanged = () => {
    if (!originalConnectionSnapshot) return false;
    const currentSnapshot = readConnectionSnapshot();
    return connectionFieldNames.some((name) => currentSnapshot[name] !== originalConnectionSnapshot[name]);
  };

  const syncConnectionStatusByConfig = () => {
    if (form.dataset.mode !== "edit") {
      return;
    }

    if (hasConnectionConfigChanged()) {
      hiddenConnectionStatus.value = "untested";
    }
  };

  const openModal = () => {
    modal.hidden = false;
    syncBodyScrollLock();

    const firstInput = form.querySelector("input, select, textarea");
    if (firstInput) {
      window.setTimeout(() => firstInput.focus(), 20);
    }
  };

  const resetFormMode = () => {
    form.dataset.mode = "create";
    hiddenAccountId.value = "";
    hiddenConnectionStatus.value = "untested";
    originalConnectionSnapshot = null;
    form.reset();
    hiddenConnectionStatus.value = "untested";
    title.textContent = "新增账户";
    submitButton.textContent = "保存账户";
    form.querySelectorAll("[data-password-toggle]").forEach((button) => {
      const wrapper = button.closest(".password-field");
      const input = wrapper?.querySelector(".password-field__control");
      if (!input) return;
      input.type = "password";
      button.setAttribute("aria-pressed", "false");
    });
  };

  const closeModal = () => {
    modal.hidden = true;
    syncBodyScrollLock();
    resetFormMode();
  };

  const closeBalanceConfigModal = () => {
    if (!balanceConfigModal || !balanceConfigForm) return;
    balanceConfigModal.hidden = true;
    balanceConfigForm.reset();
    balanceConfigForm.elements.account_id.value = "";
    balanceConfigForm.elements.funding_ratio_percent.value = "0";
    syncBodyScrollLock();
  };

  const closeAutoTransferModal = () => {
    if (!autoTransferModal || !autoTransferForm) return;
    autoTransferModal.hidden = true;
    syncBodyScrollLock();
  };

  const fillTransferTargetOptions = (fromAccountId) => {
    if (!transferForm) return;
    const select = transferForm.elements.to_account_id;
    if (!select) return;

    const accounts = Array.isArray(latestAccountsResult.account_rows) ? latestAccountsResult.account_rows : [];
    const options = accounts
      .filter((item) => String(item.id || "") !== String(fromAccountId))
      .map(
        (item) =>
          `<option value="${escapeHtml(item.id || "")}">${escapeHtml(item.name || "")} / ${escapeHtml(item.exchange || "")}</option>`,
      );

    select.innerHTML = `<option value="">请选择转入账户</option>${options.join("")}`;
  };

  const renderTransferPreview = () => {
    if (!transferForm || !transferPreview) return;

    const fromAccountId = String(transferForm.elements.from_account_id.value || "").trim();
    const toAccountId = String(transferForm.elements.to_account_id.value || "").trim();
    const amount = Number(transferForm.elements.amount.value || 0);
    const fromRow = findBalanceRowById(fromAccountId);
    const toRow = findBalanceRowById(toAccountId);

    if (!fromRow || !toRow) {
      transferPreview.hidden = true;
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划拨金额：--";
      }
      return;
    }

    const fromAvailable = parseMoney(fromRow.available);
    const fromTarget = parseMoney(fromRow.target);
    const toAvailable = parseMoney(toRow.available);
    const toTarget = parseMoney(toRow.target);

    const transferValue = Number.isFinite(amount) && amount > 0 ? amount : 0;

    const fromBefore = transferPreview.querySelector("[data-transfer-from-before]");
    const fromTargetEl = transferPreview.querySelector("[data-transfer-from-target]");
    const fromAfter = transferPreview.querySelector("[data-transfer-from-after]");
    const toBefore = transferPreview.querySelector("[data-transfer-to-before]");
    const toTargetEl = transferPreview.querySelector("[data-transfer-to-target]");
    const toAfter = transferPreview.querySelector("[data-transfer-to-after]");

    if (fromBefore) fromBefore.textContent = formatMoney(fromAvailable);
    if (fromTargetEl) fromTargetEl.textContent = formatMoney(fromTarget);
    if (fromAfter) fromAfter.textContent = formatMoney(Math.max(0, fromAvailable - transferValue));
    if (toBefore) toBefore.textContent = formatMoney(toAvailable);
    if (toTargetEl) toTargetEl.textContent = formatMoney(toTarget);
    if (toAfter) toAfter.textContent = formatMoney(toAvailable + transferValue);

    transferPreview.hidden = false;
  };

  const syncDefaultTransferAmount = () => {
    if (!transferForm) return;

    const fromAccountId = String(transferForm.elements.from_account_id.value || "").trim();
    const toAccountId = String(transferForm.elements.to_account_id.value || "").trim();
    const fromRow = findBalanceRowById(fromAccountId);
    const toRow = findBalanceRowById(toAccountId);

    if (!fromRow || !toRow) {
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划拨金额：--";
      }
      renderTransferPreview();
      return;
    }

    const fromAvailable = parseMoney(fromRow.available);
    const fromTarget = parseMoney(fromRow.target);
    const toAvailable = parseMoney(toRow.available);
    const toTarget = parseMoney(toRow.target);
    const fromExcess = Math.max(0, fromAvailable - fromTarget);
    const toNeed = Math.max(0, toTarget - toAvailable);
    const defaultAmount = Math.min(fromExcess, toNeed);

    currentTransferContext = {
      fromExcess,
      toNeed,
      defaultAmount,
    };

    transferForm.elements.amount.value = defaultAmount > 0 ? String(Number(defaultAmount.toFixed(2))) : "";
    if (transferDefaultHint) {
      transferDefaultHint.textContent = `默认划拨金额：${formatMoney(defaultAmount)}（转出超出 ${formatMoney(fromExcess)}，转入待补 ${formatMoney(toNeed)}）`;
    }
    renderTransferPreview();
  };

  const closeTransferModal = () => {
    if (!transferModal || !transferForm) return;
    transferModal.hidden = true;
    transferForm.reset();
    transferForm.elements.from_account_id.value = "";
    transferForm.elements.from_account_name.value = "";
    transferForm.elements.to_account_id.innerHTML = `<option value="">请选择转入账户</option>`;
    currentTransferContext = null;
    if (transferPreview) {
      transferPreview.hidden = true;
    }
    if (transferDefaultHint) {
      transferDefaultHint.textContent = "默认划拨金额：--";
    }
    syncBodyScrollLock();
  };

  const closeDeleteConfirm = (result) => {
    if (!confirmModal || confirmModal.hidden) return;

    confirmModal.hidden = true;
    syncBodyScrollLock();

    const resolver = confirmModal.__resolver;
    delete confirmModal.__resolver;
    if (typeof resolver === "function") {
      resolver(result);
    }
  };

  const openDeleteConfirm = (message) => {
    if (!confirmModal || !confirmMessage || !confirmAccept) {
      return Promise.resolve(window.confirm(message));
    }

    confirmMessage.textContent = message;
    confirmModal.hidden = false;
    syncBodyScrollLock();

    return new Promise((resolve) => {
      confirmModal.__resolver = resolve;
      window.setTimeout(() => confirmAccept.focus(), 20);
    });
  };

  const fillForm = (account) => {
    form.dataset.mode = "edit";
    hiddenAccountId.value = String(account.account_id || "");
    hiddenConnectionStatus.value = String(account.connection_test_status || "untested");
    form.elements.market_type.value = account.market_type || "";
    form.elements.exchange_code.value = account.exchange_code || "";
    form.elements.api_key.value = account.api_key || "";
    form.elements.api_secret.value = account.api_secret || "";
    form.elements.api_passphrase.value = account.api_passphrase || "";
    form.elements.address_network.value = account.address_network || "";
    form.elements.address_value.value = account.address_value || "";
    form.elements.address_memo.value = account.address_memo || "";
    originalConnectionSnapshot = readConnectionSnapshot();
    title.textContent = "编辑账户";
    submitButton.textContent = "保存修改";
  };

  const buildConnectionPayload = () => {
    const formData = new FormData(form);
    return {
      account_id: Number(formData.get("account_id") || 0),
      market_type: String(formData.get("market_type") || "").trim(),
      exchange_code: String(formData.get("exchange_code") || "").trim(),
      api_key: String(formData.get("api_key") || "").trim(),
      api_secret: String(formData.get("api_secret") || "").trim(),
      api_passphrase: String(formData.get("api_passphrase") || "").trim(),
    };
  };

  connectionFieldNames.forEach((name) => {
    const field = form.elements[name];
    if (!field) return;

    field.addEventListener("input", syncConnectionStatusByConfig);
    field.addEventListener("change", syncConnectionStatusByConfig);
  });

  form.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const wrapper = button.closest(".password-field");
      const input = wrapper?.querySelector(".password-field__control");
      if (!input) return;

      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      button.setAttribute("aria-pressed", isVisible ? "false" : "true");
    });
  });

  openButton.addEventListener("click", () => {
    resetFormMode();
    openModal();
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  if (balanceConfigModal) {
    balanceConfigModal.addEventListener("click", (event) => {
      if (event.target === balanceConfigModal) {
        closeBalanceConfigModal();
      }
    });
  }

  if (autoTransferModal) {
    autoTransferModal.addEventListener("click", (event) => {
      if (event.target === autoTransferModal) {
        closeAutoTransferModal();
      }
    });
  }

  if (transferModal) {
    transferModal.addEventListener("click", (event) => {
      if (event.target === transferModal) {
        closeTransferModal();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && confirmModal && !confirmModal.hidden) {
      closeDeleteConfirm(false);
      return;
    }

    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }

    if (event.key === "Escape" && balanceConfigModal && !balanceConfigModal.hidden) {
      closeBalanceConfigModal();
    }

    if (event.key === "Escape" && autoTransferModal && !autoTransferModal.hidden) {
      closeAutoTransferModal();
    }

    if (event.key === "Escape" && transferModal && !transferModal.hidden) {
      closeTransferModal();
    }
  });

  confirmCancelButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeDeleteConfirm(false);
    });
  });

  if (confirmAccept) {
    confirmAccept.addEventListener("click", () => {
      closeDeleteConfirm(true);
    });
  }

  balanceConfigCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeBalanceConfigModal();
    });
  });

  autoTransferCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeAutoTransferModal();
    });
  });

  transferCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeTransferModal();
    });
  });

  if (transferForm) {
    transferForm.elements.to_account_id?.addEventListener("change", () => {
      syncDefaultTransferAmount();
    });

    transferForm.elements.amount?.addEventListener("input", () => {
      renderTransferPreview();
    });
  }

  document.addEventListener("click", async (event) => {
    const balanceConfigButton = event.target.closest("[data-balance-config]");
    if (!balanceConfigButton || !balanceConfigModal || !balanceConfigForm) return;

    const balanceRow = balanceConfigButton.closest("[data-balance-row]");
    let accountId = String(
      balanceConfigButton.getAttribute("data-balance-config") ||
      balanceRow?.getAttribute("data-balance-row") ||
      "",
    ).trim();
    const currentValue = String(balanceConfigButton.getAttribute("data-balance-config-value") || "0").trim() || "0";
    try {
      if (!accountId) {
        accountId = await resolveBalanceAccountId(balanceConfigButton);
      }

      if (!accountId) {
        showToast("账户 ID 缺失，无法配置资金占比。");
        return;
      }

      balanceConfigForm.elements.account_id.value = accountId;
      balanceConfigForm.elements.funding_ratio_percent.value = currentValue;
      balanceConfigModal.hidden = false;
      syncBodyScrollLock();
      window.setTimeout(() => balanceConfigForm.elements.funding_ratio_percent.focus(), 20);
    } catch (error) {
      showToast(error?.message || "读取账户失败，无法配置资金占比。");
    }
  });

  if (balanceConfigSave && balanceConfigForm) {
    balanceConfigSave.addEventListener("click", async () => {
      const accountId = String(balanceConfigForm.elements.account_id.value || "").trim();
      const fundingRatioPercent = Number(balanceConfigForm.elements.funding_ratio_percent.value || 0);
      if (!accountId) {
        showToast("账户 ID 缺失，无法保存。");
        return;
      }

      if (Number.isNaN(fundingRatioPercent) || fundingRatioPercent < 0 || fundingRatioPercent > 100) {
        showToast("资金占比必须在 0 到 100 之间。");
        return;
      }

      balanceConfigSave.disabled = true;
      try {
        const result = await postJson(`/api/accounts/${accountId}/funding-ratio`, {
          funding_ratio_percent: fundingRatioPercent,
        });
        if (!result.success) {
          showToast(result.message || "保存资金占比失败。");
          return;
        }

        await refreshAccountTables();
        showToast(result.message || "资金占比已保存。");
        closeBalanceConfigModal();
      } catch (error) {
        showToast(error?.message || "保存资金占比失败，请稍后再试。");
      } finally {
        balanceConfigSave.disabled = false;
      }
    });
  }

  if (autoTransferOpenButton && autoTransferModal && autoTransferForm) {
    autoTransferOpenButton.addEventListener("click", async () => {
      try {
        const config = await refreshAutoTransferConfig();
        autoTransferForm.elements.trigger_ratio_percent.value = String(Math.round(Number(config.trigger_ratio || 0.5) * 100));
        autoTransferModal.hidden = false;
        syncBodyScrollLock();
      } catch (error) {
        showToast(error?.message || "读取自动调拨配置失败，请稍后再试。");
      }
    });
  }

  if (autoTransferToggleButton) {
    autoTransferToggleButton.addEventListener("click", async () => {
      const nextEnabled = !Boolean(latestAutoTransferConfig?.is_enabled);
      autoTransferToggleButton.disabled = true;
      try {
        const result = await postJson("/api/accounts/auto-transfer-config", {
          is_enabled: nextEnabled,
          trigger_ratio: Number(latestAutoTransferConfig?.trigger_ratio || 0.5),
        });
        if (!result.success) {
          showToast(result.message || "更新自动调拨开关失败。");
          return;
        }

        latestAutoTransferConfig = {
          is_enabled: Boolean(result.config?.is_enabled),
          trigger_ratio: Number(result.config?.trigger_ratio || 0.5),
        };
        syncAutoTransferToggleUi();
        await refreshAccountTables();

        if (autoTransferForm) {
          autoTransferForm.elements.trigger_ratio_percent.value = String(
            Math.round(Number(latestAutoTransferConfig.trigger_ratio || 0.5) * 100),
          );
        }

        showToast(
          result.auto_transfer_executed
            ? "自动调拨配置已保存，并已按规则生成一条调拨记录。"
            : (result.message || "自动调拨配置已保存。"),
        );
      } catch (error) {
        showToast(error?.message || "更新自动调拨开关失败，请稍后再试。");
      } finally {
        autoTransferToggleButton.disabled = false;
      }
    });
  }

  if (autoTransferSaveButton && autoTransferForm) {
    autoTransferSaveButton.addEventListener("click", async () => {
      const triggerRatioPercent = Number(autoTransferForm.elements.trigger_ratio_percent.value || 50);
      if (Number.isNaN(triggerRatioPercent) || triggerRatioPercent <= 0 || triggerRatioPercent > 100) {
        showToast("触发比例必须在 1 到 100 之间。");
        return;
      }

      autoTransferSaveButton.disabled = true;
      try {
        const result = await postJson("/api/accounts/auto-transfer-config", {
          is_enabled: Boolean(latestAutoTransferConfig?.is_enabled),
          trigger_ratio: triggerRatioPercent / 100,
        });
        if (!result.success) {
          showToast(result.message || "保存自动调拨配置失败。");
          return;
        }

        latestAutoTransferConfig = {
          is_enabled: Boolean(result.config?.is_enabled),
          trigger_ratio: Number(result.config?.trigger_ratio || 0.5),
        };
        syncAutoTransferToggleUi();
        await refreshAccountTables();

        showToast(
          result.auto_transfer_executed
            ? "自动调拨配置已保存，并已按规则生成一条调拨记录。"
            : (result.message || "自动调拨配置已保存。"),
        );
        closeAutoTransferModal();
      } catch (error) {
        showToast(error?.message || "保存自动调拨配置失败，请稍后再试。");
      } finally {
        autoTransferSaveButton.disabled = false;
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const balanceActionButton = event.target.closest("[data-balance-action]");
    if (!balanceActionButton || !transferModal || !transferForm) return;

    const balanceRow = balanceActionButton.closest("[data-balance-row]");
    let accountId = String(balanceActionButton.getAttribute("data-balance-action") || "").trim();
    try {
      if (!accountId) {
        accountId = await resolveBalanceAccountId(balanceActionButton);
      }
      if (!accountId) {
        showToast("账户缺失，暂时无法调拨。");
        return;
      }

      const accountName = String(
        balanceRow?.querySelector(".spread-symbol strong")?.textContent || "",
      ).trim();
      const exchangeName = String(
        balanceRow?.querySelector(".spread-symbol__hint")?.textContent || "",
      ).trim();

      transferForm.elements.from_account_id.value = accountId;
      transferForm.elements.from_account_name.value = [accountName, exchangeName].filter(Boolean).join(" / ");
      fillTransferTargetOptions(accountId);
      if (transferPreview) {
        transferPreview.hidden = true;
      }
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划拨金额：--";
      }
      transferModal.hidden = false;
      syncBodyScrollLock();
      window.setTimeout(() => transferForm.elements.to_account_id.focus(), 20);
    } catch (error) {
      showToast(error?.message || "读取账户失败，无法打开调拨窗口。");
    }
  });

  if (transferSave && transferForm) {
    transferSave.addEventListener("click", async () => {
      const fromAccountId = Number(transferForm.elements.from_account_id.value || 0);
      const toAccountId = Number(transferForm.elements.to_account_id.value || 0);
      const amount = Number(transferForm.elements.amount.value || 0);

      if (!fromAccountId) {
        showToast("转出账户不能为空。");
        return;
      }
      if (!toAccountId) {
        showToast("请选择转入账户。");
        return;
      }
      if (fromAccountId === toAccountId) {
        showToast("转出账户和转入账户不能相同。");
        return;
      }
      if (Number.isNaN(amount) || amount <= 0) {
        showToast("请输入正确的划转金额。");
        return;
      }
      if (currentTransferContext && amount > currentTransferContext.defaultAmount && currentTransferContext.defaultAmount > 0) {
        showToast(`划转金额不能超过默认可划转金额 ${formatMoney(currentTransferContext.defaultAmount)}。`);
        return;
      }

      transferSave.disabled = true;
      try {
        const result = await postJson("/api/accounts/transfer", {
          from_account_id: fromAccountId,
          to_account_id: toAccountId,
          amount,
          reason: "手动调拨",
        });
        if (!result.success) {
          showToast(result.message || "保存调拨记录失败。");
          return;
        }

        showToast(result.message || "调拨记录已保存。");
        closeTransferModal();
      } catch (error) {
        showToast(error?.message || "保存调拨记录失败，请稍后再试。");
      } finally {
        transferSave.disabled = false;
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const testRowButton = event.target.closest("[data-account-test-row]");
    if (!testRowButton) return;

    const accountId = String(testRowButton.getAttribute("data-account-test-row") || "").trim();
    if (!accountId) {
      showToast("账户 ID 缺失，无法测试连接。");
      return;
    }

    testRowButton.disabled = true;
    const originalText = testRowButton.textContent;
    testRowButton.textContent = "测试中...";

    try {
      const detailResult = await getJson(`/api/accounts/${accountId}`);
      if (!detailResult.success || !detailResult.account) {
        showToast(detailResult.message || "读取账户失败。");
        return;
      }

      const account = detailResult.account;
      const payload = {
        account_id: Number(account.account_id || 0),
        market_type: String(account.market_type || "").trim(),
        exchange_code: String(account.exchange_code || "").trim(),
        api_key: String(account.api_key || "").trim(),
        api_secret: String(account.api_secret || "").trim(),
        api_passphrase: String(account.api_passphrase || "").trim(),
      };

      const result = await postJson("/api/accounts/test-connection", payload);
      await refreshAccountTables();

      if (!result.success) {
        showToast(result.message || "连接失败，请检查密钥配置。");
        return;
      }

      showToast(result.message || "连接成功。");
    } catch (error) {
      showToast(error?.message || "测试连接失败，请稍后再试。");
    } finally {
      testRowButton.disabled = false;
      testRowButton.textContent = originalText;
    }
  });

  document.addEventListener("click", async (event) => {
    const editButton = event.target.closest("[data-account-edit]");
    if (!editButton) return;

    const accountId = String(editButton.getAttribute("data-account-edit") || "").trim();
    if (!accountId) {
      showToast("账户 ID 缺失，无法编辑。");
      return;
    }

    editButton.disabled = true;
    try {
      const result = await getJson(`/api/accounts/${accountId}`);
      if (!result.success || !result.account) {
        showToast(result.message || "读取账户失败。");
        return;
      }

      fillForm(result.account);
      openModal();
    } catch (error) {
      showToast(error?.message || "读取账户失败，请稍后再试。");
    } finally {
      editButton.disabled = false;
    }
  });

  document.addEventListener("click", async (event) => {
    const deleteButton = event.target.closest("[data-account-delete]");
    if (!deleteButton) return;

    const accountId = String(deleteButton.getAttribute("data-account-delete") || "").trim();
    if (!accountId) {
      showToast("账户 ID 缺失，无法删除。");
      return;
    }

    const confirmed = await openDeleteConfirm("确定删除这个账户吗？删除后不可恢复。");
    if (!confirmed) {
      return;
    }

    deleteButton.disabled = true;
    try {
      const result = await postJson(`/api/accounts/${accountId}/delete`);
      if (!result.success) {
        showToast(result.message || "删除账户失败。");
        return;
      }

      await refreshAccountTables();
      showToast(result.message || "账户已删除。");
    } catch (error) {
      showToast(error?.message || "删除账户失败，请稍后再试。");
    } finally {
      deleteButton.disabled = false;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;

    const formData = new FormData(form);
    const payload = {
      market_type: String(formData.get("market_type") || "").trim(),
      exchange_code: String(formData.get("exchange_code") || "").trim(),
      api_key: String(formData.get("api_key") || "").trim(),
      api_secret: String(formData.get("api_secret") || "").trim(),
      api_passphrase: String(formData.get("api_passphrase") || "").trim(),
      connection_test_status: String(formData.get("connection_test_status") || "untested").trim() || "untested",
      address_network: String(formData.get("address_network") || "").trim(),
      address_value: String(formData.get("address_value") || "").trim(),
      address_memo: String(formData.get("address_memo") || "").trim(),
    };

    const isEditMode = form.dataset.mode === "edit";
    const accountId = String(formData.get("account_id") || "").trim();
    const url = isEditMode && accountId ? `/api/accounts/${accountId}` : "/api/accounts";

    try {
      const result = await postJson(url, payload);
      if (!result.success) {
        showToast(result.message || (isEditMode ? "更新账户失败。" : "保存账户失败。"));
        return;
      }

      await refreshAccountTables();
      showToast(result.message || (isEditMode ? "账户已更新。" : "账户已保存。"));
      closeModal();
    } catch (error) {
      showToast(error?.message || (isEditMode ? "更新账户失败，请稍后再试。" : "保存账户失败，请稍后再试。"));
    } finally {
      submitButton.disabled = false;
    }
  });

  if (testButton) {
    testButton.addEventListener("click", async () => {
      const payload = buildConnectionPayload();

      if (!payload.market_type) {
        showToast("请选择市场类型。");
        return;
      }

      if (!payload.exchange_code) {
        showToast("请选择交易所。");
        return;
      }

      if (!payload.api_key) {
        showToast("请输入 API Key。");
        return;
      }

      if (!payload.api_secret) {
        showToast("请输入 API Secret。");
        return;
      }

      if (payload.exchange_code === "okx" && !payload.api_passphrase) {
        showToast("OKX 需要填写 API Passphrase。");
        return;
      }

      testButton.disabled = true;
      const originalText = testButton.textContent;
      testButton.textContent = "测试中...";

      try {
        const result = await postJson("/api/accounts/test-connection", payload);
        if (!result.success) {
          hiddenConnectionStatus.value = "failed";
          if (payload.account_id) {
            await refreshAccountTables();
          }
          showToast(result.message || "连接失败，请检查密钥配置。");
          return;
        }

        hiddenConnectionStatus.value = "success";
        originalConnectionSnapshot = readConnectionSnapshot();
        if (payload.account_id) {
          await refreshAccountTables();
        }
        showToast(result.message || "连接成功，可保存账户。");
      } catch (error) {
        hiddenConnectionStatus.value = "failed";
        showToast(error?.message || "测试连接失败，请稍后再试。");
      } finally {
        testButton.disabled = false;
        testButton.textContent = originalText;
      }
    });
  }
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindAccountTabs();
bindAccountModal();
refreshAccountTables().catch(() => {});
refreshAutoTransferConfig().catch(() => {});
