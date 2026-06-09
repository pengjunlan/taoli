"""Background account balance monitor."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import List

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.exchange_connection_service import exchange_connection_service
from app.domain.entities.monitor_models import AccountSnapshot, ServiceHeartbeat
from app.infrastructure.cache import AccountBalanceCacheItem, account_balance_cache
from app.infrastructure.persistence.account_repository import account_repository
from app.shared.exceptions import ExchangeError


logger = logging.getLogger(__name__)


class AccountMonitorService:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._interval_seconds = 30
        self._last_status = "idle"
        self._last_detail = "waiting for startup"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._prime_cache_from_database()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="account-balance-monitor",
                daemon=True,
            )
            self._thread.start()

    def heartbeat(self) -> ServiceHeartbeat:
        return ServiceHeartbeat(
            name="account_monitor",
            status=self._last_status,
            detail=self._last_detail,
        )

    def collect_account_snapshots(self) -> List[AccountSnapshot]:
        return []

    def get_cached_amount(self, account_id: int, fallback_amount: float = 0.0) -> float:
        item = account_balance_cache.get(account_id)
        if item is None:
            return fallback_amount
        return float(item.amount)

    def get_cached_synced_at(self, account_id: int):
        item = account_balance_cache.get(account_id)
        if item is None:
            return None
        return item.synced_at

    def remove_account(self, account_id: int) -> None:
        account_balance_cache.delete(account_id)

    def seed_account(self, account_id: int, amount: float, synced_at) -> None:
        account_balance_cache.set(
            AccountBalanceCacheItem(
                account_id=account_id,
                amount=float(amount or 0),
                synced_at=synced_at,
            )
        )

    def _prime_cache_from_database(self) -> None:
        rows = account_repository.list_all_accounts_with_address()
        account_balance_cache.prime(
            AccountBalanceCacheItem(
                account_id=int(row["id"]),
                amount=float(row.get("current_available_amount") or 0),
                synced_at=row.get("current_available_synced_at"),
            )
            for row in rows
        )
        self._last_status = "primed"
        self._last_detail = f"loaded {len(rows)} account balances from database"

    def _run_loop(self) -> None:
        while True:
            try:
                self._refresh_all_accounts()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Account balance monitor loop failed: %s", exc)
                self._last_status = "error"
                self._last_detail = str(exc)
            time.sleep(self._interval_seconds)

    def _refresh_all_accounts(self) -> None:
        rows = account_repository.list_all_accounts_with_address()
        refreshed_count = 0
        skipped_count = 0

        for row in rows:
            account_id = int(row["id"])
            connection_test_status = str(row.get("connection_test_status") or "untested").strip().lower()
            if connection_test_status != "success":
                skipped_count += 1
                continue

            try:
                amount = exchange_connection_service.fetch_available_balance(
                    ExchangeConnectionTestRequest(
                        account_id=account_id,
                        market_type=str(row.get("market_type") or ""),
                        exchange_code=str(row.get("exchange_code") or ""),
                        api_key=str(row.get("api_key") or ""),
                        api_secret=str(row.get("api_secret") or ""),
                        api_passphrase=str(row.get("api_passphrase") or ""),
                    )
                )
            except ExchangeError as exc:
                logger.warning("Refresh balance failed for account_id=%s: %s", account_id, exc)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Refresh balance failed unexpectedly for account_id=%s: %s", account_id, exc)
                continue

            cached_item = account_balance_cache.get(account_id)
            normalized_amount = round(float(amount or 0), 8)
            if cached_item is not None and round(float(cached_item.amount or 0), 8) == normalized_amount:
                continue

            synced_at = datetime.now()
            account_balance_cache.set(
                AccountBalanceCacheItem(
                    account_id=account_id,
                    amount=normalized_amount,
                    synced_at=synced_at,
                )
            )
            account_repository.update_current_available_amount(
                account_id=account_id,
                amount=normalized_amount,
                synced_at=synced_at,
            )
            refreshed_count += 1

        self._last_status = "running"
        self._last_detail = (
            f"refreshed {refreshed_count} accounts, skipped {skipped_count} untested/failed accounts"
        )


account_monitor_service = AccountMonitorService()
