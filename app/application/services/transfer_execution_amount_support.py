"""Amount and transfer-reference helpers for transfer execution."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict


class TransferExecutionAmountSupportMixin:
    def _resolve_target_internal_transfer_amount(
        self,
        *,
        requested_amount: float,
        current_available_amount: float,
        credited_amount: float | None = None,
        planned_amount: float | None = None,
    ) -> float:
        candidate_amounts = [
            max(float(requested_amount or 0), 0.0),
            max(float(current_available_amount or 0), 0.0),
        ]
        if credited_amount is not None:
            candidate_amounts.append(max(float(credited_amount or 0), 0.0))
        if planned_amount is not None:
            candidate_amounts.append(max(float(planned_amount or 0), 0.0))
        return self._quantize_transfer_amount(min(candidate_amounts)) if candidate_amounts else 0.0

    def _quantize_transfer_amount(self, amount: float, precision: int = 8) -> float:
        normalized = max(float(amount or 0), 0.0)
        if normalized <= 0:
            return 0.0
        quantizer = Decimal("1").scaleb(-precision)
        quantized = Decimal(str(normalized)).quantize(quantizer, rounding=ROUND_DOWN)
        return float(quantized) if quantized > 0 else 0.0

    def _extract_transfer_reference(self, response: Dict[str, Any] | None) -> str:
        if not isinstance(response, dict):
            return "--"
        for key in ("id", "txid", "txId", "wdId", "transId", "tranId"):
            value = response.get(key)
            if value:
                return str(value)
        info = response.get("info")
        if isinstance(info, dict):
            for key in ("id", "txId", "wdId", "transId", "tranId"):
                value = info.get(key)
                if value:
                    return str(value)
        return "--"
