"""Build per-page live payloads for websocket push."""

from __future__ import annotations

from typing import Dict

from app.application.services import account_service, opportunity_status_service, strategy_runtime_service


class LivePushService:
    def build_payload(
        self,
        *,
        channel: str,
        user_id: int,
        page: int = 1,
        page_size: int = 5,
        locked_keys: list[str] | None = None,
    ) -> Dict[str, object]:
        normalized_channel = str(channel or "").strip().lower()
        if normalized_channel == "funding":
            payload = opportunity_status_service.build_live_channel_payload(
                channel="funding",
                user_id=user_id,
                page=page,
                page_size=page_size,
                locked_keys=locked_keys,
            )
            return {"channel": "funding", "success": True, **payload}

        if normalized_channel == "spread":
            payload = opportunity_status_service.build_live_channel_payload(
                channel="spread",
                user_id=user_id,
                page=page,
                page_size=page_size,
                locked_keys=locked_keys,
            )
            return {"channel": "spread", "success": True, **payload}

        if normalized_channel == "accounts":
            account_rows = account_service.build_account_rows_for_user(user_id)
            auto_transfer_config = account_service.get_auto_transfer_config(user_id)
            balance_rows = account_service.build_balance_rows_from_accounts(account_rows, auto_transfer_config.trigger_ratio)
            address_rows = account_service.build_address_rows_for_user(user_id)
            summary_cards = account_service.build_summary_cards(
                account_rows,
                balance_rows,
                is_auto_transfer_enabled=auto_transfer_config.is_enabled,
            )
            return {
                "channel": "accounts",
                "success": True,
                "account_rows": account_rows,
                "address_rows": address_rows,
                "balance_rows": balance_rows,
                "summary_cards": summary_cards,
                "account_count": len(account_rows),
                "address_count": len(address_rows),
                "auto_transfer_config": {
                    "is_enabled": auto_transfer_config.is_enabled,
                    "trigger_ratio": auto_transfer_config.trigger_ratio,
                },
            }

        if normalized_channel == "strategy-runtime":
            payload = strategy_runtime_service.get_positions_orders_payload(user_id)
            return {
                "channel": "strategy-runtime",
                "success": True,
                **payload,
            }

        return {
            "channel": normalized_channel,
            "success": False,
            "message": "unsupported_channel",
        }


live_push_service = LivePushService()
