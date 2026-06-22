import { showToast } from "../../core/utils.js";
import { unlockAutoTransferAccount } from "./api.js";

export function bindAutoTransferGuardControls({ elements, refreshAccountTables }) {
  const {
    autoTransferAlertConfigButton,
    autoTransferAlertUnlockButton,
  } = elements;

  async function handleUnlock(button, accountId) {
    if (!accountId) {
      showToast("账户标识缺失，无法解冻自动调拨。");
      return;
    }

    button.disabled = true;
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
      button.disabled = false;
    }
  }

  document.addEventListener("click", async (event) => {
    const unlockButton = event.target.closest("[data-auto-transfer-unlock]");
    if (!unlockButton) return;

    const accountId = Number(unlockButton.getAttribute("data-auto-transfer-unlock") || 0);
    await handleUnlock(unlockButton, accountId);
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

}
