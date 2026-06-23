import { showToast } from "../../core/utils.js";
import {
  createAccount,
  deleteAccount,
  fetchAccountDetail,
  fetchExchangeNetworkOptions,
  testAccountConnection,
  updateAccount,
} from "./api.js";
import { getFormField } from "./form-fields.js";

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
    accountNetworkHint,
    accountModalTitle,
  } = elements;

  const hiddenAccountId = accountForm?.querySelector('input[name="account_id"]');
  const hiddenConnectionStatus = accountForm?.querySelector('input[name="connection_test_status"]');
  const submitButton = accountForm?.querySelector('button[type="submit"]');
  const getAccountField = (name) => getFormField(accountForm, name);

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
  let currentNetworkLoadToken = 0;

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
    if (accountNetworkHint) {
      accountNetworkHint.textContent = "选择交易所后，这里会按该交易所的 USDT 可用网络联动加载。";
    }
    accountForm.querySelectorAll("[data-password-toggle]").forEach((button) => {
      const wrapper = button.closest(".password-field");
      const input = wrapper?.querySelector(".password-field__control");
      if (!input) return;
      input.type = "password";
      button.setAttribute("aria-pressed", "false");
    });
  };

  const renderNetworkOptions = ({ options, selectedValue = "", exchangeCode = "", isLoading = false }) => {
    const addressNetworkField = getAccountField("address_network");
    if (!addressNetworkField) return;

    const selected = String(selectedValue || "").trim().toLowerCase();
    const rows = Array.isArray(options) ? options : [];
    if (isLoading) {
      addressNetworkField.innerHTML = '<option value="">网络加载中...</option>';
      addressNetworkField.disabled = true;
      return;
    }

    const html = ['<option value="">暂不配置</option>'];
    rows.forEach((item) => {
      const networkCode = String(item.network_code || "").trim();
      if (!networkCode) return;
      const networkName = String(item.network_name || networkCode).trim();
      const tags = [];
      if (item.is_deposit_enabled === false) {
        tags.push("不可充");
      }
      if (item.is_withdraw_enabled === false) {
        tags.push("不可提");
      }
      const labelSuffix = tags.length ? ` (${tags.join(" / ")})` : "";
      const isSelected = networkCode.toLowerCase() === selected ? " selected" : "";
      html.push(`<option value="${networkCode}"${isSelected}>${networkName}${labelSuffix}</option>`);
    });
    addressNetworkField.innerHTML = html.join("");
    addressNetworkField.disabled = !String(exchangeCode || "").trim();
    if (selected && !rows.some((item) => String(item.network_code || "").trim().toLowerCase() === selected)) {
      addressNetworkField.value = "";
    }
  };

  const updateNetworkHint = (message) => {
    if (!accountNetworkHint) return;
    accountNetworkHint.textContent = String(message || "").trim() || "选择交易所后，这里会按该交易所的 USDT 可用网络联动加载。";
  };

  const loadNetworkOptions = async ({
    exchangeCode,
    selectedValue = "",
    silent = false,
  }) => {
    const normalizedExchangeCode = String(exchangeCode || "").trim().toLowerCase();
    if (!normalizedExchangeCode) {
      renderNetworkOptions({ options: [], exchangeCode: "", selectedValue: "" });
      updateNetworkHint("请先选择交易所，再选择接收网络。");
      return;
    }

    const token = ++currentNetworkLoadToken;
    renderNetworkOptions({
      options: [],
      exchangeCode: normalizedExchangeCode,
      selectedValue,
      isLoading: true,
    });
    updateNetworkHint("正在加载当前交易所的 USDT 网络...");

    try {
      const result = await fetchExchangeNetworkOptions(normalizedExchangeCode);

      if (token !== currentNetworkLoadToken) {
        return;
      }

      if (!result.success) {
        renderNetworkOptions({ options: [], exchangeCode: normalizedExchangeCode, selectedValue });
        updateNetworkHint(result.message || "读取网络失败，请稍后重试。");
        if (!silent) {
          showToast(result.message || "读取网络失败，请稍后重试。");
        }
        return;
      }

      renderNetworkOptions({
        options: result.options || [],
        exchangeCode: normalizedExchangeCode,
        selectedValue,
      });
      const exchangeLabel = String(result.exchange_label || normalizedExchangeCode.toUpperCase()).trim();
      const updatedAt = String(result.updated_at || "").trim();
      updateNetworkHint(updatedAt ? `${exchangeLabel} 网络已加载，最近更新时间：${updatedAt}` : `${exchangeLabel} 网络已加载。`);
    } catch (error) {
      if (token !== currentNetworkLoadToken) {
        return;
      }
      renderNetworkOptions({ options: [], exchangeCode: normalizedExchangeCode, selectedValue });
      updateNetworkHint("读取网络失败，请稍后重试。");
      if (!silent) {
        showToast(error?.message || "读取网络失败，请稍后重试。");
      }
    }
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

  const fillForm = (account, networkOptions = null) => {
    const marketTypeField = getAccountField("market_type");
    const exchangeCodeField = getAccountField("exchange_code");
    const apiKeyField = getAccountField("api_key");
    const apiSecretField = getAccountField("api_secret");
    const apiPassphraseField = getAccountField("api_passphrase");
    const addressNetworkField = getAccountField("address_network");
    const addressValueField = getAccountField("address_value");
    const addressMemoField = getAccountField("address_memo");

    if (
      !marketTypeField ||
      !exchangeCodeField ||
      !apiKeyField ||
      !apiSecretField ||
      !apiPassphraseField ||
      !addressNetworkField ||
      !addressValueField ||
      !addressMemoField
    ) {
      throw new Error("账户表单加载不完整，请刷新页面后重试。");
    }

    accountForm.dataset.mode = "edit";
    hiddenAccountId.value = String(account.account_id || "");
    hiddenConnectionStatus.value = String(account.connection_test_status || "untested");
    marketTypeField.value = account.market_type || "";
    exchangeCodeField.value = account.exchange_code || "";
    apiKeyField.value = account.api_key || "";
    apiSecretField.value = account.api_secret || "";
    apiPassphraseField.value = account.api_passphrase || "";
    addressValueField.value = account.address_value || "";
    addressMemoField.value = account.address_memo || "";
    originalConnectionSnapshot = readConnectionSnapshot();
    accountModalTitle.textContent = "编辑账户";
    submitButton.textContent = "保存修改";
    renderNetworkOptions({
      options: networkOptions?.options || [],
      exchangeCode: account.exchange_code || "",
      selectedValue: account.address_network || "",
    });
    updateNetworkHint("当前已按账户交易所加载可选网络。");
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
    const field = getAccountField(name);
    if (!field) return;

    field.addEventListener("input", syncConnectionStatusByConfig);
    field.addEventListener("change", syncConnectionStatusByConfig);
  });

  const exchangeCodeField = getAccountField("exchange_code");
  if (exchangeCodeField) {
    exchangeCodeField.addEventListener("change", () => {
      void loadNetworkOptions({
        exchangeCode: exchangeCodeField.value,
        selectedValue: String(getAccountField("address_network")?.value || "").trim(),
        silent: true,
      });
    });
  }

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
    renderNetworkOptions({ options: [], exchangeCode: "", selectedValue: "" });
    updateNetworkHint("请先选择交易所，再选择接收网络。");
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

      fillForm(result.account, result.network_options || null);
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
