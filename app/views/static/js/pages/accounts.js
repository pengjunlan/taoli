import { createLiveSocket } from "../core/live-socket.js";
import { bindListPagination, bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction } from "../core/utils.js";
import { bindAccountModal } from "./accounts/account-modal.js";
import { bindAutoTransferControls, refreshAutoTransferConfig, syncAutoTransferToggleUi } from "./accounts/auto-transfer.js";
import { bindBalanceConfigControls } from "./accounts/balance-config.js";
import { applyAccountsPayload, refreshAccountTables } from "./accounts/render.js";
import { setLatestAutoTransferConfig } from "./accounts/state.js";
import { bindAccountTabs } from "./accounts/tabs.js";
import { bindTransferModal } from "./accounts/transfer-modal.js";
import { bindAutoTransferGuardControls } from "./accounts/auto-transfer-guard.js";

let liveSocket = null;

function getAccountPageElements() {
  return {
    accountModal: document.querySelector("[data-account-modal]"),
    accountModalOpenButton: document.querySelector("[data-account-modal-open]"),
    accountModalCloseButtons: document.querySelectorAll("[data-account-modal-close]"),
    accountModalTitle: document.getElementById("account-modal-title"),
    accountForm: document.querySelector("[data-account-form]"),
    accountTestButton: document.querySelector("[data-account-test]"),
    accountNetworkHint: document.querySelector("[data-account-network-hint]"),
    confirmModal: document.querySelector("[data-account-confirm]"),
    confirmMessage: document.querySelector("[data-account-confirm-message]"),
    confirmAcceptButton: document.querySelector("[data-account-confirm-accept]"),
    confirmCancelButtons: document.querySelectorAll("[data-account-confirm-cancel]"),
    balanceConfigModal: document.querySelector("[data-balance-config-modal]"),
    balanceConfigForm: document.querySelector("[data-balance-config-form]"),
    balanceConfigSaveButton: document.querySelector("[data-balance-config-save]"),
    balanceConfigCloseButtons: document.querySelectorAll("[data-balance-config-close]"),
    autoTransferModal: document.querySelector("[data-auto-transfer-modal]"),
    autoTransferForm: document.querySelector("[data-auto-transfer-form]"),
    autoTransferOpenButton: document.querySelector("[data-auto-transfer-open]"),
    autoTransferToggleButton: document.querySelector("[data-auto-transfer-toggle]"),
    autoTransferToggleLabel: document.querySelector("[data-auto-transfer-toggle-label]"),
    autoTransferSaveButton: document.querySelector("[data-auto-transfer-save]"),
    autoTransferCloseButtons: document.querySelectorAll("[data-auto-transfer-close]"),
    transferModal: document.querySelector("[data-transfer-modal]"),
    transferForm: document.querySelector("[data-transfer-form]"),
    transferSaveButton: document.querySelector("[data-transfer-save]"),
    transferCloseButtons: document.querySelectorAll("[data-transfer-close]"),
    transferPreview: document.querySelector("[data-transfer-preview]"),
    transferDefaultHint: document.querySelector("[data-transfer-default-hint]"),
    transferNotice: document.querySelector("[data-transfer-notice]"),
    transferOptionSummary: document.querySelector("[data-transfer-option-summary]"),
    autoTransferAlert: document.querySelector("[data-auto-transfer-alert]"),
    autoTransferAlertTitle: document.querySelector("[data-auto-transfer-alert-title]"),
    autoTransferAlertMessage: document.querySelector("[data-auto-transfer-alert-message]"),
    autoTransferAlertConfigButton: document.querySelector("[data-auto-transfer-alert-config]"),
    autoTransferAlertUnlockButton: document.querySelector("[data-auto-transfer-alert-unlock]"),
  };
}

const elements = getAccountPageElements();

function syncBodyScrollLock() {
  const layers = [
    elements.accountModal,
    elements.confirmModal,
    elements.balanceConfigModal,
    elements.autoTransferModal,
    elements.transferModal,
  ];
  const hasVisibleLayer = layers.some((element) => element && !element.hidden);
  document.body.style.overflow = hasVisibleLayer ? "hidden" : "";
}

function applyLivePayload(payload) {
  applyAccountsPayload(payload);
  setLatestAutoTransferConfig(payload.auto_transfer_config || {});
  syncAutoTransferToggleUi(elements);
}

function startLiveUpdates() {
  liveSocket?.close();
  liveSocket = createLiveSocket({
    channel: "accounts",
    suppressErrorToast: true,
    onMessage(payload) {
      if (!payload?.success) {
        return;
      }
      applyLivePayload(payload);
    },
  });
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindAccountTabs();

const accountModalControls = bindAccountModal({
  elements,
  syncBodyScrollLock,
  refreshAccountTables,
});

const balanceConfigControls = bindBalanceConfigControls({
  elements,
  syncBodyScrollLock,
  refreshAccountTables,
});

const autoTransferControls = bindAutoTransferControls({
  elements,
  syncBodyScrollLock,
  refreshAccountTables,
});

const transferModalControls = bindTransferModal({
  elements,
  syncBodyScrollLock,
});

bindAutoTransferGuardControls({
  elements,
  refreshAccountTables,
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }

  const handlers = [
    accountModalControls.handleEscape,
    balanceConfigControls.handleEscape,
    autoTransferControls.handleEscape,
    transferModalControls.handleEscape,
  ];

  handlers.some((handleEscape) => typeof handleEscape === "function" && handleEscape());
});

Promise.allSettled([
  refreshAccountTables(),
  refreshAutoTransferConfig(elements),
]).finally(() => {
  startLiveUpdates();
});

window.addEventListener("beforeunload", () => {
  liveSocket?.close();
});
