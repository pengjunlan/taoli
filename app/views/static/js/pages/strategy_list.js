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

const STRATEGY_FIELD_HINTS = {
  name: "给这套策略起一个容易识别的名字，只用于列表展示和后续排查。",
  strategy_type: "选择策略模型：资金费套利看资金费率，价差套利看跨交易所价差。",
  annualized_rate_threshold: "资金费套利开仓阈值。净资金费率达到该值后，才允许进入开仓判断。",
  min_net_funding_rate_threshold: "资金费套利正常平仓线。净资金费率回落到该值以下，说明继续持有不划算。",
  spread_rate_threshold: "价差套利开仓最小值。只有价差率高于这个下限，才允许进入区间开仓判断。",
  open_spread_rate_max_threshold: "价差套利开仓最大值。只有价差率落在最小值和这个最大值之间，才允许开仓，避免在异常大价差附近来回摩擦。",
  min_close_spread_rate_threshold: "价差套利正常平仓线。价差回落到该值以下，说明价差收益空间基本释放。",
  max_spread_rate_threshold: "风险边界。这个值更适合做持仓后的止损/停加仓上限，不建议与开仓最大价差共用。",
  max_pairs: "限制同一规则最多同时运行多少个交易对，防止机会过多时占满资金。资金费套利与价差套利都按同一口径理解。",
  order_amount_usdt: "页面统一展示为每次开仓/加仓目标金额。比如填 100U，表示本次希望累计做到 100U。",
  max_position_usdt: "同一交易对在这条规则下允许累计持有的最大名义金额上限，单位 U。资金费套利与价差套利都按同一口径理解。",
  order_interval_seconds: "页面统一展示为子委托之间的节奏间隔。比如目标 100U、子委托 10U，则可按这个间隔逐笔推进。",
  split_order_amount_usdt: "实际子委托金额。表示一次真实委托要发出的金额，例如目标 100U、子委托 10U，则系统会按约 10 笔逐步完成。",
  funding_open_window_start_minutes: "资金费结算前多少分钟开始允许开仓。填 0 表示不限制最早开仓时间。",
  funding_open_window_end_minutes: "距离结算太近时停止新开仓，避免最后几分钟成交/滑点风险。填 0 表示不限制。",
  funding_settlement_skew_minutes: "两个交易所的资金费结算时间允许最多相差多少分钟。超过这个时间差，就不做这组资金费套利。填 0 表示必须同一结算时间，不允许错开。",
  funding_spread_resonance_min: "资金费方向和价差方向同向时，要求价差至少达到多少。填 0 表示只要求同向，不要求最小幅度。",
  net_spread_threshold: "扣除手续费、滑点和预估资金费成本后的真实价差开仓门槛。",
  funding_carry_min: "价差套利方向下，资金费收益至少不能太差。填 0 表示不额外要求资金费正贡献。",
  max_funding_cost: "价差套利持仓期间最多允许被资金费消耗多少收益，超过后停止加仓或考虑退出。",
  min_net_profit_threshold: "最低净收益保护。预期收益必须覆盖手续费、滑点和安全垫后才允许开仓。",
  take_profit_threshold: "后续建议按组合整体浮盈率来触发止盈，并配合分批平仓执行。",
  drawdown_add_step_percent: "价差套利加仓阶梯。系统会把它作为相对上一次开仓/加仓基准价差的恶化间隔，达到一个阶梯才允许再按目标金额发起下一轮加仓。",
  max_hold_minutes: "单个套利持仓最多持有多久。填 0 表示不按时间强制退出。",
  close_interval_seconds: "分批平仓时，两批之间至少间隔多少秒。填 0 表示不做间隔限制。",
  close_batch_count: "本地页面预留字段，当前已隐藏，不参与当前页面配置。",
  close_batch_ratio_percent: "单批平仓金额。比如当前组合还有 100U，填 10 表示每次平约 10U；平完后按平仓间隔时间等待，再继续下一批，直到全部平完。填 0 表示不分批，直接一次性平完。",
  single_leg_timeout_seconds: "一边成交、另一边迟迟未成交时，等待多久后进入异常处理。填 0 表示使用系统默认保护。",
  is_enabled: "启用后该规则会参与自动筛选和执行；关闭后只保留配置，不再触发新的自动开仓。",
};

const STRATEGY_COPY_BY_TYPE = {
  funding: {
    max_pairs: "最大运行交易对数",
    order_amount_usdt: "每次开仓/加仓目标金额 (U)",
    max_position_usdt: "单交易对累计持仓上限 (U)",
    order_interval_seconds: "子委托间隔时间 (秒)",
  },
  spread: {
    max_pairs: "最大运行交易对数",
    order_amount_usdt: "每次开仓/加仓目标金额 (U)",
    max_position_usdt: "单交易对累计持仓上限 (U)",
    order_interval_seconds: "子委托间隔时间 (秒)",
  },
};

let strategyFieldTooltip = null;
let activeStrategyFieldTooltipTrigger = null;

function getStrategyFieldTooltip() {
  if (strategyFieldTooltip) return strategyFieldTooltip;

  strategyFieldTooltip = document.createElement("div");
  strategyFieldTooltip.className = "strategy-field-tooltip";
  strategyFieldTooltip.setAttribute("role", "tooltip");
  strategyFieldTooltip.hidden = true;
  document.body.appendChild(strategyFieldTooltip);
  return strategyFieldTooltip;
}

function positionStrategyFieldTooltip(trigger, tooltip) {
  const margin = 12;
  const gap = 8;
  const rect = trigger.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();

  let left = rect.left;
  let top = rect.bottom + gap;

  if (left + tooltipRect.width + margin > window.innerWidth) {
    left = window.innerWidth - tooltipRect.width - margin;
  }
  if (left < margin) {
    left = margin;
  }

  if (top + tooltipRect.height + margin > window.innerHeight) {
    top = rect.top - tooltipRect.height - gap;
  }
  if (top < margin) {
    top = margin;
  }

  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function showStrategyFieldTooltip(trigger) {
  const hint = trigger.getAttribute("data-tooltip");
  if (!hint) return;

  activeStrategyFieldTooltipTrigger = trigger;
  const tooltip = getStrategyFieldTooltip();
  tooltip.textContent = hint;
  tooltip.hidden = false;
  tooltip.classList.add("is-visible");
  positionStrategyFieldTooltip(trigger, tooltip);
}

function hideStrategyFieldTooltip() {
  if (!strategyFieldTooltip) return;

  activeStrategyFieldTooltipTrigger = null;
  strategyFieldTooltip.classList.remove("is-visible");
  strategyFieldTooltip.hidden = true;
}

function repositionStrategyFieldTooltip() {
  if (!strategyFieldTooltip || strategyFieldTooltip.hidden || !activeStrategyFieldTooltipTrigger) return;

  positionStrategyFieldTooltip(activeStrategyFieldTooltipTrigger, strategyFieldTooltip);
}

function injectStrategyFieldHints(form) {
  Object.entries(STRATEGY_FIELD_HINTS).forEach(([name, hint]) => {
    const control = form.elements[name];
    if (!control) return;

    const field = control.closest(".field");
    const label = field ? field.querySelector(".field__label") : null;
    if (!field || !label || label.querySelector(".strategy-field-help")) return;

    const helpElement = document.createElement("span");
    helpElement.className = "strategy-field-help";
    helpElement.textContent = "?";
    helpElement.setAttribute("role", "button");
    helpElement.setAttribute("tabindex", "0");
    helpElement.setAttribute("aria-label", hint);
    helpElement.setAttribute("data-tooltip", hint);
    helpElement.addEventListener("mouseenter", () => showStrategyFieldTooltip(helpElement));
    helpElement.addEventListener("focus", () => showStrategyFieldTooltip(helpElement));
    helpElement.addEventListener("mouseleave", hideStrategyFieldTooltip);
    helpElement.addEventListener("blur", hideStrategyFieldTooltip);
    label.appendChild(helpElement);
  });
}

function formatMoney(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "0";
  if (Math.abs(amount - Math.round(amount)) < 1e-9) return String(Math.round(amount));
  return amount.toFixed(2).replace(/\.?0+$/, "");
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
        <td colspan="12" class="spread-metric">暂无规则，请先新增策略规则</td>
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
          <td class="spread-metric">${escapeHtml(row.min_close_threshold_text || row.min_close_spread_rate_threshold_text || "--")}</td>
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
  const minNetFundingField = document.querySelector("[data-field-min-net-funding]");
  const spreadField = document.querySelector("[data-field-spread]");
  const openMaxSpreadField = document.querySelector("[data-field-open-max-spread]");
  const minCloseSpreadField = document.querySelector("[data-field-min-close-spread]");
  const fundingAdvancedSections = document.querySelectorAll("[data-funding-advanced]");
  const spreadAdvancedSections = document.querySelectorAll("[data-spread-advanced]");
  const spreadPositioningSections = document.querySelectorAll("[data-spread-positioning]");
  const confirmModal = document.querySelector("[data-strategy-confirm]");
  const confirmMessage = document.querySelector("[data-strategy-confirm-message]");
  const confirmAccept = document.querySelector("[data-strategy-confirm-accept]");
  const confirmCancelButtons = document.querySelectorAll("[data-strategy-confirm-cancel]");
  const title = document.getElementById("strategy-modal-title");
  const hiddenRuleId = form?.querySelector('input[name="rule_id"]');
  const submitButton = form?.querySelector('button[type="submit"]');
  const splitPreviewText = form?.querySelector("[data-spread-split-preview]");
  const spreadPositioningTitle = form?.querySelector("[data-spread-positioning-title]");
  const spreadPositioningDescription = form?.querySelector("[data-spread-positioning-description]");
  const copyTargets = {
    max_pairs: form?.querySelector('[data-copy-label="max_pairs"]'),
    order_amount_usdt: form?.querySelector('[data-copy-label="order_amount_usdt"]'),
    max_position_usdt: form?.querySelector('[data-copy-label="max_position_usdt"]'),
    order_interval_seconds: form?.querySelector('[data-copy-label="order_interval_seconds"]'),
  };

  if (!modal || !form || !openButton || !typeField || !annualizedField || !minNetFundingField || !spreadField || !openMaxSpreadField || !minCloseSpreadField || !title || !hiddenRuleId || !submitButton) {
    return;
  }

  injectStrategyFieldHints(form);

  let pendingDeleteResolver = null;

  const fundingAdvancedFieldNames = [
    "funding_open_window_start_minutes",
    "funding_open_window_end_minutes",
    "funding_settlement_skew_minutes",
    "funding_spread_resonance_min",
  ];

  const spreadAdvancedFieldNames = [
    "net_spread_threshold",
    "funding_carry_min",
    "max_funding_cost",
  ];

  const spreadRuntimeFieldNames = [
    "open_spread_rate_max_threshold",
    "drawdown_add_step_percent",
  ];

  const sharedAdvancedFieldNames = [
    "min_net_profit_threshold",
    "take_profit_threshold",
    "max_hold_minutes",
    "close_interval_seconds",
    "close_batch_count",
    "close_batch_ratio_percent",
    "single_leg_timeout_seconds",
  ];

  const setFieldValue = (name, value) => {
    if (!form.elements[name]) return;
    form.elements[name].value = Number(value || 0);
  };

  const resetFieldValues = (names) => {
    names.forEach((name) => setFieldValue(name, 0));
  };

  const buildNumericPayload = (formData, names) =>
    names.reduce((payload, name) => {
      payload[name] = Number(formData.get(name) || 0);
      return payload;
    }, {});

  const syncAdvancedSection = (sections, hidden) => {
    sections.forEach((section) => {
      section.classList.toggle("is-hidden", hidden);
      section.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = hidden;
      });
    });
  };

  const syncFieldCopy = (strategyType) => {
    const copyMap = STRATEGY_COPY_BY_TYPE[strategyType] || STRATEGY_COPY_BY_TYPE.funding;
    Object.entries(copyTargets).forEach(([key, element]) => {
      if (!element) return;
      element.textContent = copyMap[key] || "";
    });
    if (spreadPositioningTitle) {
      spreadPositioningTitle.textContent = "拆单与仓位";
    }
    if (spreadPositioningDescription) {
      spreadPositioningDescription.textContent = "面向资金费套利与价差套利的页面预演区。这里先按“每次开仓/加仓目标金额 + 实际子委托金额 + 间隔时间”推演拆单节奏，同时保留浮亏加仓和整体止盈入口。";
    }
  };

  const syncSpreadSplitPreview = () => {
    if (!splitPreviewText) return;
    const targetAmount = Number(form.elements.order_amount_usdt?.value || 0);
    const splitAmount = Number(form.elements.split_order_amount_usdt?.value || 0);
    const intervalSeconds = Number(form.elements.order_interval_seconds?.value || 0);
    const maxPosition = Number(form.elements.max_position_usdt?.value || 0);

    if (targetAmount <= 0) {
      splitPreviewText.textContent = "请先填写“每次开仓/加仓目标金额”，页面会按目标金额推演拆单节奏。";
      return;
    }

    if (splitAmount <= 0) {
      splitPreviewText.textContent = `当前目标金额是 ${formatMoney(targetAmount)}U。请再填写“实际子委托金额”，页面会估算需要拆成多少笔。`;
      return;
    }

    const estimatedBatches = Math.ceil(targetAmount / splitAmount);
    const coveredAmount = estimatedBatches * splitAmount;
    const intervalText = intervalSeconds > 0 ? `${intervalSeconds} 秒/笔` : "无额外间隔限制";
    const capText = maxPosition > 0 ? `，单交易对持仓上限 ${formatMoney(maxPosition)}U` : "";
    splitPreviewText.textContent = `页面预演：每次开仓/加仓目标 ${formatMoney(targetAmount)}U，按 ${formatMoney(splitAmount)}U/笔 拆分，预计约 ${estimatedBatches} 笔完成，覆盖约 ${formatMoney(coveredAmount)}U，节奏 ${intervalText}${capText}。`;
  };

  const syncBodyScrollLock = () => {
    const hasVisibleLayer = [modal, confirmModal].some((element) => element && !element.hidden);
    document.body.style.overflow = hasVisibleLayer ? "hidden" : "";
  };

  const modalDialog = modal.querySelector(".account-modal__dialog");

  const syncTypeFields = () => {
    hideStrategyFieldTooltip();

    const strategyType = String(typeField.value || "funding").trim();
    const isFunding = strategyType === "funding";
    syncFieldCopy(strategyType);

    annualizedField.classList.toggle("is-hidden", !isFunding);
    minNetFundingField.classList.toggle("is-hidden", !isFunding);
    spreadField.classList.toggle("is-hidden", isFunding);
    openMaxSpreadField.classList.toggle("is-hidden", isFunding);
    minCloseSpreadField.classList.toggle("is-hidden", isFunding);
    syncAdvancedSection(fundingAdvancedSections, !isFunding);
    syncAdvancedSection(spreadAdvancedSections, isFunding);
    syncAdvancedSection(spreadPositioningSections, false);

    form.elements.annualized_rate_threshold.disabled = !isFunding;
    form.elements.min_net_funding_rate_threshold.disabled = !isFunding;
    form.elements.spread_rate_threshold.disabled = isFunding;
    form.elements.open_spread_rate_max_threshold.disabled = isFunding;
    form.elements.min_close_spread_rate_threshold.disabled = isFunding;
    form.elements.drawdown_add_step_percent.disabled = isFunding;

    if (isFunding) {
      form.elements.spread_rate_threshold.value = 0;
      form.elements.open_spread_rate_max_threshold.value = 0;
      form.elements.min_close_spread_rate_threshold.value = 0;
      resetFieldValues(spreadAdvancedFieldNames);
      resetFieldValues(spreadRuntimeFieldNames);
    } else {
      form.elements.annualized_rate_threshold.value = 0;
      form.elements.min_net_funding_rate_threshold.value = 0;
      resetFieldValues(fundingAdvancedFieldNames);
    }

    syncSpreadSplitPreview();
  };

  const resetFormMode = () => {
    form.dataset.mode = "create";
    form.reset();
    hiddenRuleId.value = "";
    typeField.value = "funding";
    form.elements.annualized_rate_threshold.value = 0;
    form.elements.min_net_funding_rate_threshold.value = 0;
    form.elements.spread_rate_threshold.value = 0;
    form.elements.open_spread_rate_max_threshold.value = 0;
    form.elements.min_close_spread_rate_threshold.value = 0;
    form.elements.max_spread_rate_threshold.value = 0;
    form.elements.max_pairs.value = 1;
    form.elements.order_amount_usdt.value = 0;
    form.elements.max_position_usdt.value = 0;
    form.elements.order_interval_seconds.value = 0;
    resetFieldValues(fundingAdvancedFieldNames);
    resetFieldValues(spreadAdvancedFieldNames);
    form.elements.split_order_amount_usdt.value = 0;
    resetFieldValues(sharedAdvancedFieldNames);
    form.elements.is_enabled.checked = true;
    title.textContent = "新增规则";
    submitButton.textContent = "保存规则";
    syncTypeFields();
  };

  const openModal = () => {
    hideStrategyFieldTooltip();
    modal.hidden = false;
    syncBodyScrollLock();
    const firstInput = form.querySelector("input, select");
    if (firstInput) {
      window.setTimeout(() => firstInput.focus(), 20);
    }
  };

  const closeModal = () => {
    hideStrategyFieldTooltip();
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
    form.elements.min_net_funding_rate_threshold.value = Number(rule.min_net_funding_rate_threshold || 0);
    form.elements.spread_rate_threshold.value = Number(rule.spread_rate_threshold || 0);
    form.elements.open_spread_rate_max_threshold.value = Number(rule.open_spread_rate_max_threshold || 0);
    form.elements.min_close_spread_rate_threshold.value = Number(rule.min_close_spread_rate_threshold || 0);
    form.elements.max_spread_rate_threshold.value = Number(rule.max_spread_rate_threshold || 0);
    form.elements.max_pairs.value = Number(rule.max_pairs || 1);
    form.elements.order_amount_usdt.value = Number(rule.order_amount_usdt || 0);
    form.elements.max_position_usdt.value = Number(rule.max_position_usdt || 0);
    form.elements.order_interval_seconds.value = Number(rule.order_interval_seconds || 0);
    form.elements.split_order_amount_usdt.value = Number(rule.split_order_amount_usdt || 0);
    [...fundingAdvancedFieldNames, ...spreadAdvancedFieldNames, ...spreadRuntimeFieldNames, ...sharedAdvancedFieldNames].forEach((name) => {
      setFieldValue(name, rule[name]);
    });
    form.elements.is_enabled.checked = Boolean(rule.is_enabled);

    if (strategyType === "funding") {
      form.elements.spread_rate_threshold.value = 0;
      form.elements.open_spread_rate_max_threshold.value = 0;
      form.elements.min_close_spread_rate_threshold.value = 0;
      resetFieldValues(spreadAdvancedFieldNames);
      resetFieldValues(spreadRuntimeFieldNames);
    } else {
      form.elements.annualized_rate_threshold.value = 0;
      form.elements.min_net_funding_rate_threshold.value = 0;
      resetFieldValues(fundingAdvancedFieldNames);
    }

    title.textContent = "编辑规则";
    submitButton.textContent = "保存修改";
    syncTypeFields();
    syncSpreadSplitPreview();
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
  ["order_amount_usdt", "split_order_amount_usdt", "order_interval_seconds", "max_position_usdt"].forEach((name) => {
    const control = form.elements[name];
    if (!control) return;
    control.addEventListener("input", syncSpreadSplitPreview);
  });

  if (modalDialog) {
    modalDialog.addEventListener("scroll", hideStrategyFieldTooltip, { passive: true });
  }
  window.addEventListener("resize", repositionStrategyFieldTooltip);

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
      min_net_funding_rate_threshold: Number(formData.get("min_net_funding_rate_threshold") || 0),
      spread_rate_threshold: Number(formData.get("spread_rate_threshold") || 0),
      open_spread_rate_max_threshold: Number(formData.get("open_spread_rate_max_threshold") || 0),
      min_close_spread_rate_threshold: Number(formData.get("min_close_spread_rate_threshold") || 0),
      max_spread_rate_threshold: Number(formData.get("max_spread_rate_threshold") || 0),
      max_pairs: Number(formData.get("max_pairs") || 0),
      order_amount_usdt: Number(formData.get("order_amount_usdt") || 0),
      max_position_usdt: Number(formData.get("max_position_usdt") || 0),
      order_interval_seconds: Number(formData.get("order_interval_seconds") || 0),
      split_order_amount_usdt: Number(formData.get("split_order_amount_usdt") || 0),
      ...buildNumericPayload(formData, fundingAdvancedFieldNames),
      ...buildNumericPayload(formData, spreadAdvancedFieldNames),
      ...buildNumericPayload(formData, spreadRuntimeFieldNames),
      ...buildNumericPayload(formData, sharedAdvancedFieldNames),
      is_enabled: form.elements.is_enabled.checked,
    };

    if (payload.strategy_type === "funding") {
      payload.spread_rate_threshold = 0;
      payload.open_spread_rate_max_threshold = 0;
      payload.min_close_spread_rate_threshold = 0;
      spreadAdvancedFieldNames.forEach((name) => {
        payload[name] = 0;
      });
      payload.drawdown_add_step_percent = 0;
    }
    if (payload.strategy_type === "spread") {
      payload.annualized_rate_threshold = 0;
      payload.min_net_funding_rate_threshold = 0;
      fundingAdvancedFieldNames.forEach((name) => {
        payload[name] = 0;
      });

      const targetAmount = Number(payload.order_amount_usdt || 0);
      const splitAmount = Number(formData.get("split_order_amount_usdt") || 0);
      if (splitAmount > 0 && targetAmount > 0 && splitAmount > targetAmount) {
        showToast("价差套利的实际子委托金额不应大于每次开仓/加仓目标金额。");
        submitButton.disabled = false;
        return;
      }
    } else if (payload.strategy_type === "funding") {
      const targetAmount = Number(payload.order_amount_usdt || 0);
      const splitAmount = Number(formData.get("split_order_amount_usdt") || 0);
      if (splitAmount > 0 && targetAmount > 0 && splitAmount > targetAmount) {
        showToast("资金费套利的实际子委托金额不应大于每次开仓/加仓目标金额。");
        submitButton.disabled = false;
        return;
      }
    }

    const isEditMode = form.dataset.mode === "edit";
    const ruleId = String(formData.get("rule_id") || "").trim();
    const url = isEditMode && ruleId ? `/api/strategies/${ruleId}` : "/api/strategies";
    let closePositionsOnDisable = false;

    if (isEditMode && ruleId) {
      try {
        const currentDetail = await getJson(`/api/strategies/${ruleId}`);
        if (currentDetail?.success && currentDetail.rule) {
          const wasEnabled = Boolean(currentDetail.rule.is_enabled);
          const hasActivePositions = Boolean(currentDetail.has_active_positions);
          const willDisable = !Boolean(payload.is_enabled);
          if (wasEnabled && willDisable && hasActivePositions) {
            closePositionsOnDisable = window.confirm("这个规则当前还有套利持仓。是否在停用规则的同时，对该规则当前持仓全部发起平仓？");
          }
        }
      } catch (error) {
        // Keep default behavior if detail lookup fails.
      }
    }
    if (isEditMode) {
      payload.close_positions_on_disable = closePositionsOnDisable;
    }

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
