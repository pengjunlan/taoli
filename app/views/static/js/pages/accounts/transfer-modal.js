import { showToast } from "../../core/utils.js";
import { createTransferRecord, fetchTransferOptions } from "./api.js";
import { escapeHtml, formatMoney, parseMoney } from "./formatters.js";
import { getFormField } from "./form-fields.js";
import { findBalanceRowById, resolveBalanceAccountId } from "./render.js";
import { getLatestAccountsResult } from "./state.js";

const DEFAULT_TRANSFER_NOTICE = "手动调拨可直接提交，后台会按记录尝试执行，成功或失败以执行结果为准。";

export function bindTransferModal({ elements, syncBodyScrollLock }) {
  const {
    transferModal,
    transferForm,
    transferSaveButton,
    transferCloseButtons,
    transferPreview,
    transferDefaultHint,
    transferNotice,
    transferOptionSummary,
  } = elements;
  let latestTransferOptions = null;

  const getBalanceRows = () => {
    const rows = getLatestAccountsResult()?.balance_rows;
    return Array.isArray(rows) ? rows : [];
  };

  const getAccountLabel = (row) =>
    [String(row?.name || "").trim(), String(row?.exchange || "").trim()].filter(Boolean).join(" / ");

  const getAccountLabelById = (accountId) => {
    const row = getBalanceRows().find((item) => String(item.id || "") === String(accountId || ""));
    return row ? getAccountLabel(row) : "";
  };

  const setTransferOptionSummary = (text) => {
    if (transferOptionSummary) {
      transferOptionSummary.textContent = text;
    }
  };

  const setTransferNotice = (text) => {
    if (transferNotice) {
      transferNotice.textContent = text;
    }
  };

  const getSupportedTargetOptions = () => {
    const options = latestTransferOptions?.options;
    if (!Array.isArray(options)) {
      return [];
    }
    return options.filter((item) => Boolean(item?.route_supported) && String(item?.id || "").trim());
  };

  const getTransferField = (name) => getFormField(transferForm, name);

  const fillSourceAccountOptions = ({ selectedAccountId = "" } = {}) => {
    if (!transferForm) return;

    const select = getTransferField("from_account_id");
    if (!select) return;

    const optionHtml = getBalanceRows()
      .filter((row) => String(row.id || "").trim())
      .map((row) => {
        const id = String(row.id || "").trim();
        return `<option value="${escapeHtml(id)}">${escapeHtml(getAccountLabel(row) || "--")}</option>`;
      });

    select.innerHTML = `<option value="">请选择转出账户</option>${optionHtml.join("")}`;
    select.value = String(selectedAccountId || "");
  };

  const fillTargetAccountOptions = ({ selectedAccountId = "" } = {}) => {
    if (!transferForm) return;

    const select = getTransferField("to_account_id");
    const fromSelect = getTransferField("from_account_id");
    const fromAccountId = String(fromSelect?.value || "").trim();
    if (!select) return;

    const supportedTargetIds = new Set(getSupportedTargetOptions().map((item) => String(item.id || "").trim()));
    const optionHtml = getBalanceRows()
      .filter((row) => {
        const id = String(row.id || "").trim();
        return id && id !== fromAccountId && supportedTargetIds.has(id);
      })
      .map((row) => {
        const id = String(row.id || "").trim();
        return `<option value="${escapeHtml(id)}">${escapeHtml(getAccountLabel(row) || "--")}</option>`;
      });

    select.innerHTML = `<option value="">请选择转入账户</option>${optionHtml.join("")}`;
    select.disabled = !fromAccountId || optionHtml.length === 0;
    select.value = String(selectedAccountId || "");
  };

  const renderTransferPreview = () => {
    if (!transferForm || !transferPreview) return;

    const fromSelect = getTransferField("from_account_id");
    const toSelect = getTransferField("to_account_id");
    const amountField = getTransferField("amount");
    const fromAccountId = String(fromSelect?.value || "").trim();
    const toAccountId = String(toSelect?.value || "").trim();
    const amount = Number(amountField?.value || 0);
    const fromRow = findBalanceRowById(fromAccountId);
    const toRow = findBalanceRowById(toAccountId);

    if (!fromRow || !toRow) {
      transferPreview.hidden = true;
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

    const fromSelect = getTransferField("from_account_id");
    const toSelect = getTransferField("to_account_id");
    const amountField = getTransferField("amount");
    if (!fromSelect || !toSelect || !amountField) {
      throw new Error("手动调拨表单加载不完整，请刷新页面后重试。");
    }

    const fromAccountId = String(fromSelect.value || "").trim();
    const toAccountId = String(toSelect.value || "").trim();
    const fromRow = findBalanceRowById(fromAccountId);
    const toRow = findBalanceRowById(toAccountId);

    if (!fromRow || !toRow) {
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划转金额：-";
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

    amountField.value = defaultAmount > 0 ? String(Number(defaultAmount.toFixed(2))) : "";

    if (transferDefaultHint) {
      transferDefaultHint.textContent = `默认划转金额：${formatMoney(defaultAmount)}（转出超出 ${formatMoney(fromExcess)}，转入待补 ${formatMoney(toNeed)}）`;
    }

    renderTransferPreview();
  };

  const syncTransferTargets = async ({ selectedTargetId = "" } = {}) => {
    if (!transferForm) return;

    const fromSelect = getTransferField("from_account_id");
    if (!fromSelect) {
      throw new Error("手动调拨表单加载不完整，请刷新页面后重试。");
    }

    const fromAccountId = String(fromSelect.value || "").trim();
    latestTransferOptions = null;

    if (!fromAccountId) {
      fillTargetAccountOptions({ selectedAccountId: selectedTargetId });
      setTransferOptionSummary("请选择转出账户。");
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划转金额：-";
      }
      if (transferPreview) {
        transferPreview.hidden = true;
      }
      setTransferNotice(DEFAULT_TRANSFER_NOTICE);
      return;
    }

    const optionResult = await fetchTransferOptions(fromAccountId);
    if (!optionResult.success) {
      throw new Error(optionResult.message || "读取可执行调拨目标失败。");
    }
    latestTransferOptions = optionResult;
    fillTargetAccountOptions({ selectedAccountId: selectedTargetId });

    const targetSelect = getTransferField("to_account_id");
    if (!targetSelect) {
      throw new Error("手动调拨表单加载不完整，请刷新页面后重试。");
    }

    const availableTargetCount = Array.from(targetSelect.options || []).filter((option) => option.value).length;

    if (!availableTargetCount) {
      setTransferOptionSummary(optionResult.notice || "当前没有可选的转入账户。");
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划转金额：-";
      }
      if (transferPreview) {
        transferPreview.hidden = true;
      }
      setTransferNotice(optionResult.notice || DEFAULT_TRANSFER_NOTICE);
      return;
    }

    setTransferOptionSummary(`当前可选转入账户 ${availableTargetCount} 个。`);
    setTransferNotice(optionResult.notice || DEFAULT_TRANSFER_NOTICE);
    syncDefaultTransferAmount();
  };

  const closeTransferModal = () => {
    if (!transferModal || !transferForm) return;

    transferModal.hidden = true;
    transferForm.reset();
    latestTransferOptions = null;
    fillSourceAccountOptions();
    fillTargetAccountOptions();
    if (transferPreview) {
      transferPreview.hidden = true;
    }
    if (transferDefaultHint) {
      transferDefaultHint.textContent = "默认划转金额：-";
    }
    setTransferOptionSummary("请选择转出账户。");
    setTransferNotice(DEFAULT_TRANSFER_NOTICE);
    syncBodyScrollLock();
  };

  if (transferModal) {
    transferModal.addEventListener("click", (event) => {
      if (event.target === transferModal) {
        closeTransferModal();
      }
    });
  }

  transferCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeTransferModal();
    });
  });

  if (transferForm) {
    getTransferField("from_account_id")?.addEventListener("change", async () => {
      try {
        await syncTransferTargets();
      } catch (error) {
        showToast(error?.message || "读取可执行调拨目标失败。");
      }
    });

    getTransferField("to_account_id")?.addEventListener("change", () => {
      syncDefaultTransferAmount();
    });

    getTransferField("amount")?.addEventListener("input", () => {
      renderTransferPreview();
    });
  }

  document.addEventListener("click", async (event) => {
    const balanceActionButton = event.target.closest("[data-balance-action]");
    if (!balanceActionButton || !transferModal || !transferForm) return;

    let accountId = String(balanceActionButton.getAttribute("data-balance-action") || "").trim();

    try {
      if (!accountId) {
        accountId = await resolveBalanceAccountId(balanceActionButton);
      }

      if (!accountId) {
        showToast("账户缺失，暂时无法调拨。");
        return;
      }

      transferModal.hidden = false;
      syncBodyScrollLock();
      setTransferNotice(DEFAULT_TRANSFER_NOTICE);
      fillSourceAccountOptions({ selectedAccountId: accountId });
      await syncTransferTargets();

      window.setTimeout(() => {
        const fromSelect = getTransferField("from_account_id");
        const targetSelect = getTransferField("to_account_id");
        if (!fromSelect || !targetSelect) {
          return;
        }

        if (targetSelect.disabled) {
          fromSelect.focus();
          return;
        }
        targetSelect.focus();
      }, 20);
    } catch (error) {
      showToast(error?.message || "读取账户失败，无法打开调拨窗口。");
      closeTransferModal();
    }
  });

  if (transferSaveButton && transferForm) {
    transferSaveButton.addEventListener("click", async () => {
      const fromSelect = getTransferField("from_account_id");
      const toSelect = getTransferField("to_account_id");
      const amountField = getTransferField("amount");
      if (!fromSelect || !toSelect || !amountField) {
        showToast("手动调拨表单加载不完整，请刷新页面后重试。");
        return;
      }

      const fromAccountId = Number(fromSelect.value || 0);
      const toAccountId = Number(toSelect.value || 0);
      const amount = Number(amountField.value || 0);

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

      const confirmMessage = [
        "确认创建手动划转记录？",
        `转出账户：${getAccountLabelById(fromAccountId) || "--"}`,
        `转入账户：${getAccountLabelById(toAccountId) || "--"}`,
        `划转金额：${formatMoney(amount)}`,
        "",
        "提交后由后台进程继续尝试执行实际划转。",
      ].join("\n");

      if (!window.confirm(confirmMessage)) {
        return;
      }

      transferSaveButton.disabled = true;
      try {
        const result = await createTransferRecord({
          from_account_id: fromAccountId,
          to_account_id: toAccountId,
          amount,
          reason: "手动划转",
        });

        if (!result.success) {
          showToast(result.message || "保存调拨记录失败。");
          return;
        }

        showToast(result.message || "手动划转记录已创建。");
        closeTransferModal();
      } catch (error) {
        showToast(error?.message || "保存调拨记录失败，请稍后再试。");
      } finally {
        transferSaveButton.disabled = false;
      }
    });
  }

  fillSourceAccountOptions();
  fillTargetAccountOptions();
  setTransferNotice(DEFAULT_TRANSFER_NOTICE);
  setTransferOptionSummary("请选择转出账户。");

  return {
    handleEscape() {
      if (!transferModal || transferModal.hidden) {
        return false;
      }
      closeTransferModal();
      return true;
    },
  };
}
