import { bindListPagination, bindPrototypeActions } from "../core/prototype.js";
import { bindLogoutAction } from "../core/utils.js";
import { bindAccountModal } from "./accounts/account-modal.js";
import { bindAutoTransferControls, refreshAutoTransferConfig } from "./accounts/auto-transfer.js";
import { bindBalanceConfigControls } from "./accounts/balance-config.js";
import { refreshAccountTables } from "./accounts/render.js";
import { bindAccountTabs } from "./accounts/tabs.js";
import { bindTransferModal } from "./accounts/transfer-modal.js";

function getAccountPageElements() {
  return {
    accountModal: document.querySelector("[data-account-modal]"),
    accountModalOpenButton: document.querySelector("[data-account-modal-open]"),
    accountModalCloseButtons: document.querySelectorAll("[data-account-modal-close]"),
    accountModalTitle: document.getElementById("account-modal-title"),
    accountForm: document.querySelector("[data-account-form]"),
    accountTestButton: document.querySelector("[data-account-test]"),
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

refreshAccountTables().catch(() => {});
refreshAutoTransferConfig(elements).catch(() => {});
