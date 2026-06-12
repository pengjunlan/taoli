import { refreshListPagination } from "../../core/prototype.js";

export function bindAccountTabs() {
  const triggers = Array.from(document.querySelectorAll("[data-account-tab-trigger]"));
  const panels = Array.from(document.querySelectorAll("[data-account-tab-panel]"));

  if (!triggers.length || !panels.length) return;

  const activateTab = (tabKey) => {
    triggers.forEach((trigger) => {
      const isActive = trigger.getAttribute("data-account-tab-trigger") === tabKey;
      trigger.classList.toggle("is-active", isActive);
      trigger.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    panels.forEach((panel) => {
      const isActive = panel.getAttribute("data-account-tab-panel") === tabKey;
      panel.classList.toggle("is-active", isActive);
      panel.hidden = !isActive;
    });

    refreshListPagination(document);
  };

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      activateTab(trigger.getAttribute("data-account-tab-trigger"));
    });
  });
}
