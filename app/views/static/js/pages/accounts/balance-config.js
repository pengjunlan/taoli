import { showToast } from "../../core/utils.js";
import { updateFundingRatio } from "./api.js";
import { resolveBalanceAccountId } from "./render.js";

export function bindBalanceConfigControls({ elements, syncBodyScrollLock, refreshAccountTables }) {
  const {
    balanceConfigModal,
    balanceConfigForm,
    balanceConfigSaveButton,
    balanceConfigCloseButtons,
  } = elements;

  const closeBalanceConfigModal = () => {
    if (!balanceConfigModal || !balanceConfigForm) return;
    balanceConfigModal.hidden = true;
    balanceConfigForm.reset();
    balanceConfigForm.elements.account_id.value = "";
    balanceConfigForm.elements.funding_ratio_percent.value = "0";
    syncBodyScrollLock();
  };

  if (balanceConfigModal) {
    balanceConfigModal.addEventListener("click", (event) => {
      if (event.target === balanceConfigModal) {
        closeBalanceConfigModal();
      }
    });
  }

  balanceConfigCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeBalanceConfigModal();
    });
  });

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

  if (balanceConfigSaveButton && balanceConfigForm) {
    balanceConfigSaveButton.addEventListener("click", async () => {
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

      balanceConfigSaveButton.disabled = true;
      try {
        const result = await updateFundingRatio(accountId, {
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
        balanceConfigSaveButton.disabled = false;
      }
    });
  }

  return {
    handleEscape() {
      if (!balanceConfigModal || balanceConfigModal.hidden) {
        return false;
      }
      closeBalanceConfigModal();
      return true;
    },
  };
}
