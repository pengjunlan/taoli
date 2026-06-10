import { bindListPagination, bindPrototypeActions, refreshListPagination } from "../core/prototype.js";
import { bindLogoutAction, postJson, showToast } from "../core/utils.js";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderTriggerConditions(triggerText) {
  const parts = String(triggerText || "")
    .split(" / ")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!parts.length) {
    return '<span class="strategy-trigger__line">--</span>';
  }

  return parts
    .map((item) => `<span class="strategy-trigger__line">${escapeHtml(item)}</span>`)
    .join("");
}

async function getJson(url) {
  const response = await fetch(url, {
    method: "GET",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
    },
    credentials: "same-origin",
  });

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { success: false, message: "服务响应格式错误。" };
  }

  if (!data.message && typeof data.detail === "string" && data.detail.trim()) {
    data.message = data.detail.trim();
  }

  if (!response.ok && !data.message) {
    data.message = "请求失败，请稍后再试。";
  }

  return data;
}

function updateSummaryCards(cards) {
  const list = Array.isArray(cards) ? cards : [];
  list.forEach((card) => {
    const key = String(card?.key || "").trim();
    if (!key) return;

    const container = document.querySelector(`[data-summary-card="${key}"]`);
    if (!container) return;

    const label = container.querySelector("[data-summary-label]");
    const value = container.querySelector("[data-summary-value]");
    const change = container.querySelector("[data-summary-change]");

    if (label) label.textContent = String(card.label || "");
    if (value) value.textContent = String(card.value || "");
    if (change) change.textContent = String(card.change || "");

    container.className = `stats-card stats-card--${String(card.tone || "brand")}`;
  });
}

function renderStrategyRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="11" class="spread-metric">暂无规则，请先新增策略规则</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr data-strategy-row="${escapeHtml(row.id)}">
          <td>
            <div class="spread-symbol">
              <strong>${escapeHtml(row.name)}</strong>
              <span class="spread-symbol__hint">${escapeHtml(row.strategy_type_label)}</span>
            </div>
          </td>
          <td>${escapeHtml(row.strategy_type_label)}</td>
          <td>
            <div class="strategy-trigger">
              ${renderTriggerConditions(row.trigger_text)}
            </div>
          </td>
          <td class="spread-metric">${escapeHtml(row.max_spread_rate_threshold_text || "--")}</td>
          <td class="spread-metric">${escapeHtml(row.max_pairs)}</td>
          <td class="spread-metric spread-metric--strong">${escapeHtml(row.order_amount_text)}</td>
          <td class="spread-metric spread-metric--strong">${escapeHtml(row.max_position_text)}</td>
          <td class="spread-metric">${escapeHtml(row.order_interval_text)}</td>
          <td>
            <span class="pill pill--${escapeHtml(row.status_tone)}">${escapeHtml(row.status_label)}</span>
          </td>
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-strategy-edit="${escapeHtml(row.id)}">编辑</button>
              <button class="table-action" type="button" data-strategy-delete="${escapeHtml(row.id)}">删除</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

async function refreshStrategyRules() {
  const result = await getJson("/api/strategies/list");
  if (!result.success) {
    throw new Error(result.message || "读取规则列表失败。");
  }

  const body = document.querySelector("[data-strategy-table-body]");
  const count = document.querySelector("[data-rule-count]");

  updateSummaryCards(result.summary_cards || []);

  if (body) {
    body.innerHTML = renderStrategyRows(result.rule_rows || []);
  }

  if (count) {
    count.textContent = `共 ${Number(result.rule_count || 0)} 条规则`;
  }

  refreshListPagination(document);
}

function bindStrategyModal() {
  const modal = document.querySelector("[data-strategy-modal]");
  const form = document.querySelector("[data-strategy-form]");
  const openButton = document.querySelector("[data-rule-create]");
  const closeButtons = document.querySelectorAll("[data-strategy-modal-close]");
  const typeField = document.querySelector("[data-strategy-type]");
  const annualizedField = document.querySelector("[data-field-annualized]");
  const spreadField = document.querySelector("[data-field-spread]");
  const confirmModal = document.querySelector("[data-strategy-confirm]");
  const confirmMessage = document.querySelector("[data-strategy-confirm-message]");
  const confirmAccept = document.querySelector("[data-strategy-confirm-accept]");
  const confirmCancelButtons = document.querySelectorAll("[data-strategy-confirm-cancel]");
  const title = document.getElementById("strategy-modal-title");
  const hiddenRuleId = form?.querySelector('input[name="rule_id"]');
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!modal || !form || !openButton || !typeField || !annualizedField || !spreadField || !title || !hiddenRuleId || !submitButton) {
    return;
  }

  let pendingDeleteResolver = null;

  const syncBodyScrollLock = () => {
    const hasVisibleLayer = [modal, confirmModal].some((element) => element && !element.hidden);
    document.body.style.overflow = hasVisibleLayer ? "hidden" : "";
  };

  const syncTypeFields = () => {
    const strategyType = String(typeField.value || "funding").trim();
    const isFunding = strategyType === "funding";
    annualizedField.classList.toggle("is-hidden", !isFunding);
    spreadField.classList.toggle("is-hidden", isFunding);
    form.elements.annualized_rate_threshold.disabled = !isFunding;
    form.elements.spread_rate_threshold.disabled = isFunding;

    if (isFunding) {
      form.elements.spread_rate_threshold.value = 0;
    } else {
      form.elements.annualized_rate_threshold.value = 0;
    }
  };

  const resetFormMode = () => {
    form.dataset.mode = "create";
    form.reset();
    hiddenRuleId.value = "";
    typeField.value = "funding";
    form.elements.annualized_rate_threshold.value = 0;
    form.elements.spread_rate_threshold.value = 0;
    form.elements.max_spread_rate_threshold.value = 0;
    form.elements.max_pairs.value = 1;
    form.elements.order_amount_usdt.value = 0;
    form.elements.max_position_usdt.value = 0;
    form.elements.order_interval_seconds.value = 0;
    form.elements.is_enabled.checked = true;
    title.textContent = "新增规则";
    submitButton.textContent = "保存规则";
    syncTypeFields();
  };

  const openModal = () => {
    modal.hidden = false;
    syncBodyScrollLock();
    const firstInput = form.querySelector("input, select");
    if (firstInput) {
      window.setTimeout(() => firstInput.focus(), 20);
    }
  };

  const closeModal = () => {
    modal.hidden = true;
    syncBodyScrollLock();
    resetFormMode();
  };

  const fillForm = (rule) => {
    const strategyType = String(rule.strategy_type || "funding");

    form.dataset.mode = "edit";
    hiddenRuleId.value = String(rule.id || "");
    form.elements.name.value = String(rule.name || "");
    form.elements.strategy_type.value = strategyType;
    form.elements.annualized_rate_threshold.value = Number(rule.annualized_rate_threshold || 0);
    form.elements.spread_rate_threshold.value = Number(rule.spread_rate_threshold || 0);
    form.elements.max_spread_rate_threshold.value = Number(rule.max_spread_rate_threshold || 0);
    form.elements.max_pairs.value = Number(rule.max_pairs || 1);
    form.elements.order_amount_usdt.value = Number(rule.order_amount_usdt || 0);
    form.elements.max_position_usdt.value = Number(rule.max_position_usdt || 0);
    form.elements.order_interval_seconds.value = Number(rule.order_interval_seconds || 0);
    form.elements.is_enabled.checked = Boolean(rule.is_enabled);

    if (strategyType === "funding") {
      form.elements.spread_rate_threshold.value = 0;
    } else {
      form.elements.annualized_rate_threshold.value = 0;
    }

    title.textContent = "编辑规则";
    submitButton.textContent = "保存修改";
    syncTypeFields();
  };

  const openDeleteConfirm = (message) =>
    new Promise((resolve) => {
      if (!confirmModal || !confirmMessage) {
        resolve(false);
        return;
      }
      pendingDeleteResolver = resolve;
      confirmMessage.textContent = message;
      confirmModal.hidden = false;
      syncBodyScrollLock();
    });

  const closeDeleteConfirm = (accepted) => {
    if (!confirmModal) return;
    confirmModal.hidden = true;
    syncBodyScrollLock();
    if (pendingDeleteResolver) {
      pendingDeleteResolver(accepted);
      pendingDeleteResolver = null;
    }
  };

  openButton.addEventListener("click", () => {
    resetFormMode();
    openModal();
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeModal();
    });
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  if (confirmModal) {
    confirmModal.addEventListener("click", (event) => {
      if (event.target === confirmModal) {
        closeDeleteConfirm(false);
      }
    });
  }

  confirmCancelButtons.forEach((button) => {
    button.addEventListener("click", () => {
      closeDeleteConfirm(false);
    });
  });

  if (confirmAccept) {
    confirmAccept.addEventListener("click", () => {
      closeDeleteConfirm(true);
    });
  }

  typeField.addEventListener("change", syncTypeFields);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
    if (event.key === "Escape" && confirmModal && !confirmModal.hidden) {
      closeDeleteConfirm(false);
    }
  });

  document.addEventListener("click", async (event) => {
    const editButton = event.target.closest("[data-strategy-edit]");
    if (!editButton) return;

    const ruleId = String(editButton.getAttribute("data-strategy-edit") || "").trim();
    if (!ruleId) {
      showToast("规则 ID 缺失，无法编辑。");
      return;
    }

    editButton.disabled = true;
    try {
      const result = await getJson(`/api/strategies/${ruleId}`);
      if (!result.success || !result.rule) {
        showToast(result.message || "读取规则失败。");
        return;
      }

      fillForm(result.rule);
      openModal();
    } catch (error) {
      showToast(error?.message || "读取规则失败，请稍后再试。");
    } finally {
      editButton.disabled = false;
    }
  });

  document.addEventListener("click", async (event) => {
    const deleteButton = event.target.closest("[data-strategy-delete]");
    if (!deleteButton) return;

    const ruleId = String(deleteButton.getAttribute("data-strategy-delete") || "").trim();
    if (!ruleId) {
      showToast("规则 ID 缺失，无法删除。");
      return;
    }

    const confirmed = await openDeleteConfirm("确定删除这条规则吗？删除后不可恢复。");
    if (!confirmed) return;

    deleteButton.disabled = true;
    try {
      const result = await postJson(`/api/strategies/${ruleId}/delete`);
      if (!result.success) {
        showToast(result.message || "删除规则失败。");
        return;
      }

      await refreshStrategyRules();
      showToast(result.message || "规则已删除。");
    } catch (error) {
      showToast(error?.message || "删除规则失败，请稍后再试。");
    } finally {
      deleteButton.disabled = false;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;

    const formData = new FormData(form);
    const payload = {
      name: String(formData.get("name") || "").trim(),
      strategy_type: String(formData.get("strategy_type") || "").trim(),
      annualized_rate_threshold: Number(formData.get("annualized_rate_threshold") || 0),
      spread_rate_threshold: Number(formData.get("spread_rate_threshold") || 0),
      max_spread_rate_threshold: Number(formData.get("max_spread_rate_threshold") || 0),
      max_pairs: Number(formData.get("max_pairs") || 0),
      order_amount_usdt: Number(formData.get("order_amount_usdt") || 0),
      max_position_usdt: Number(formData.get("max_position_usdt") || 0),
      order_interval_seconds: Number(formData.get("order_interval_seconds") || 0),
      is_enabled: form.elements.is_enabled.checked,
    };

    if (payload.strategy_type === "funding") {
      payload.spread_rate_threshold = 0;
    }
    if (payload.strategy_type === "spread") {
      payload.annualized_rate_threshold = 0;
    }

    const isEditMode = form.dataset.mode === "edit";
    const ruleId = String(formData.get("rule_id") || "").trim();
    const url = isEditMode && ruleId ? `/api/strategies/${ruleId}` : "/api/strategies";

    try {
      const result = await postJson(url, payload);
      if (!result.success) {
        showToast(result.message || (isEditMode ? "更新规则失败。" : "保存规则失败。"));
        return;
      }

      await refreshStrategyRules();
      showToast(result.message || (isEditMode ? "规则已更新。" : "规则已保存。"));
      closeModal();
    } catch (error) {
      showToast(error?.message || (isEditMode ? "更新规则失败，请稍后再试。" : "保存规则失败，请稍后再试。"));
    } finally {
      submitButton.disabled = false;
    }
  });

  resetFormMode();
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindStrategyModal();
refreshStrategyRules().catch((error) => {
  showToast(error?.message || "读取规则列表失败，请稍后再试。");
});
