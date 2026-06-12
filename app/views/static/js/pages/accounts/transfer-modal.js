import { showToast } from "../../core/utils.js";
import { createTransferRecord, fetchTransferOptions } from "./api.js";
import { escapeHtml, formatMoney, parseMoney } from "./formatters.js";
import { findBalanceRowById, resolveBalanceAccountId } from "./render.js";

const DEFAULT_REAL_TRANSFER_NOTICE = "当前仅支持 Binance / OKX 的真实调拨路径，提交后会进入后台真实执行，请确认账户、网络与金额无误。";

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

  let currentTransferContext = null;

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

  const fillTransferTargetOptions = (options) => {
    if (!transferForm) return;
    const select = transferForm.elements.to_account_id;
    if (!select) return;

    const items = Array.isArray(options) ? options : [];
    const optionHtml = items.map(
      (item) =>
        `<option value="${escapeHtml(item.id || "")}">${escapeHtml(item.name || "")} / ${escapeHtml(item.exchange || "")} / ${escapeHtml(item.market_type || "")} / ${escapeHtml(item.mode_label || "真实调拨")}</option>`,
    );

    select.innerHTML = `<option value="">请选择转入账户</option>${optionHtml.join("")}`;
    select.disabled = items.length === 0;
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
        transferDefaultHint.textContent = "默认划拨金额：-";
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
        transferDefaultHint.textContent = "默认划拨金额：-";
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
    transferForm.elements.to_account_id.disabled = false;
    currentTransferContext = null;
    if (transferPreview) {
      transferPreview.hidden = true;
    }
    if (transferDefaultHint) {
      transferDefaultHint.textContent = "默认划拨金额：-";
    }
    setTransferOptionSummary("正在读取可执行目标...");
    setTransferNotice(DEFAULT_REAL_TRANSFER_NOTICE);
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
    transferForm.elements.to_account_id?.addEventListener("change", () => {
      syncDefaultTransferAmount();
    });

    transferForm.elements.amount?.addEventListener("input", () => {
      renderTransferPreview();
    });
  }

  document.addEventListener("click", async (event) => {
    const balanceActionButton = event.target.closest("[data-balance-action]");
    if (!balanceActionButton || !transferModal || !transferForm) return;

    const isSupported = String(balanceActionButton.getAttribute("data-balance-action-supported") || "true") === "true";
    if (!isSupported) {
      showToast(balanceActionButton.getAttribute("data-balance-action-reason") || "当前没有可真实执行的调拨目标。");
      return;
    }

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
      transferModal.hidden = false;
      syncBodyScrollLock();
      transferForm.elements.to_account_id.innerHTML = `<option value="">正在读取可执行目标...</option>`;
      transferForm.elements.to_account_id.disabled = true;
      setTransferOptionSummary("正在读取可执行目标...");
      setTransferNotice(DEFAULT_REAL_TRANSFER_NOTICE);
      if (transferPreview) {
        transferPreview.hidden = true;
      }
      if (transferDefaultHint) {
        transferDefaultHint.textContent = "默认划拨金额：-";
      }
      const optionsResult = await fetchTransferOptions(accountId);
      if (!optionsResult.success) {
        showToast(optionsResult.message || "读取可执行调拨目标失败。");
        closeTransferModal();
        return;
      }

      fillTransferTargetOptions(optionsResult.options || []);
      setTransferNotice(optionsResult.notice || DEFAULT_REAL_TRANSFER_NOTICE);
      setTransferOptionSummary(
        `当前可真实执行目标 ${Number(optionsResult.option_count || 0)} 个，已过滤不可执行目标 ${Number(optionsResult.blocked_count || 0)} 个`,
      );

      if (!Array.isArray(optionsResult.options) || !optionsResult.options.length) {
        showToast("当前没有可真实执行的调拨目标，请先检查目标账户支持范围和地址配置。");
        return;
      }

      window.setTimeout(() => transferForm.elements.to_account_id.focus(), 20);
    } catch (error) {
      showToast(error?.message || "读取账户失败，无法打开调拨窗口。");
      closeTransferModal();
    }
  });

  if (transferSaveButton && transferForm) {
    transferSaveButton.addEventListener("click", async () => {
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

      const toAccountLabel = String(
        transferForm.elements.to_account_id.selectedOptions?.[0]?.textContent || "",
      ).trim();
      const confirmMessage = [
        "确认发起真实调拨？",
        `转出账户：${String(transferForm.elements.from_account_name.value || "").trim() || "--"}`,
        `转入账户：${toAccountLabel || "--"}`,
        `划转金额：${formatMoney(amount)}`,
        "",
        "该操作会调用交易所接口并进入后台执行，请确认账户、网络与金额无误。",
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
          reason: "手动真实调拨",
        });
        if (!result.success) {
          showToast(result.message || "保存调拨记录失败。");
          return;
        }

        showToast(result.message || "真实调拨任务已创建。");
        closeTransferModal();
      } catch (error) {
        showToast(error?.message || "保存调拨记录失败，请稍后再试。");
      } finally {
        transferSaveButton.disabled = false;
      }
    });
  }

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
