"""Background account balance monitor."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import List

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.exchange_connection_service import exchange_connection_service
from app.application.services.monitor_center_service import monitor_center_service
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
        self._monitor_key = "account_balance_sync"

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            monitor_center_service.register_worker(
                key=self._monitor_key,
                name="账户余额同步线程",
                category="账户监控",
                thread_name="account-balance-monitor",
                interval_seconds=self._interval_seconds,
                status="starting",
                detail="准备加载数据库余额缓存。",
            )
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

    def get_cached_amount(self, account_id: int, fallback_amount: float = 0.0, *, user_id: int | None = None) -> float:
        item = account_balance_cache.get(account_id, user_id=user_id)
        if item is None:
            return fallback_amount
        return float(item.amount)

    def get_cached_synced_at(self, account_id: int, *, user_id: int | None = None):
        item = account_balance_cache.get(account_id, user_id=user_id)
        if item is None:
            return None
        return item.synced_at

    def get_cached_balance(self, account_id: int, *, user_id: int | None = None) -> AccountBalanceCacheItem | None:
        return account_balance_cache.get(account_id, user_id=user_id)

    def remove_account(self, account_id: int, *, user_id: int | None = None) -> None:
        account_balance_cache.delete(account_id, user_id=user_id)

    def seed_account(
        self,
        account_id: int,
        amount: float,
        synced_at,
        *,
        user_id: int = 0,
        exchange_code: str = "",
        market_type: str = "",
        frozen_amount: float = 0.0,
        total_amount: float | None = None,
    ) -> None:
        resolved_total_amount = (
            float(total_amount)
            if total_amount is not None
            else max(float(amount or 0) + float(frozen_amount or 0), 0.0)
        )
        account_balance_cache.set(
            AccountBalanceCacheItem(
                account_id=account_id,
                user_id=int(user_id or 0),
                exchange_code=str(exchange_code or ""),
                market_type=str(market_type or ""),
                amount=float(amount or 0),
                frozen_amount=float(frozen_amount or 0),
                total_amount=resolved_total_amount,
                synced_at=synced_at,
            )
        )

    def _prime_cache_from_database(self) -> None:
        rows = account_repository.list_all_accounts_with_address()
        account_balance_cache.prime(
            AccountBalanceCacheItem(
                account_id=int(row["id"]),
                user_id=int(row.get("user_id") or 0),
                exchange_code=str(row.get("exchange_code") or ""),
                market_type=str(row.get("market_type") or ""),
                amount=float(row.get("current_available_amount") or 0),
                frozen_amount=0.0,
                total_amount=float(row.get("current_available_amount") or 0),
                synced_at=row.get("current_available_synced_at"),
            )
            for row in rows
        )
        self._last_status = "primed"
        self._last_detail = f"loaded {len(rows)} account balances from database"
        monitor_center_service.mark_success(
            self._monitor_key,
            f"已从数据库加载 {len(rows)} 个账户余额缓存。",
        )

    def _run_loop(self) -> None:
        while True:
            try:
                monitor_center_service.heartbeat(
                    self._monitor_key,
                    status="running",
                    detail="线程心跳正常，准备刷新账户余额。",
                )
                self._refresh_all_accounts()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Account balance monitor loop failed: %s", exc)
                self._last_status = "error"
                self._last_detail = str(exc)
                monitor_center_service.mark_error(self._monitor_key, f"账户余额同步线程异常：{exc}")
            time.sleep(self._interval_seconds)

    def _refresh_all_accounts(self) -> None:
        rows = account_repository.list_all_accounts_with_address()
        refreshed_count = 0
        skipped_count = 0

        for row in rows:
            account_id = int(row["id"])
            user_id = int(row.get("user_id") or 0)
            api_key = str(row.get("api_key") or "").strip()
            api_secret = str(row.get("api_secret") or "").strip()
            if not api_key or not api_secret:
                skipped_count += 1
                continue

            try:
                snapshot = exchange_connection_service.fetch_balance_snapshot(
                    ExchangeConnectionTestRequest(
                        account_id=account_id,
                        market_type=str(row.get("market_type") or ""),
                        exchange_code=str(row.get("exchange_code") or ""),
                        api_key=api_key,
                        api_secret=api_secret,
                        api_passphrase=str(row.get("api_passphrase") or ""),
                    )
                )
            except ExchangeError as exc:
                logger.warning("Refresh balance failed for account_id=%s: %s", account_id, exc)
                monitor_center_service.add_log(
                    self._monitor_key,
                    "warning",
                    f"账户 {account_id} 余额刷新失败：{exc}",
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Refresh balance failed unexpectedly for account_id=%s: %s", account_id, exc)
                monitor_center_service.add_log(
                    self._monitor_key,
                    "warning",
                    f"账户 {account_id} 余额刷新异常：{exc}",
                )
                continue

            normalized_amount = round(float(snapshot.available_amount or 0), 8)
            normalized_frozen_amount = round(float(snapshot.frozen_amount or 0), 8)
            normalized_total_amount = round(float(snapshot.total_amount or 0), 8)
            synced_at = datetime.now()
            account_balance_cache.set(
                AccountBalanceCacheItem(
                    account_id=account_id,
                    user_id=user_id,
                    exchange_code=str(row.get("exchange_code") or ""),
                    market_type=str(row.get("market_type") or ""),
                    amount=normalized_amount,
                    frozen_amount=normalized_frozen_amount,
                    total_amount=normalized_total_amount,
                    synced_at=synced_at,
                )
            )
            account_repository.update_current_available_amount(
                account_id=account_id,
                amount=normalized_amount,
                synced_at=synced_at,
            )
            if str(row.get("connection_test_status") or "untested").strip().lower() != "success":
                account_repository.update_connection_test_status(
                    account_id=account_id,
                    user_id=user_id,
                    status="success",
                )
            refreshed_count += 1
            monitor_center_service.add_log(
                self._monitor_key,
                "info",
                f"账户 {account_id} 当前可用已更新为 {normalized_amount}",
            )

        self._last_status = "running"
        self._last_detail = f"refreshed {refreshed_count} accounts, skipped {skipped_count} incomplete accounts"
        monitor_center_service.mark_success(
            self._monitor_key,
            f"本轮完成：更新 {refreshed_count} 个账户，跳过 {skipped_count} 个配置不完整账户",
        )


account_monitor_service = AccountMonitorService()
