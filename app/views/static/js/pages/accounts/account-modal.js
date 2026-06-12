import { showToast } from "../../core/utils.js";
import {
  createAccount,
  deleteAccount,
  fetchAccountDetail,
  testAccountConnection,
  updateAccount,
} from "./api.js";

export function bindAccountModal({ elements, syncBodyScrollLock, refreshAccountTables }) {
  const {
    accountModal,
    confirmModal,
    confirmMessage,
    confirmAcceptButton,
    confirmCancelButtons,
    accountModalOpenButton,
    accountModalCloseButtons,
    accountForm,
    accountTestButton,
    accountModalTitle,
  } = elements;

  const hiddenAccountId = accountForm?.querySelector('input[name="account_id"]');
  const hiddenConnectionStatus = accountForm?.querySelector('input[name="connection_test_status"]');
  const submitButton = accountForm?.querySelector('button[type="submit"]');

  if (
    !accountModal ||
    !accountModalOpenButton ||
    !accountForm ||
    !hiddenAccountId ||
    !hiddenConnectionStatus ||
    !accountModalTitle ||
    !submitButton
  ) {
    return {
      handleEscape() {
        return false;
      },
    };
  }

  const connectionFieldNames = ["market_type", "exchange_code", "api_key", "api_secret", "api_passphrase"];
  let originalConnectionSnapshot = null;

  const readConnectionSnapshot = () =>
    Object.fromEntries(
      connectionFieldNames.map((name) => [name, String(accountForm.elements[name]?.value || "").trim()]),
    );

  const hasConnectionConfigChanged = () => {
    if (!originalConnectionSnapshot) return false;
    const currentSnapshot = readConnectionSnapshot();
    return connectionFieldNames.some((name) => currentSnapshot[name] !== originalConnectionSnapshot[name]);
  };

  const syncConnectionStatusByConfig = () => {
    if (accountForm.dataset.mode !== "edit") {
      return;
    }

    if (hasConnectionConfigChanged()) {
      hiddenConnectionStatus.value = "untested";
    }
  };

  const openModal = () => {
    accountModal.hidden = false;
    syncBodyScrollLock();

    const firstInput = accountForm.querySelector("input, select, textarea");
    if (firstInput) {
      window.setTimeout(() => firstInput.focus(), 20);
    }
  };

  const resetFormMode = () => {
    accountForm.dataset.mode = "create";
    hiddenAccountId.value = "";
    hiddenConnectionStatus.value = "untested";
    originalConnectionSnapshot = null;
    accountForm.reset();
    hiddenConnectionStatus.value = "untested";
    accountModalTitle.textContent = "新增账户";
    submitButton.textContent = "保存账户";
    accountForm.querySelectorAll("[data-password-toggle]").forEach((button) => {
      const wrapper = button.closest(".password-field");
      const input = wrapper?.querySelector(".password-field__control");
      if (!input) return;
      input.type = "password";
      button.setAttribute("aria-pressed", "false");
    });
  };

  const closeModal = () => {
    accountModal.hidden = true;
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
    if (!confirmModal || !confirmMessage || !confirmAcceptButton) {
      return Promise.resolve(window.confirm(message));
    }

    confirmMessage.textContent = message;
    confirmModal.hidden = false;
    syncBodyScrollLock();

    return new Promise((resolve) => {
      confirmModal.__resolver = resolve;
      window.setTimeout(() => confirmAcceptButton.focus(), 20);
    });
  };

  const fillForm = (account) => {
    accountForm.dataset.mode = "edit";
    hiddenAccountId.value = String(account.account_id || "");
    hiddenConnectionStatus.value = String(account.connection_test_status || "untested");
    accountForm.elements.market_type.value = account.market_type || "";
    accountForm.elements.exchange_code.value = account.exchange_code || "";
    accountForm.elements.api_key.value = account.api_key || "";
    accountForm.elements.api_secret.value = account.api_secret || "";
    accountForm.elements.api_passphrase.value = account.api_passphrase || "";
    accountForm.elements.address_network.value = account.address_network || "";
    accountForm.elements.address_value.value = account.address_value || "";
    accountForm.elements.address_memo.value = account.address_memo || "";
    originalConnectionSnapshot = readConnectionSnapshot();
    accountModalTitle.textContent = "编辑账户";
    submitButton.textContent = "保存修改";
  };

  const buildConnectionPayload = () => {
    const formData = new FormData(accountForm);
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
    const field = accountForm.elements[name];
    if (!field) return;

    field.addEventListener("input", syncConnectionStatusByConfig);
    field.addEventListener("change", syncConnectionStatusByConfig);
  });

  accountForm.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const wrapper = button.closest(".password-field");
      const input = wrapper?.querySelector(".password-field__control");
      if (!input) return;

      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      button.setAttribute("aria-pressed", isVisible ? "false" : "true");
    });
  });

  accountModalOpenButton.addEventListener("click", () => {
    resetFormMode();
    openModal();
  });

  accountModalCloseButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  accountModal.addEventListener("click", (event) => {
    if (event.target === accountModal) {
      closeModal();
    }
  });

  confirmCancelButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeDeleteConfirm(false);
    });
  });

  if (confirmAcceptButton) {
    confirmAcceptButton.addEventListener("click", () => {
      closeDeleteConfirm(true);
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
      const detailResult = await fetchAccountDetail(accountId);
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

      const result = await testAccountConnection(payload);
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
      const result = await fetchAccountDetail(accountId);
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
      const result = await deleteAccount(accountId);
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

  accountForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;

    const formData = new FormData(accountForm);
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

    const isEditMode = accountForm.dataset.mode === "edit";
    const accountId = String(formData.get("account_id") || "").trim();

    try {
      const result = isEditMode && accountId
        ? await updateAccount(accountId, payload)
        : await createAccount(payload);
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

  if (accountTestButton) {
    accountTestButton.addEventListener("click", async () => {
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

      accountTestButton.disabled = true;
      const originalText = accountTestButton.textContent;
      accountTestButton.textContent = "测试中...";

      try {
        const result = await testAccountConnection(payload);
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
        accountTestButton.disabled = false;
        accountTestButton.textContent = originalText;
      }
    });
  }

  return {
    handleEscape() {
      if (confirmModal && !confirmModal.hidden) {
        closeDeleteConfirm(false);
        return true;
      }

      if (!accountModal.hidden) {
        closeModal();
        return true;
      }

      return false;
    },
  };
}
