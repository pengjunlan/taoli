const DEFAULT_ACCOUNTS_RESULT = {
  summary_cards: [],
  account_rows: [],
  address_rows: [],
  balance_rows: [],
  account_count: 0,
  address_count: 0,
};

const DEFAULT_AUTO_TRANSFER_CONFIG = {
  is_enabled: false,
  trigger_ratio: 0.5,
};

let latestAccountsResult = { ...DEFAULT_ACCOUNTS_RESULT };
let latestAutoTransferConfig = { ...DEFAULT_AUTO_TRANSFER_CONFIG };

export function getLatestAccountsResult() {
  return latestAccountsResult;
}

export function setLatestAccountsResult(result) {
  latestAccountsResult = {
    ...DEFAULT_ACCOUNTS_RESULT,
    ...(result || {}),
  };
  return latestAccountsResult;
}

export function getLatestAutoTransferConfig() {
  return latestAutoTransferConfig;
}

export function setLatestAutoTransferConfig(config) {
  latestAutoTransferConfig = {
    is_enabled: Boolean(config?.is_enabled),
    trigger_ratio: Number(config?.trigger_ratio || 0.5),
  };
  return latestAutoTransferConfig;
}
