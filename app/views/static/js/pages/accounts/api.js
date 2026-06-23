import { postJson } from "../../core/utils.js";

export async function getJson(url) {
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

export function fetchAccountsList() {
  return getJson("/api/accounts/list");
}

export function fetchAutoTransferConfig() {
  return getJson("/api/accounts/auto-transfer-config");
}

export function updateAutoTransferConfig(payload) {
  return postJson("/api/accounts/auto-transfer-config", payload);
}

export function unlockAutoTransferAccount(accountId) {
  return postJson(`/api/accounts/${accountId}/auto-transfer-unlock`);
}

export function fetchAccountDetail(accountId) {
  return getJson(`/api/accounts/${accountId}`);
}

export function fetchExchangeNetworkOptions(exchangeCode) {
  return getJson(`/api/accounts/exchanges/${encodeURIComponent(String(exchangeCode || "").trim())}/networks`);
}

export function createTransferRecord(payload) {
  return postJson("/api/accounts/transfer", payload);
}

export function fetchTransferOptions(accountId) {
  return getJson(`/api/accounts/${accountId}/transfer-options`);
}

export function updateFundingRatio(accountId, payload) {
  return postJson(`/api/accounts/${accountId}/funding-ratio`, payload);
}

export function testAccountConnection(payload) {
  return postJson("/api/accounts/test-connection", payload);
}

export function createAccount(payload) {
  return postJson("/api/accounts", payload);
}

export function updateAccount(accountId, payload) {
  return postJson(`/api/accounts/${accountId}`, payload);
}

export function deleteAccount(accountId) {
  return postJson(`/api/accounts/${accountId}/delete`);
}
