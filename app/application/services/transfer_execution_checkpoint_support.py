"""Checkpoint and snapshot helpers for transfer execution."""

from __future__ import annotations

import json
from typing import Any, Dict

from app.application.services.account_support import (
    TRANSFER_EXECUTION_SNAPSHOT_CONTEXT_FIELDS,
    TRANSFER_EXECUTION_SNAPSHOT_PAYLOAD_KEY,
)
from app.infrastructure.persistence.account_repository import account_repository


class TransferExecutionCheckpointSupportMixin:
    def _store_execution_checkpoint(
        self,
        context: Dict[str, Any],
        *,
        execution_checkpoint: str,
        execution_reference: str = "",
        execution_payload: str = "",
    ) -> None:
        context["execution_checkpoint"] = execution_checkpoint
        if execution_reference:
            context["execution_reference"] = execution_reference
        if execution_payload:
            context["execution_payload"] = execution_payload
        record_id = int(context.get("id") or 0)
        if record_id > 0:
            account_repository.update_transfer_record_execution_checkpoint(
                record_id,
                execution_checkpoint=execution_checkpoint,
                execution_reference=str(context.get("execution_reference") or execution_reference),
                execution_payload=str(context.get("execution_payload") or execution_payload),
            )

    def _apply_execution_snapshot(self, context: Dict[str, Any]) -> None:
        payload = self._read_execution_payload_meta(context)
        snapshot = payload.get(TRANSFER_EXECUTION_SNAPSHOT_PAYLOAD_KEY)
        if not isinstance(snapshot, dict):
            return
        for field in TRANSFER_EXECUTION_SNAPSHOT_CONTEXT_FIELDS:
            value = snapshot.get(field)
            if value is None:
                continue
            context[field] = str(value).strip() if isinstance(value, str) else value

    def _serialize_execution_payload_meta(
        self,
        context: Dict[str, Any],
        *,
        target_credit_balance_before: float | None = None,
        target_credit_available_amount: float | None = None,
        target_credit_amount: float | None = None,
        target_internal_transfer_amount: float | None = None,
        requires_target_account_alignment: bool | None = None,
    ) -> str:
        payload = self._read_execution_payload_meta(context)
        if target_credit_balance_before is not None:
            payload["_target_credit_balance_before"] = float(target_credit_balance_before)
        if target_credit_available_amount is not None:
            payload["_target_credit_available_amount"] = float(target_credit_available_amount)
        if target_credit_amount is not None:
            payload["_target_credit_amount"] = float(target_credit_amount)
        if target_internal_transfer_amount is not None:
            payload["_target_internal_transfer_amount"] = float(target_internal_transfer_amount)
        if requires_target_account_alignment is not None:
            payload["_requires_target_account_alignment"] = bool(requires_target_account_alignment)
        text = json.dumps(payload, ensure_ascii=False, default=str) if payload else ""
        if text:
            context["execution_payload"] = text
        return text

    def _read_execution_payload_meta(self, context: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        raw_payload = context.get("execution_payload") or context.get("_withdraw_payload") or ""
        if not raw_payload:
            return payload
        try:
            parsed = json.loads(str(raw_payload))
        except Exception:
            return {"raw": str(raw_payload)}
        if isinstance(parsed, dict):
            payload.update(parsed)
        return payload

    def _read_target_credit_balance_before(self, context: Dict[str, Any]) -> float | None:
        value = self._read_execution_payload_meta(context).get("_target_credit_balance_before")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _read_target_credit_amount(self, context: Dict[str, Any]) -> float | None:
        value = self._read_execution_payload_meta(context).get("_target_credit_amount")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _read_target_internal_transfer_amount(self, context: Dict[str, Any]) -> float | None:
        value = self._read_execution_payload_meta(context).get("_target_internal_transfer_amount")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
