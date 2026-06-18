"""Unified visibility filter for opportunity rows by enabled system exchanges."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from app.application.services.system_exchange_config_service import EXCHANGE_LABELS, system_exchange_config_service


class OpportunityExchangeFilterService:
    def __init__(self) -> None:
        self._label_to_code = {
            str(label).strip().lower(): str(exchange_code).strip().lower()
            for exchange_code, label in EXCHANGE_LABELS.items()
        }

    def filter_rows(self, rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        enabled_exchange_codes = self._enabled_exchange_codes()
        filtered: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if self._is_visible(row=row, enabled_exchange_codes=enabled_exchange_codes):
                filtered.append(dict(row))
        return filtered

    def _enabled_exchange_codes(self) -> Set[str]:
        config_map = system_exchange_config_service.get_config_map()
        if not config_map:
            return set(EXCHANGE_LABELS.keys())
        return {
            str(exchange_code).strip().lower()
            for exchange_code, config in config_map.items()
            if bool(config.get("is_enabled"))
        }

    def _is_visible(self, *, row: Dict[str, Any], enabled_exchange_codes: Set[str]) -> bool:
        row_exchange_codes = self._extract_exchange_codes(row)
        if not row_exchange_codes:
            return True
        return all(exchange_code in enabled_exchange_codes for exchange_code in row_exchange_codes)

    def _extract_exchange_codes(self, row: Dict[str, Any]) -> Set[str]:
        exchange_codes: Set[str] = set()
        for key in (
            "left_exchange_code",
            "right_exchange_code",
            "open_exchange_code",
            "hedge_exchange_code",
            "long_exchange",
            "short_exchange",
            "buy_exchange",
            "sell_exchange",
            "open_exchange",
            "hedge_exchange",
        ):
            normalized = self._normalize_exchange_code(row.get(key))
            if normalized:
                exchange_codes.add(normalized)
        return exchange_codes

    def _normalize_exchange_code(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.lower()
        if normalized in EXCHANGE_LABELS:
            return normalized
        return self._label_to_code.get(normalized, "")


opportunity_exchange_filter_service = OpportunityExchangeFilterService()

