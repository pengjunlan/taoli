"""Exchange-specific transfer adapters used by the transfer orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


TRANSFER_ASSET_CODE = "USDT"

COMMON_NETWORK_ALIASES = {
    "trc20": "TRC20",
    "trx": "TRC20",
    "erc20": "ERC20",
    "eth": "ERC20",
    "bep20": "BEP20",
    "bsc": "BEP20",
    "arbitrum": "ARBITRUM",
    "arbone": "ARBITRUM",
    "arbitrumone": "ARBITRUM",
    "optimism": "OPTIMISM",
    "op": "OPTIMISM",
    "polygon": "MATIC",
    "matic": "MATIC",
    "plasma": "PLASMA",
    "xpl": "PLASMA",
    "solana": "SOL",
    "sol": "SOL",
    "omni": "OMNI",
    "xtz": "XTZ",
    "tezos": "XTZ",
}


def network_alias_key(network_code: str) -> str:
    return str(network_code or "").strip().replace("_", "").replace("-", "").replace(" ", "").lower()


def normalize_network_code(network_code: str) -> str:
    normalized = str(network_code or "").strip()
    if not normalized:
        return ""
    if normalized.upper().startswith(f"{TRANSFER_ASSET_CODE}-"):
        normalized = normalized.split("-", 1)[1]
    alias_key = network_alias_key(normalized)
    return COMMON_NETWORK_ALIASES.get(alias_key, normalized.upper())


@dataclass(frozen=True)
class DepositDestination:
    address: str
    tag: str | None
    network_code: str


@dataclass(frozen=True)
class ExchangeTransferAdapter:
    code: str
    internal_account_by_market: Dict[str, str]
    withdraw_account: str
    transfer_client_market_type: str = "spot"
    withdraw_account_market_type: str = "spot"
    withdraw_network_aliases: Dict[str, str] | None = None
    balance_type_by_market: Dict[str, str] | None = None

    def map_internal_account(self, market_type: str) -> str:
        return str(self.internal_account_by_market.get(str(market_type or "").strip().lower()) or "")

    def resolve_withdraw_network_code(self, network_code: str) -> str:
        normalized = normalize_network_code(network_code)
        exchange_aliases = self.withdraw_network_aliases or {}
        return str(exchange_aliases.get(normalized, normalized) or normalized)

    def build_withdraw_params(self, network_code: str, fee: float | None = None) -> Dict[str, Any]:
        return {"network": self.resolve_withdraw_network_code(network_code)}

    def build_balance_params(self, market_type: str) -> Dict[str, Any] | None:
        balance_type = str((self.balance_type_by_market or {}).get(str(market_type or "").strip().lower()) or "").strip()
        if not balance_type:
            return None
        return {"type": balance_type}

    def fetch_deposit_address(self, client: Any, network_code: str) -> Dict[str, Any] | None:
        resolved_network = self.resolve_withdraw_network_code(network_code)
        return client.fetch_deposit_address(TRANSFER_ASSET_CODE, {"network": resolved_network})

    def normalize_destination_network_code(self, network_code: str) -> str:
        return normalize_network_code(network_code)

    def resolve_deposit_destination(
        self,
        *,
        deposit: Dict[str, Any] | None,
        fallback_network: str,
        fallback_address: str,
        fallback_memo: str,
    ) -> DepositDestination:
        target_network_code = self.normalize_destination_network_code(fallback_network)
        if deposit is not None:
            self.validate_deposit_payload(deposit)
            return DepositDestination(
                address=str(deposit.get("address") or fallback_address).strip(),
                tag=str(deposit.get("tag") or fallback_memo or "").strip() or None,
                network_code=(
                    self.normalize_destination_network_code(str(deposit.get("network") or "").strip())
                    or target_network_code
                ),
            )

        return DepositDestination(
            address=str(fallback_address or "").strip(),
            tag=str(fallback_memo or "").strip() or None,
            network_code=target_network_code,
        )

    def validate_deposit_payload(self, deposit: Dict[str, Any]) -> None:
        return None


class BinanceTransferAdapter(ExchangeTransferAdapter):
    def build_withdraw_params(self, network_code: str, fee: float | None = None) -> Dict[str, Any]:
        params = super().build_withdraw_params(network_code, fee)
        params["walletType"] = 0
        return params


class OKXTransferAdapter(ExchangeTransferAdapter):
    def build_withdraw_params(self, network_code: str, fee: float | None = None) -> Dict[str, Any]:
        normalized_fee = max(float(fee or 0), 0.0)
        fee_text = format(normalized_fee, ".12f").rstrip("0").rstrip(".") or "0"
        return {
            "network": self.resolve_withdraw_network_code(network_code),
            "fee": fee_text,
        }

    def validate_deposit_payload(self, deposit: Dict[str, Any]) -> None:
        info = deposit.get("info") if isinstance(deposit, dict) else None
        to_account = str(info.get("to") or "") if isinstance(info, dict) else ""
        if to_account and to_account not in {"6", "18"}:
            raise ValueError(f"OKX 充值地址目标账户类型异常: {to_account}")


class ExchangeTransferRegistry:
    def __init__(self) -> None:
        self._adapters: Dict[str, ExchangeTransferAdapter] = {}

    def register(self, adapter: ExchangeTransferAdapter) -> None:
        self._adapters[adapter.code] = adapter

    def get(self, exchange_code: str) -> ExchangeTransferAdapter | None:
        return self._adapters.get(str(exchange_code or "").strip().lower())

    def is_supported(self, exchange_code: str) -> bool:
        return self.get(exchange_code) is not None

    def supported_exchange_codes(self) -> set[str]:
        return set(self._adapters.keys())


exchange_transfer_registry = ExchangeTransferRegistry()
exchange_transfer_registry.register(
    BinanceTransferAdapter(
        code="binance",
        internal_account_by_market={
            "spot": "spot",
            "swap": "linear",
        },
        withdraw_account="spot",
        transfer_client_market_type="spot",
        withdraw_account_market_type="spot",
        withdraw_network_aliases={
            "TRC20": "TRC20",
            "ERC20": "ERC20",
            "BEP20": "BEP20",
            "ARBITRUM": "ARBITRUM",
            "OPTIMISM": "OPTIMISM",
            "MATIC": "MATIC",
            "PLASMA": "PLASMA",
            "SOL": "SOL",
            "OMNI": "OMNI",
        },
        balance_type_by_market={
            "spot": "spot",
            "swap": "swap",
        },
    )
)
exchange_transfer_registry.register(
    ExchangeTransferAdapter(
        code="gate",
        internal_account_by_market={
            "spot": "spot",
            "swap": "swap",
        },
        withdraw_account="funding",
        transfer_client_market_type="spot",
        withdraw_account_market_type="spot",
        withdraw_network_aliases={
            "TRC20": "TRC20",
            "ERC20": "ERC20",
            "BEP20": "BEP20",
            "ARBITRUM": "ARBONE",
            "OPTIMISM": "OP",
            "MATIC": "MATIC",
            "PLASMA": "XPL",
            "SOL": "SOL",
            "OMNI": "OMNI",
        },
        balance_type_by_market={
            "spot": "funding",
            "swap": "swap",
        },
    )
)
exchange_transfer_registry.register(
    ExchangeTransferAdapter(
        code="bitget",
        internal_account_by_market={
            "spot": "spot",
            "swap": "swap",
        },
        withdraw_account="spot",
        transfer_client_market_type="spot",
        withdraw_account_market_type="spot",
        withdraw_network_aliases={
            "TRC20": "TRC20",
            "ERC20": "ERC20",
            "BEP20": "BEP20",
            "ARBITRUM": "ARBITRUM",
            "OPTIMISM": "OPTIMISM",
            "MATIC": "MATIC",
            "PLASMA": "PLASMA",
            "SOL": "SOL",
            "OMNI": "OMNI",
        },
        balance_type_by_market={
            "spot": "spot",
            "swap": "swap",
        },
    )
)
exchange_transfer_registry.register(
    OKXTransferAdapter(
        code="okx",
        internal_account_by_market={
            "spot": "funding",
            "swap": "trading",
        },
        withdraw_account="funding",
        transfer_client_market_type="spot",
        withdraw_account_market_type="spot",
        withdraw_network_aliases={
            "TRC20": "TRC20",
            "ERC20": "ERC20",
            "BEP20": "BSC",
            "ARBITRUM": "Arbitrum One",
            "OPTIMISM": "Optimism",
            "MATIC": "Polygon",
            "PLASMA": "Plasma",
            "SOL": "Solana",
            "OMNI": "OMNI",
            "XTZ": "Tezos",
        },
        balance_type_by_market={
            "spot": "funding",
            "swap": "trading",
        },
    )
)
