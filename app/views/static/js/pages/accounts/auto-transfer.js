import { showToast } from "../../core/utils.js";
import { fetchAutoTransferConfig, updateAutoTransferConfig } from "./api.js";
import { getFormField } from "./form-fields.js";
import { getLatestAutoTransferConfig, setLatestAutoTransferConfig } from "./state.js";

export function syncAutoTransferToggleUi(elements) {
  const { autoTransferToggleButton, autoTransferToggleLabel } = elements;
  if (!autoTransferToggleButton || !autoTransferToggleLabel) return;

  const config = getLatestAutoTransferConfig();
  const isEnabled = Boolean(config?.is_enabled);
  autoTransferToggleButton.classList.toggle("is-enabled", isEnabled);
  autoTransferToggleButton.setAttribute("aria-pressed", isEnabled ? "true" : "false");
  autoTransferToggleLabel.textContent = isEnabled ? "自动调拨已开启" : "自动调拨已关闭";
}

export async function refreshAutoTransferConfig(elements) {
  const result = await fetchAutoTransferConfig();
  if (!result.success) {
    throw new Error(result.message || "读取自动调拨配置失败。");
  }

  const config = setLatestAutoTransferConfig(result.config);
  syncAutoTransferToggleUi(elements);
  return config;
}

export function bindAutoTransferControls({ elements, syncBodyScrollLock, refreshAccountTables }) {
  const {
    autoTransferModal,
    autoTransferForm,
    autoTransferOpenButton,
    autoTransferToggleButton,
    autoTransferSaveButton,
    autoTransferCloseButtons,
  } = elements;

  const closeAutoTransferModal = () => {
    if (!autoTransferModal || !autoTransferForm) return;
    autoTransferModal.hidden = true;
    syncBodyScrollLock();
  };

  const getTriggerRatioField = () => getFormField(autoTransferForm, "trigger_ratio_percent");

  if (autoTransferModal) {
    autoTransferModal.addEventListener("click", (event) => {
      if (event.target === autoTransferModal) {
        closeAutoTransferModal();
      }
    });
  }

  autoTransferCloseButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeAutoTransferModal();
    });
  });

  if (autoTransferOpenButton && autoTransferModal && autoTransferForm) {
    autoTransferOpenButton.addEventListener("click", async () => {
      try {
        const config = await refreshAutoTransferConfig(elements);
        const triggerRatioField = getTriggerRatioField();
        if (!triggerRatioField) {
          throw new Error("自动调拨配置表单加载不完整，请刷新页面后重试。");
        }

        triggerRatioField.value = String(
          Math.round(Number(config.trigger_ratio || 0.5) * 100),
        );
        autoTransferModal.hidden = false;
        syncBodyScrollLock();
      } catch (error) {
        showToast(error?.message || "读取自动调拨配置失败，请稍后再试。");
      }
    });
  }

  if (autoTransferToggleButton) {
    autoTransferToggleButton.addEventListener("click", async () => {
      const nextEnabled = !Boolean(getLatestAutoTransferConfig()?.is_enabled);
      autoTransferToggleButton.disabled = true;
      try {
        const result = await updateAutoTransferConfig({
          is_enabled: nextEnabled,
          trigger_ratio: Number(getLatestAutoTransferConfig()?.trigger_ratio || 0.5),
        });
        if (!result.success) {
          showToast(result.message || "更新自动调拨开关失败。");
          return;
        }

        setLatestAutoTransferConfig(result.config);
        syncAutoTransferToggleUi(elements);
        await refreshAccountTables();

        if (autoTransferForm) {
          const triggerRatioField = getTriggerRatioField();
          if (triggerRatioField) {
            triggerRatioField.value = String(
            Math.round(Number(getLatestAutoTransferConfig().trigger_ratio || 0.5) * 100),
            );
          }
        }

        showToast(
          result.auto_transfer_executed
            ? "自动调拨配置已保存，并已按规则创建一条真实调拨任务。"
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
      const triggerRatioField = getTriggerRatioField();
      if (!triggerRatioField) {
        showToast("自动调拨配置表单加载不完整，请刷新页面后重试。");
        return;
      }

      const triggerRatioPercent = Number(triggerRatioField.value || 50);
      if (Number.isNaN(triggerRatioPercent) || triggerRatioPercent <= 0 || triggerRatioPercent > 100) {
        showToast("触发比例必须在 1 到 100 之间。");
        return;
      }

      autoTransferSaveButton.disabled = true;
      try {
        const result = await updateAutoTransferConfig({
          is_enabled: Boolean(getLatestAutoTransferConfig()?.is_enabled),
          trigger_ratio: triggerRatioPercent / 100,
        });
        if (!result.success) {
          showToast(result.message || "保存自动调拨配置失败。");
          return;
        }

        setLatestAutoTransferConfig(result.config);
        syncAutoTransferToggleUi(elements);
        await refreshAccountTables();

        showToast(
          result.auto_transfer_executed
            ? "自动调拨配置已保存，并已按规则创建一条真实调拨任务。"
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

  return {
    handleEscape() {
      if (!autoTransferModal || autoTransferModal.hidden) {
        return false;
      }
      closeAutoTransferModal();
      return true;
    },
  };
}
