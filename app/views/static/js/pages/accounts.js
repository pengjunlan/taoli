import { bindListPagination, bindPrototypeActions, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, postJson, showToast } from "../core/utils.js";

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderAccountTableRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="8" class="spread-metric">暂无已配置账户</td>
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
          <td class="spread-metric">${escapeHtml(account.updated_at)}</td>
          <td>
            <div class="account-actions">
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

  const accountBody = document.querySelector("[data-account-table-body]");
  const addressBody = document.querySelector("[data-address-table-body]");
  const accountCount = document.querySelector("[data-account-count]");
  const addressCount = document.querySelector("[data-address-count]");

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
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!modal || !openButton || !form || !hiddenAccountId || !title || !submitButton) return;

  const syncBodyScrollLock = () => {
    const hasVisibleLayer = [modal, confirmModal].some((element) => element && !element.hidden);
    document.body.style.overflow = hasVisibleLayer ? "hidden" : "";
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
    form.reset();
    title.textContent = "新增账户";
    submitButton.textContent = "保存账户";
  };

  const closeModal = () => {
    modal.hidden = true;
    syncBodyScrollLock();
    resetFormMode();
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
    form.elements.market_type.value = account.market_type || "";
    form.elements.exchange_code.value = account.exchange_code || "";
    form.elements.api_key.value = account.api_key || "";
    form.elements.api_secret.value = account.api_secret || "";
    form.elements.api_passphrase.value = account.api_passphrase || "";
    form.elements.address_network.value = account.address_network || "";
    form.elements.address_value.value = account.address_value || "";
    form.elements.address_memo.value = account.address_memo || "";
    title.textContent = "编辑账户";
    submitButton.textContent = "保存修改";
  };

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

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && confirmModal && !confirmModal.hidden) {
      closeDeleteConfirm(false);
      return;
    }

    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
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
    testButton.addEventListener("click", () => {
      showToast("测试连接接口下一步接入，当前先保留操作入口。");
    });
  }
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindAccountTabs();
bindAccountModal();
