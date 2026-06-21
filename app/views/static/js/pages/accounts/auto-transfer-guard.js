import { showToast } from "../../core/utils.js";
import { unlockAutoTransferAccount } from "./api.js";

export function bindAutoTransferGuardControls({ elements, refreshAccountTables }) {
  const {
    autoTransferAlertConfigButton,
    autoTransferAlertUnlockButton,
  } = elements;

  document.addEventListener("click", async (event) => {
    const unlockButton = event.target.closest("[data-auto-transfer-unlock]");
    if (!unlockButton) return;

    const accountId = Number(unlockButton.getAttribute("data-auto-transfer-unlock") || 0);
    if (!accountId) {
      showToast("账户标识缺失，无法解冻自动调拨。");
      return;
    }

    unlockButton.disabled = true;
    try {
      const result = await unlockAutoTransferAccount(accountId);
      if (!result.success) {
        showToast(result.message || "解冻自动调拨失败。");
        return;
      }

      await refreshAccountTables();
      showToast(result.message || "该账户自动调拨已解冻。");
    } catch (error) {
      showToast(error?.message || "解冻自动调拨失败，请稍后再试。");
    } finally {
      unlockButton.disabled = false;
    }
  });

  if (autoTransferAlertConfigButton) {
    autoTransferAlertConfigButton.addEventListener("click", () => {
      const accountId = Number(autoTransferAlertConfigButton.getAttribute("data-account-id") || 0);
      if (!accountId) {
        return;
      }
      const editButton = document.querySelector(`[data-account-edit="${accountId}"]`);
      if (!editButton) {
        showToast("未找到对应账户，请刷新页面后重试。");
        return;
      }
      editButton.click();
    });
  }

  if (autoTransferAlertUnlockButton) {
    autoTransferAlertUnlockButton.addEventListener("click", () => {
      const accountId = Number(autoTransferAlertUnlockButton.getAttribute("data-account-id") || 0);
      if (!accountId) {
        return;
      }
      const rowButton = document.querySelector(`[data-auto-transfer-unlock="${accountId}"]`);
      if (!rowButton) {
        showToast("未找到对应解冻按钮，请刷新页面后重试。");
        return;
      }
      rowButton.click();
    });
  }
}
