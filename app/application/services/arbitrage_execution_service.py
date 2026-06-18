"""Execute arbitrage order legs against exchange APIs."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, Iterable

from app.application.dto.requests.exchange_requests import ExchangeConnectionTestRequest
from app.application.services.arbitrage_execution_plan_service import arbitrage_execution_plan_service
from app.application.services.arbitrage_opportunity_monitor_service import arbitrage_opportunity_monitor_service
from app.application.services.arbitrage_runtime_support_service import arbitrage_runtime_support_service
from app.application.services.exchange_connection_service import exchange_connection_service
from app.application.services.monitor_center_service import monitor_center_service
from app.application.services.system_exchange_config_service import system_exchange_config_service
from app.infrastructure.persistence import arbitrage_execution_repository
from app.infrastructure.persistence.account_repository import account_repository


logger = logging.getLogger(__name__)


class ArbitrageExecutionService:
    def process_order_leg(self, order_leg: Dict[str, Any]) -> str:
        blocked_result = self._block_disabled_opening_flow(order_leg)
        if blocked_result is not None:
            execution_id = int(order_leg.get("execution_id") or 0)
            if execution_id > 0:
                self.reconcile_execution(execution_id=execution_id)
            return blocked_result

        status = str(order_leg.get("status") or "")
        execution_id = int(order_leg.get("execution_id") or 0)
        if status in {"pending", "created"}:
            result = self._submit_order(order_leg)
        elif status in {"submitting", "submitted", "partial"}:
            result = self._monitor_order(order_leg)
        else:
            result = status

        if execution_id > 0:
            self.reconcile_execution(execution_id=execution_id)
        return result

    def _block_disabled_opening_flow(self, order_leg: Dict[str, Any]) -> str | None:
        action = str(order_leg.get("action") or "").strip().lower()
        if action != "open":
            return None

        strategy_rule_id = int(order_leg.get("strategy_rule_id") or 0)
        user_id = int(order_leg.get("user_id") or 0)
        if strategy_rule_id > 0 and user_id > 0:
            strategy_rule = account_repository.get_strategy_rule_by_id(strategy_rule_id, user_id)
            if strategy_rule is None or not bool(strategy_rule.get("is_enabled")):
                arbitrage_execution_repository.update_order_leg_status(
                    order_leg_id=int(order_leg.get("id") or 0),
                    status="failed",
                    status_message="规则已停用，停止继续提交新的开仓订单",
                    closed_at=datetime.now(),
                )
                return "failed"

        exchange_code = str(order_leg.get("exchange_code") or "").strip().lower()
        exchange_config = system_exchange_config_service.get_config_map().get(exchange_code)
        if exchange_code and exchange_config is not None and not bool(exchange_config.get("is_enabled")):
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg.get("id") or 0),
                status="failed",
                status_message="交易所已被系统停用，停止继续提交新的开仓订单",
                closed_at=datetime.now(),
            )
            return "failed"
        return None

    def reconcile_execution(self, *, execution_id: int) -> str:
        execution_row = arbitrage_execution_repository.get_execution_by_id(execution_id)
        if execution_row is None:
            return "missing"

        order_legs = arbitrage_execution_repository.list_order_legs_by_execution(execution_id=execution_id)
        if not order_legs:
            return str(execution_row.get("status") or "pending")

        statuses = {str(leg.get("status") or "") for leg in order_legs}
        action = str(execution_row.get("action") or "open").strip().lower()

        if statuses.issubset({"pending", "created", "submitting", "submitted", "partial"}):
            next_status = "opening" if action == "open" else "closing"
            self._update_execution_status_if_changed(
                execution_id=execution_id,
                current_row=execution_row,
                status=next_status,
            )
            return next_status

        if "failed" in statuses:
            self._update_execution_status_if_changed(
                execution_id=execution_id,
                current_row=execution_row,
                status="failed",
            )
            self._handle_failed_execution(execution_row=execution_row, order_legs=order_legs)
            return "failed"

        if statuses == {"filled"}:
            next_status = "open" if action == "open" else "closed"
            self._update_execution_status_if_changed(
                execution_id=execution_id,
                current_row=execution_row,
                status=next_status,
            )
            if action == "close":
                self._mark_source_execution_closed(execution_row=execution_row)
            return next_status

        if "cancelled" in statuses and statuses.issubset({"cancelled", "filled"}):
            self._update_execution_status_if_changed(
                execution_id=execution_id,
                current_row=execution_row,
                status="failed",
            )
            self._handle_failed_execution(execution_row=execution_row, order_legs=order_legs)
            return "failed"

        next_status = "opening" if action == "open" else "closing"
        self._update_execution_status_if_changed(
            execution_id=execution_id,
            current_row=execution_row,
            status=next_status,
        )
        return next_status

    def _update_execution_status_if_changed(
        self,
        *,
        execution_id: int,
        current_row: Dict[str, Any],
        status: str,
    ) -> None:
        current_status = str(current_row.get("status") or "")
        if current_status == status:
            return
        arbitrage_execution_repository.update_execution_status(execution_id=execution_id, status=status)

    def _handle_failed_execution(
        self,
        *,
        execution_row: Dict[str, Any],
        order_legs: list[Dict[str, Any]],
    ) -> None:
        self._finalize_failed_execution_active_legs(order_legs)
        action = str(execution_row.get("action") or "open").strip().lower()
        if action == "close":
            self._handle_failed_close_execution(execution_row=execution_row, order_legs=order_legs)
            return

        if self._has_exposed_position(order_legs):
            scheduled = self._schedule_force_close(execution_row=execution_row)
            if scheduled:
                return

        if any(int(row.get("retry_count") or 0) >= 10 for row in order_legs):
            self._mark_cooldown(execution_row=execution_row)

    def _schedule_force_close(self, *, execution_row: Dict[str, Any]) -> bool:
        user_id = int(execution_row.get("user_id") or 0)
        strategy_rule_id = int(execution_row.get("strategy_rule_id") or 0)
        pair_key = str(execution_row.get("pair_key") or "")
        if user_id <= 0 or strategy_rule_id <= 0 or not pair_key:
            return False

        if arbitrage_execution_repository.has_open_close_execution(
            user_id=user_id,
            strategy_rule_id=strategy_rule_id,
            pair_key=pair_key,
        ):
            arbitrage_execution_repository.update_execution_status(
                execution_id=int(execution_row.get("id") or 0),
                status="closing",
            )
            return True

        result = arbitrage_execution_plan_service.create_close_execution(
            execution_row=execution_row,
            reason="开仓执行失败，触发强制平仓",
        )
        if result is None:
            self._mark_cooldown(execution_row=execution_row)
            return False

        arbitrage_execution_repository.update_execution_status(
            execution_id=int(execution_row.get("id") or 0),
            status="closing",
        )
        monitor_center_service.add_log(
            "arbitrage_execution_monitor",
            "warning",
            f"执行 #{execution_row.get('id')} 触发强制平仓，已生成平仓执行 #{result.execution_id}",
        )
        return True

    def _handle_failed_close_execution(
        self,
        *,
        execution_row: Dict[str, Any],
        order_legs: list[Dict[str, Any]],
    ) -> None:
        if any(int(row.get("retry_count") or 0) >= 10 for row in order_legs):
            self._mark_cooldown(execution_row=execution_row)
            self._restore_source_execution_to_open(execution_row=execution_row)
            return
        self._restore_source_execution_to_closing(execution_row=execution_row)

    def _restore_source_execution_to_open(self, *, execution_row: Dict[str, Any]) -> None:
        source_execution_id = int(execution_row.get("source_execution_id") or 0)
        if source_execution_id <= 0:
            return
        source_execution = arbitrage_execution_repository.get_execution_by_id(source_execution_id)
        if source_execution is None:
            return
        if str(source_execution.get("status") or "") == "closed":
            return
        arbitrage_execution_repository.update_execution_status(
            execution_id=source_execution_id,
            status="open",
        )

    def _restore_source_execution_to_closing(self, *, execution_row: Dict[str, Any]) -> None:
        source_execution_id = int(execution_row.get("source_execution_id") or 0)
        if source_execution_id <= 0:
            return
        source_execution = arbitrage_execution_repository.get_execution_by_id(source_execution_id)
        if source_execution is None:
            return
        if str(source_execution.get("status") or "") == "closed":
            return
        arbitrage_execution_repository.update_execution_status(
            execution_id=source_execution_id,
            status="closing",
        )

    def _has_exposed_position(self, order_legs: Iterable[Dict[str, Any]]) -> bool:
        for row in order_legs:
            if float(row.get("filled_quantity") or 0) > 0:
                return True
            quantity = arbitrage_execution_repository.get_position_quantity(
                exchange_account_id=int(row.get("exchange_account_id") or 0),
                market_type=str(row.get("market_type") or ""),
                symbol=str(row.get("symbol") or ""),
                position_side=str(row.get("position_side") or ""),
            )
            if quantity is not None and quantity > 0:
                return True
        return False

    def _mark_cooldown(self, *, execution_row: Dict[str, Any]) -> None:
        user_id = int(execution_row.get("user_id") or 0)
        pair_key = str(execution_row.get("pair_key") or "").strip()
        if user_id <= 0 or not pair_key:
            return
        arbitrage_opportunity_monitor_service.mark_pair_cooldown(
            user_id=user_id,
            pair_key=pair_key,
            seconds=3600,
        )
        monitor_center_service.add_log(
            "arbitrage_opportunity_monitor",
            "warning",
            f"组合 {pair_key} 进入 1 小时冷却",
        )

    def _mark_source_execution_closed(self, *, execution_row: Dict[str, Any]) -> None:
        source_execution_id = int(execution_row.get("source_execution_id") or 0)
        if source_execution_id <= 0:
            return
        source_execution = arbitrage_execution_repository.get_execution_by_id(source_execution_id)
        if source_execution is None:
            return
        if str(source_execution.get("status") or "") == "closed":
            return
        arbitrage_execution_repository.update_execution_status(
            execution_id=source_execution_id,
            status="closed",
        )

    def _submit_order(self, order_leg: Dict[str, Any]) -> str:
        account_row = account_repository.get_active_account_with_address_by_id(
            int(order_leg.get("exchange_account_id") or 0),
            int(order_leg.get("user_id") or 0),
        )
        if account_row is None:
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed",
                status_message="账户不存在，无法提交订单",
                closed_at=datetime.now(),
            )
            return "failed"

        requested_price = float(order_leg.get("requested_price") or 0)
        requested_quantity = float(order_leg.get("requested_quantity") or 0)
        if requested_price <= 0 or requested_quantity <= 0:
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed",
                status_message="订单价格或数量无效",
                closed_at=datetime.now(),
            )
            return "failed"

        if self._should_skip_close_leg(order_leg):
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="filled",
                status_message="本地已无剩余持仓，跳过该平仓腿",
                filled_quantity=0.0,
                filled_value_usdt=0.0,
                closed_at=datetime.now(),
            )
            return "filled"

        arbitrage_execution_repository.update_order_leg_status(
            order_leg_id=int(order_leg["id"]),
            status="submitting",
            status_message="准备提交订单",
            submitted_at=datetime.now(),
        )

        client_request = ExchangeConnectionTestRequest(
            account_id=int(account_row["id"]),
            market_type=str(account_row.get("market_type") or ""),
            exchange_code=str(account_row.get("exchange_code") or ""),
            api_key=str(account_row.get("api_key") or ""),
            api_secret=str(account_row.get("api_secret") or ""),
            api_passphrase=str(account_row.get("api_passphrase") or ""),
        )
        client = exchange_connection_service.build_exchange_client(client_request)
        try:
            order_params = self._build_order_params(
                client=client,
                request=client_request,
                order_leg=order_leg,
            )
            response = client.create_order(
                str(order_leg.get("symbol") or ""),
                "limit",
                str(order_leg.get("side") or "").lower(),
                requested_quantity,
                requested_price,
                order_params,
            )
            exchange_order_id = str((response or {}).get("id") or "")
            client_order_id = str((response or {}).get("clientOrderId") or "")
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="submitted",
                status_message="订单已提交，等待成交",
                exchange_order_id=exchange_order_id or None,
                client_order_id=client_order_id or None,
                acknowledged_at=datetime.now(),
            )
            return "submitted"
        except Exception as exc:  # noqa: BLE001
            retry_count = int(order_leg.get("retry_count") or 0) + 1
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed" if retry_count >= 10 else "pending",
                status_message=f"下单失败: {exc}",
                retry_count=retry_count,
                last_retry_at=datetime.now(),
                closed_at=datetime.now() if retry_count >= 10 else None,
            )
            return "failed" if retry_count >= 10 else "pending"
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _monitor_order(self, order_leg: Dict[str, Any]) -> str:
        account_row = account_repository.get_active_account_with_address_by_id(
            int(order_leg.get("exchange_account_id") or 0),
            int(order_leg.get("user_id") or 0),
        )
        if account_row is None:
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed",
                status_message="账户已失效或所属用户已停用，停止继续监控订单",
                closed_at=datetime.now(),
            )
            return "failed"

        client_request = ExchangeConnectionTestRequest(
            account_id=int(account_row["id"]),
            market_type=str(account_row.get("market_type") or ""),
            exchange_code=str(account_row.get("exchange_code") or ""),
            api_key=str(account_row.get("api_key") or ""),
            api_secret=str(account_row.get("api_secret") or ""),
            api_passphrase=str(account_row.get("api_passphrase") or ""),
        )
        client = exchange_connection_service.build_exchange_client(client_request)
        try:
            exchange_order_id = str(order_leg.get("exchange_order_id") or "").strip()
            if not exchange_order_id:
                return "pending"

            response = client.fetch_order(exchange_order_id, str(order_leg.get("symbol") or ""))
            normalized_status = self._normalize_order_status(str((response or {}).get("status") or ""))
            exchange_filled_quantity = float((response or {}).get("filled") or 0)
            average_fill_price = float((response or {}).get("average") or (response or {}).get("price") or 0)
            filled_quantity = arbitrage_runtime_support_service.to_base_quantity(
                exchange_code=str(order_leg.get("exchange_code") or ""),
                market_type=str(order_leg.get("market_type") or ""),
                symbol=str(order_leg.get("symbol") or ""),
                order_quantity=exchange_filled_quantity,
            )
            filled_value_usdt = (
                filled_quantity * average_fill_price
                if filled_quantity > 0 and average_fill_price > 0
                else 0.0
            )
            self._sync_incremental_fill_progress(
                order_leg=order_leg,
                cumulative_filled_quantity=filled_quantity,
                cumulative_order_quantity=exchange_filled_quantity,
                average_fill_price=average_fill_price,
            )

            if normalized_status == "filled":
                arbitrage_execution_repository.update_order_leg_status(
                    order_leg_id=int(order_leg["id"]),
                    status="filled",
                    status_message="订单已完全成交",
                    average_fill_price=average_fill_price,
                    filled_quantity=filled_quantity,
                    filled_value_usdt=filled_value_usdt,
                    closed_at=datetime.now(),
                )
                return "filled"

            if normalized_status == "partial":
                submitted_at = order_leg.get("submitted_at")
                if isinstance(submitted_at, datetime) and datetime.now() - submitted_at >= timedelta(seconds=5):
                    return self._retry_order(
                        client,
                        order_leg,
                        exchange_filled_quantity,
                        filled_quantity,
                        average_fill_price,
                        filled_value_usdt,
                    )
                arbitrage_execution_repository.update_order_leg_status(
                    order_leg_id=int(order_leg["id"]),
                    status="partial",
                    status_message="订单部分成交，继续等待",
                    average_fill_price=average_fill_price if average_fill_price > 0 else None,
                    filled_quantity=filled_quantity if filled_quantity > 0 else None,
                    filled_value_usdt=filled_value_usdt if filled_value_usdt > 0 else None,
                )
                return "partial"

            if normalized_status in {"open", "submitted"}:
                submitted_at = order_leg.get("submitted_at")
                if isinstance(submitted_at, datetime) and datetime.now() - submitted_at >= timedelta(seconds=5):
                    return self._retry_order(
                        client,
                        order_leg,
                        exchange_filled_quantity,
                        filled_quantity,
                        average_fill_price,
                        filled_value_usdt,
                    )
                return "submitted"

            if normalized_status == "cancelled":
                retry_count = int(order_leg.get("retry_count") or 0)
                if retry_count >= 10:
                    arbitrage_execution_repository.update_order_leg_status(
                        order_leg_id=int(order_leg["id"]),
                        status="failed",
                        status_message="撤单重挂超过 10 次",
                        closed_at=datetime.now(),
                    )
                    return "failed"
                arbitrage_execution_repository.update_order_leg_status(
                    order_leg_id=int(order_leg["id"]),
                    status="pending",
                    status_message="订单已撤销，准备重挂",
                )
                return "pending"

            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed",
                status_message=f"订单状态异常: {normalized_status}",
                closed_at=datetime.now(),
            )
            return "failed"
        except Exception:
            logger.debug("Monitor order degraded to submitted: leg_id=%s", order_leg.get("id"))
            return "submitted"
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _retry_order(
        self,
        client: Any,
        order_leg: Dict[str, Any],
        exchange_filled_quantity: float,
        filled_quantity: float,
        average_fill_price: float,
        filled_value_usdt: float,
    ) -> str:
        retry_count = int(order_leg.get("retry_count") or 0) + 1
        exchange_order_id = str(order_leg.get("exchange_order_id") or "").strip()
        if exchange_order_id:
            try:
                client.cancel_order(exchange_order_id, str(order_leg.get("symbol") or ""))
            except Exception:
                pass

        total_filled_base_quantity = max(float(order_leg.get("filled_quantity") or 0), filled_quantity)
        total_filled_order_quantity = self._to_order_quantity(
            order_leg=order_leg,
            base_quantity=total_filled_base_quantity,
            exchange_filled_quantity=exchange_filled_quantity,
        )
        if retry_count >= 10:
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(order_leg["id"]),
                status="failed",
                status_message="连续撤单重挂 10 次仍未成交",
                retry_count=retry_count,
                last_retry_at=datetime.now(),
                average_fill_price=average_fill_price if average_fill_price > 0 else None,
                filled_quantity=total_filled_base_quantity if total_filled_base_quantity > 0 else None,
                filled_value_usdt=filled_value_usdt if filled_value_usdt > 0 else None,
                closed_at=datetime.now(),
            )
            return "failed"

        latest_price = arbitrage_runtime_support_service.get_latest_price(
            exchange_code=str(order_leg.get("exchange_code") or ""),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            side=str(order_leg.get("side") or ""),
        )
        current_requested_quantity = float(order_leg.get("requested_quantity") or 0)
        remaining_quantity = max(0.0, current_requested_quantity - total_filled_order_quantity)
        next_requested_quantity = remaining_quantity if remaining_quantity > 0 else current_requested_quantity
        next_requested_price = latest_price if latest_price > 0 else float(order_leg.get("requested_price") or 0)
        next_requested_base_quantity = arbitrage_runtime_support_service.to_base_quantity(
            exchange_code=str(order_leg.get("exchange_code") or ""),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            order_quantity=next_requested_quantity,
        )
        next_requested_value = (
            next_requested_base_quantity * next_requested_price
            if next_requested_quantity > 0 and next_requested_price > 0
            else None
        )
        arbitrage_execution_repository.update_order_leg_status(
            order_leg_id=int(order_leg["id"]),
            status="pending",
            status_message="5 秒未完全成交，已撤单准备重挂",
            requested_price=next_requested_price if next_requested_price > 0 else None,
            requested_quantity=next_requested_quantity if next_requested_quantity > 0 else None,
            requested_value_usdt=next_requested_value,
            retry_count=retry_count,
            last_retry_at=datetime.now(),
            average_fill_price=average_fill_price if average_fill_price > 0 else None,
            filled_quantity=total_filled_base_quantity if total_filled_base_quantity > 0 else None,
            filled_value_usdt=filled_value_usdt if filled_value_usdt > 0 else None,
        )
        return "pending"

    def _sync_incremental_fill_progress(
        self,
        *,
        order_leg: Dict[str, Any],
        cumulative_filled_quantity: float,
        cumulative_order_quantity: float,
        average_fill_price: float,
    ) -> None:
        previous_filled_quantity = float(order_leg.get("filled_quantity") or 0)
        delta_filled_quantity = max(0.0, cumulative_filled_quantity - previous_filled_quantity)
        if delta_filled_quantity <= 0:
            return

        delta_order_quantity = self._to_order_quantity(
            order_leg=order_leg,
            base_quantity=delta_filled_quantity,
            exchange_filled_quantity=0.0,
        )
        delta_value_usdt = (
            delta_filled_quantity * average_fill_price
            if delta_filled_quantity > 0 and average_fill_price > 0
            else 0.0
        )
        fill_id = arbitrage_execution_repository.create_fill_record(
            execution_id=int(order_leg.get("execution_id") or 0),
            order_leg_id=int(order_leg.get("id") or 0),
            user_id=int(order_leg.get("user_id") or 0),
            exchange_account_id=int(order_leg.get("exchange_account_id") or 0) or None,
            exchange_code=str(order_leg.get("exchange_code") or ""),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            position_side=str(order_leg.get("position_side") or "net"),
            side=str(order_leg.get("side") or ""),
            fill_price=average_fill_price,
            fill_quantity=delta_filled_quantity,
            fill_value_usdt=delta_value_usdt,
            exchange_fill_id=None,
            filled_at=datetime.now(),
        )
        self._upsert_position_from_fill(
            order_leg,
            delta_filled_quantity,
            delta_order_quantity or cumulative_order_quantity,
            average_fill_price,
            delta_value_usdt,
            fill_id,
        )

    def _upsert_position_from_fill(
        self,
        order_leg: Dict[str, Any],
        filled_quantity: float,
        exchange_filled_quantity: float,
        average_fill_price: float,
        filled_value_usdt: float,
        fill_id: int,
    ) -> None:
        if filled_quantity <= 0:
            return

        position_side = str(order_leg.get("position_side") or "net")
        current_row = arbitrage_execution_repository.get_open_position(
            exchange_account_id=int(order_leg.get("exchange_account_id") or 0),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            position_side=position_side,
        )
        current_quantity = float((current_row or {}).get("quantity") or 0)
        current_avg_price = float((current_row or {}).get("avg_entry_price") or 0)
        current_realized_pnl = float((current_row or {}).get("realized_pnl_usdt") or 0)
        current_opened_by_execution_id = int((current_row or {}).get("opened_by_execution_id") or 0) or None
        is_buy = str(order_leg.get("side") or "").lower() == "buy"

        closing_quantity = 0.0
        opening_quantity = 0.0
        if position_side == "long":
            if is_buy:
                opening_quantity = filled_quantity
                new_quantity = current_quantity + filled_quantity
            else:
                closing_quantity = min(current_quantity, filled_quantity)
                new_quantity = max(0.0, current_quantity - filled_quantity)
        else:
            if is_buy:
                closing_quantity = min(current_quantity, filled_quantity)
                new_quantity = max(0.0, current_quantity - filled_quantity)
            else:
                opening_quantity = filled_quantity
                new_quantity = current_quantity + filled_quantity

        if new_quantity > 0 and opening_quantity > 0:
            total_cost = (current_quantity * current_avg_price) + (opening_quantity * average_fill_price)
            avg_entry_price = total_cost / new_quantity if new_quantity > 0 else average_fill_price
        elif new_quantity > 0:
            avg_entry_price = current_avg_price
        else:
            avg_entry_price = 0.0

        mark_price = average_fill_price if average_fill_price > 0 else avg_entry_price
        market_value_usdt = new_quantity * mark_price if new_quantity > 0 and mark_price > 0 else 0.0
        realized_pnl_delta = 0.0
        if current_quantity > 0 and closing_quantity > 0:
            if position_side == "long" and not is_buy:
                realized_pnl_delta = (average_fill_price - current_avg_price) * closing_quantity
            elif position_side == "short" and is_buy:
                realized_pnl_delta = (current_avg_price - average_fill_price) * closing_quantity
        realized_pnl_usdt = current_realized_pnl + realized_pnl_delta
        unrealized_pnl_usdt = 0.0
        if new_quantity > 0 and avg_entry_price > 0 and mark_price > 0:
            if position_side == "long":
                unrealized_pnl_usdt = (mark_price - avg_entry_price) * new_quantity
            else:
                unrealized_pnl_usdt = (avg_entry_price - mark_price) * new_quantity

        position_execution_id = current_opened_by_execution_id
        if position_execution_id is None:
            position_execution_id = int(order_leg.get("execution_id") or 0) or None

        arbitrage_execution_repository.upsert_position(
            user_id=int(order_leg.get("user_id") or 0),
            exchange_account_id=int(order_leg.get("exchange_account_id") or 0) or None,
            exchange_code=str(order_leg.get("exchange_code") or ""),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            base_asset=str(order_leg.get("symbol") or "").replace("/USDT", "").replace("USDT", ""),
            quote_asset="USDT",
            position_side=position_side,
            quantity=new_quantity,
            avg_entry_price=avg_entry_price,
            mark_price=mark_price,
            market_value_usdt=market_value_usdt if market_value_usdt > 0 else filled_value_usdt,
            realized_pnl_usdt=realized_pnl_usdt,
            unrealized_pnl_usdt=unrealized_pnl_usdt,
            opened_by_execution_id=position_execution_id,
            last_order_leg_id=int(order_leg.get("id") or 0) or None,
            last_fill_id=fill_id,
            status="open" if new_quantity > 0 else "closed",
            last_synced_at=datetime.now(),
        )

    def _build_order_params(
        self,
        *,
        client: Any,
        request: ExchangeConnectionTestRequest,
        order_leg: Dict[str, Any],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        market_type = str(order_leg.get("market_type") or "").strip().lower()
        if market_type != "swap":
            return params

        exchange_code = str(order_leg.get("exchange_code") or "").strip().lower()
        position_side = str(order_leg.get("position_side") or "").strip().lower()
        execution_action = str(order_leg.get("action") or "").strip().lower()

        position_mode = exchange_connection_service.get_position_mode(client, request)
        if position_mode == "hedge":
            mapped_position_side = self._map_position_side_for_exchange(
                exchange_code=exchange_code,
                position_side=position_side,
            )
            if mapped_position_side:
                params["positionSide"] = mapped_position_side

        if execution_action == "close" and not (exchange_code == "binance" and position_mode == "hedge"):
            params["reduceOnly"] = True
        return params

    def _should_skip_close_leg(self, order_leg: Dict[str, Any]) -> bool:
        execution_action = str(order_leg.get("action") or "").strip().lower()
        if execution_action != "close":
            return False
        position_row = arbitrage_execution_repository.get_open_position(
            exchange_account_id=int(order_leg.get("exchange_account_id") or 0),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            position_side=str(order_leg.get("position_side") or ""),
        )
        remaining_quantity = float((position_row or {}).get("quantity") or 0)
        return remaining_quantity <= 0

    def _finalize_failed_execution_active_legs(self, order_legs: Iterable[Dict[str, Any]]) -> None:
        active_statuses = {"pending", "created", "submitting", "submitted", "partial"}
        for row in order_legs:
            status = str(row.get("status") or "").strip().lower()
            if status not in active_statuses:
                continue
            exchange_order_id = str(row.get("exchange_order_id") or "").strip()
            if exchange_order_id:
                continue
            if self._should_skip_close_leg(row):
                arbitrage_execution_repository.update_order_leg_status(
                    order_leg_id=int(row.get("id") or 0),
                    status="filled",
                    status_message="关联执行失败，本地已无剩余持仓，结束该订单腿",
                    filled_quantity=0.0,
                    filled_value_usdt=0.0,
                    closed_at=datetime.now(),
                )
                continue
            arbitrage_execution_repository.update_order_leg_status(
                order_leg_id=int(row.get("id") or 0),
                status="failed",
                status_message="关联执行已失败，结束未真正提交的订单腿",
                closed_at=datetime.now(),
            )

    def _map_position_side_for_exchange(self, *, exchange_code: str, position_side: str) -> str:
        normalized_position_side = str(position_side or "").strip().lower()
        if exchange_code == "binance":
            if normalized_position_side == "long":
                return "LONG"
            if normalized_position_side == "short":
                return "SHORT"
        if normalized_position_side == "long":
            return "long"
        if normalized_position_side == "short":
            return "short"
        return ""

    def _to_order_quantity(
        self,
        *,
        order_leg: Dict[str, Any],
        base_quantity: float,
        exchange_filled_quantity: float,
    ) -> float:
        if exchange_filled_quantity > 0:
            return exchange_filled_quantity
        if base_quantity <= 0:
            return 0.0
        base_per_order_quantity = arbitrage_runtime_support_service.to_base_quantity(
            exchange_code=str(order_leg.get("exchange_code") or ""),
            market_type=str(order_leg.get("market_type") or ""),
            symbol=str(order_leg.get("symbol") or ""),
            order_quantity=1.0,
        )
        if base_per_order_quantity <= 0:
            return base_quantity
        return base_quantity / base_per_order_quantity

    def _normalize_order_status(self, status: str) -> str:
        normalized = str(status or "").strip().lower()
        mapping = {
            "open": "open",
            "closed": "filled",
            "filled": "filled",
            "canceled": "cancelled",
            "cancelled": "cancelled",
            "partially_filled": "partial",
            "partial": "partial",
            "new": "submitted",
        }
        return mapping.get(normalized, normalized or "submitted")


arbitrage_execution_service = ArbitrageExecutionService()
