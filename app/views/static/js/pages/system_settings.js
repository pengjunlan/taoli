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

function renderRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return `
      <tr class="table-empty-row">
        <td colspan="10" class="spread-metric">暂无系统交易所配置</td>
      </tr>
    `;
  }

  return rows
    .map(
      (row) => `
        <tr>
          <td>${escapeHtml(row.exchange_label)}</td>
          <td><span class="pill pill--${escapeHtml(row.status_tone)}">${escapeHtml(row.status_label)}</span></td>
          <td class="spread-metric">${escapeHtml(row.mode_label)}</td>
          <td><span class="pill pill--${escapeHtml(row.config_tone)}">${escapeHtml(row.config_status)}</span></td>
          <td class="spread-metric">${escapeHtml(row.api_key)}</td>
          <td class="spread-metric">${escapeHtml(row.api_secret)}</td>
          <td class="spread-metric">${escapeHtml(row.api_passphrase)}</td>
          <td class="spread-metric">${escapeHtml(row.remark)}</td>
          <td class="spread-metric">${escapeHtml(row.updated_at)}</td>
          <td>
            <div class="account-actions">
              <button class="table-action" type="button" data-system-config-edit="${escapeHtml(row.exchange_code)}">配置</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

let latestRows = [];

async function refreshSystemConfigs() {
  const result = await getJson("/api/system-exchanges/list");
  if (!result.success) {
    throw new Error(result.message || "读取系统交易所配置失败。");
  }

  latestRows = Array.isArray(result.config_rows) ? result.config_rows : [];
  updateSummaryCards(result.summary_cards || []);

  const body = document.querySelector("[data-system-config-table-body]");
  const count = document.querySelector("[data-system-config-count]");
  if (body) {
    body.innerHTML = renderRows(latestRows);
  }
  if (count) {
    count.textContent = `共 ${Number(result.config_count || 0)} 个交易所`;
  }

  refreshListPagination(document);
}

function bindSystemConfigModal() {
  const modal = document.querySelector("[data-system-config-modal]");
  const form = document.querySelector("[data-system-config-form]");
  const closeButtons = document.querySelectorAll("[data-system-config-modal-close]");
  const publicApiCheckbox = document.querySelector("[data-system-public-api]");
  const privateFields = document.querySelectorAll("[data-system-private-field]");
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!modal || !form || !publicApiCheckbox || !submitButton) {
    return;
  }

  const syncPrivateFields = () => {
    const usePublicApi = Boolean(publicApiCheckbox.checked);
    privateFields.forEach((field) => {
      field.classList.toggle("is-hidden", usePublicApi);
      const input = field.querySelector("input");
      if (input) {
        input.disabled = usePublicApi;
      }
    });
  };

  const openModal = () => {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeModal = () => {
    modal.hidden = true;
    document.body.style.overflow = "";
    form.reset();
    syncPrivateFields();
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-system-config-edit]");
    if (!button) return;

    const exchangeCode = String(button.getAttribute("data-system-config-edit") || "").trim();
    button.disabled = true;
    try {
      const result = await getJson(`/api/system-exchanges/${exchangeCode}`);
      if (!result.success || !result.config) {
        showToast(result.message || "未找到该交易所配置。");
        return;
      }

      const row = result.config;
      form.elements.exchange_code.value = row.exchange_code || "";
      form.elements.exchange_label.value = row.exchange_label || "";
      form.elements.is_enabled.checked = Boolean(row.is_enabled);
      form.elements.use_public_api.checked = Boolean(row.use_public_api);
      form.elements.api_key.value = String(row.api_key || "");
      form.elements.api_secret.value = String(row.api_secret || "");
      form.elements.api_passphrase.value = String(row.api_passphrase || "");
      form.elements.remark.value = String(row.remark || "");

      syncPrivateFields();
      openModal();
    } catch (error) {
      showToast(error?.message || "读取系统交易所配置失败，请稍后再试。");
    } finally {
      button.disabled = false;
    }
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeModal);
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  publicApiCheckbox.addEventListener("change", syncPrivateFields);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;

    const formData = new FormData(form);
    const payload = {
      exchange_code: String(formData.get("exchange_code") || "").trim(),
      is_enabled: form.elements.is_enabled.checked,
      use_public_api: form.elements.use_public_api.checked,
      api_key: String(formData.get("api_key") || "").trim(),
      api_secret: String(formData.get("api_secret") || "").trim(),
      api_passphrase: String(formData.get("api_passphrase") || "").trim(),
      remark: String(formData.get("remark") || "").trim(),
    };

    try {
      const result = await postJson("/api/system-exchanges", payload);
      if (!result.success) {
        showToast(result.message || "保存系统交易所配置失败。");
        return;
      }

      await refreshSystemConfigs();
      showToast(result.message || "系统交易所配置已保存。");
      closeModal();
    } catch (error) {
      showToast(error?.message || "保存系统交易所配置失败，请稍后再试。");
    } finally {
      submitButton.disabled = false;
    }
  });

  syncPrivateFields();
}

bindPrototypeActions();
bindListPagination();
bindLogoutAction();
bindSystemConfigModal();
refreshSystemConfigs().catch((error) => {
  showToast(error?.message || "读取系统交易所配置失败，请稍后再试。");
});
