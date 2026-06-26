"""Confirm whether funding-fee settlement has been received for an execution."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.exchange_connection_service import exchange_connection_service
from app.application.services.strategy_risk_config import strategy_risk_config
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class FundingFeeReceiptService:
    def has_confirmed_or_gracefully_passed(
        self,
        *,
        execution_row: Dict[str, Any],
        settlement_ms: float,
    ) -> bool:
        execution_id = int(execution_row.get("id") or 0)
        if execution_id <= 0 or settlement_ms <= 0:
            return False

        if arbitrage_execution_repository.count_funding_fee_receipts_by_execution(execution_id=execution_id) >= 2:
            return True

        now_ms = datetime.now().timestamp() * 1000
        if now_ms <= settlement_ms:
            return False

        try:
            receipt_count = self._sync_receipts_for_execution(
                execution_row=execution_row,
                settlement_ms=settlement_ms,
            )
            if receipt_count >= 2:
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Funding fee receipt confirmation degraded: execution_id=%s detail=%s",
                execution_id,
                exc,
            )

        grace_seconds = max(0, int(strategy_risk_config.funding_receipt_confirm_grace_seconds or 0))
        if grace_seconds <= 0:
            return now_ms > settlement_ms
        return now_ms > settlement_ms + grace_seconds * 1000

    def _sync_receipts_for_execution(self, *, execution_row: Dict[str, Any], settlement_ms: float) -> int:
        source_legs = arbitrage_execution_repository.list_order_legs_by_execution(
            execution_id=int(execution_row.get("id") or 0),
        )
        if not source_legs:
            return 0

        confirmed_count = 0
        since_ms = max(0, int(settlement_ms) - 30 * 60 * 1000)
        for leg in source_legs:
            account_id = int(leg.get("exchange_account_id") or 0)
            user_id = int(execution_row.get("user_id") or 0)
            if account_id <= 0 or user_id <= 0:
                continue
            account_row = account_repository.get_active_account_with_address_by_id(account_id, user_id)
            if account_row is None:
                continue

            request = ExchangeConnectionTestRequest(
                account_id=account_id,
                market_type=str(account_row.get("market_type") or leg.get("market_type") or ""),
                exchange_code=str(account_row.get("exchange_code") or leg.get("exchange_code") or ""),
                api_key=str(account_row.get("api_key") or ""),
                api_secret=str(account_row.get("api_secret") or ""),
                api_passphrase=str(account_row.get("api_passphrase") or ""),
            )
            entries = exchange_connection_service.fetch_funding_fee_entries(
                request,
                symbol=str(leg.get("symbol") or ""),
                since_ms=since_ms,
                limit=50,
            )
            matched = [
                entry
                for entry in entries
                if abs(float(entry.timestamp_ms or 0) - float(settlement_ms or 0)) <= 45 * 60 * 1000
            ]
            if not matched:
                continue

            for entry in matched:
                settled_at = datetime.fromtimestamp(entry.timestamp_ms / 1000) if entry.timestamp_ms > 0 else None
                arbitrage_execution_repository.upsert_funding_fee_receipt(
                    execution_id=int(execution_row.get("id") or 0),
                    order_leg_id=int(leg.get("id") or 0) or None,
                    user_id=user_id,
                    exchange_account_id=account_id,
                    exchange_code=str(leg.get("exchange_code") or ""),
                    market_type=str(leg.get("market_type") or ""),
                    symbol=str(leg.get("symbol") or ""),
                    position_side=str(leg.get("position_side") or ""),
                    asset_code=entry.asset_code,
                    fee_amount=entry.amount,
                    exchange_record_id=entry.exchange_record_id,
                    settled_at=settled_at,
                    raw_payload=entry.raw_payload,
                )
            confirmed_count += 1

        if confirmed_count <= 0:
            confirmed_count = arbitrage_execution_repository.count_funding_fee_receipts_by_execution(
                execution_id=int(execution_row.get("id") or 0),
            )
        return confirmed_count


funding_fee_receipt_service = FundingFeeReceiptService()


__all__ = [
    "FundingFeeReceiptService",
    "funding_fee_receipt_service",
]
