"""Shared builders for the split account repository implementation."""

from __future__ import annotations

from typing import Any, Dict

from app.domain.entities import (
    AccountAddress,
    AutoTransferConfig,
    ExchangeAccount,
    ExchangeAssetNetwork,
    StrategyRule,
    TransferRecord,
)


class AccountRepositoryBuildersMixin:
    def _build_account(self, row: Dict[str, Any]) -> ExchangeAccount:
        return ExchangeAccount(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            market_type=str(row["market_type"]),
            exchange_code=str(row["exchange_code"]),
            account_name=str(row["account_name"]),
            api_key=str(row["api_key"]),
            api_secret=str(row["api_secret"]),
            api_passphrase=str(row["api_passphrase"] or ""),
            connection_test_status=str(row.get("connection_test_status") or "untested"),
            funding_ratio_percent=float(row.get("funding_ratio_percent") or 0),
            current_available_amount=float(row.get("current_available_amount") or 0),
            current_available_synced_at=row.get("current_available_synced_at"),
            maker_fee_rate=float(row.get("maker_fee_rate") or 0.05),
            taker_fee_rate=float(row.get("taker_fee_rate") or 0.05),
            fee_rate_synced_at=row.get("fee_rate_synced_at"),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_address(self, row: Dict[str, Any]) -> AccountAddress:
        return AccountAddress(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            network=str(row["network"] or ""),
            address_value=str(row["address_value"] or ""),
            memo_tag=str(row["memo_tag"] or ""),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_transfer_record(self, row: Dict[str, Any]) -> TransferRecord:
        return TransferRecord(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            from_account_id=int(row["from_account_id"]),
            to_account_id=int(row["to_account_id"]),
            amount=float(row["amount"]),
            reason=str(row["reason"]),
            status=str(row["status"]),
            result=str(row["result"]),
            execute_status=str(row.get("execute_status") or "pending_execute"),
            result_status=str(row.get("result_status") or "none"),
            failure_type=str(row.get("failure_type") or ""),
            failure_reason=str(row.get("failure_reason") or ""),
            config_fingerprint=str(row.get("config_fingerprint") or ""),
            execution_checkpoint=str(row.get("execution_checkpoint") or ""),
            execution_reference=str(row.get("execution_reference") or ""),
            execution_payload=str(row.get("execution_payload") or ""),
            processed_at=row.get("processed_at"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_exchange_asset_network(self, row: Dict[str, Any]) -> ExchangeAssetNetwork:
        return ExchangeAssetNetwork(
            id=int(row["id"]),
            exchange_code=str(row["exchange_code"] or ""),
            asset_code=str(row["asset_code"] or ""),
            network_code=str(row["network_code"] or ""),
            network_name=str(row["network_name"] or ""),
            network_id=str(row["network_id"] or ""),
            is_deposit_enabled=bool(row.get("is_deposit_enabled")),
            is_withdraw_enabled=bool(row.get("is_withdraw_enabled")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_auto_transfer_config(self, row: Dict[str, Any]) -> AutoTransferConfig:
        return AutoTransferConfig(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            is_enabled=bool(row["is_enabled"]),
            trigger_ratio=float(row["trigger_ratio"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _build_strategy_rule(self, row: Dict[str, Any]) -> StrategyRule:
        return StrategyRule(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            name=str(row["name"]),
            strategy_type=str(row["strategy_type"]),
            annualized_rate_threshold=float(row.get("annualized_rate_threshold") or 0),
            min_net_funding_rate_threshold=float(row.get("min_net_funding_rate_threshold") or 0),
            spread_rate_threshold=float(row.get("spread_rate_threshold") or 0),
            min_close_spread_rate_threshold=float(row.get("min_close_spread_rate_threshold") or 0),
            max_spread_rate_threshold=float(row.get("max_spread_rate_threshold") or 0),
            max_pairs=int(row.get("max_pairs") or 0),
            order_amount_usdt=float(row.get("order_amount_usdt") or 0),
            max_position_usdt=float(row.get("max_position_usdt") or 0),
            order_interval_seconds=int(row.get("order_interval_seconds") or 0),
            funding_open_window_start_minutes=int(row.get("funding_open_window_start_minutes") or 0),
            funding_open_window_end_minutes=int(row.get("funding_open_window_end_minutes") or 0),
            funding_spread_resonance_min=float(row.get("funding_spread_resonance_min") or 0),
            net_spread_threshold=float(row.get("net_spread_threshold") or 0),
            funding_carry_min=float(row.get("funding_carry_min") or 0),
            max_funding_cost=float(row.get("max_funding_cost") or 0),
            min_net_profit_threshold=float(row.get("min_net_profit_threshold") or 0),
            take_profit_threshold=float(row.get("take_profit_threshold") or 0),
            max_hold_minutes=int(row.get("max_hold_minutes") or 0),
            close_interval_seconds=int(row.get("close_interval_seconds") or 0),
            close_batch_count=int(row.get("close_batch_count") or 0),
            single_leg_timeout_seconds=int(row.get("single_leg_timeout_seconds") or 0),
            is_enabled=bool(row.get("is_enabled")),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
