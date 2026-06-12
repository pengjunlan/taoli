"""Transfer planning logic for accounts."""

from __future__ import annotations

from typing import Dict, List, Optional

from app.application.services.account_support import AccountServiceSupport


class AccountTransferPlanningService(AccountServiceSupport):
    def list_auto_transfer_candidates(
        self,
        balance_rows: List[Dict[str, str]],
        trigger_ratio: float,
    ) -> List[Dict[str, float | int | str]]:
        normalized_rows: List[Dict[str, float | str]] = []
        for row in balance_rows:
            available_value = self._parse_amount(str(row.get("available") or "$0"))
            target_value = self._parse_amount(str(row.get("target") or "$0"))
            deviation_value = available_value - target_value
            normalized_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "name": str(row.get("name") or "--"),
                    "available_value": float(available_value),
                    "target_value": float(target_value),
                    "deviation_value": float(deviation_value),
                }
            )

        demand_rows = [
            row for row in normalized_rows
            if float(row["target_value"]) > 0 and float(row["available_value"]) < float(row["target_value"]) * trigger_ratio
        ]
        if not demand_rows:
            return []

        demand_rows.sort(key=lambda item: float(item["deviation_value"]))
        source_rows = [
            row for row in normalized_rows
            if float(row["available_value"]) > float(row["target_value"])
        ]
        if not source_rows:
            return []

        source_rows.sort(key=lambda item: float(item["deviation_value"]), reverse=True)
        candidates: List[Dict[str, float | int | str]] = []

        for target_row in demand_rows:
            for source_row in source_rows:
                if str(source_row["id"]) == str(target_row["id"]):
                    continue

                source_surplus = max(0.0, float(source_row["available_value"]) - float(source_row["target_value"]))
                target_need = max(0.0, float(target_row["target_value"]) - float(target_row["available_value"]))
                transfer_amount = min(source_surplus, target_need)

                if transfer_amount <= 0:
                    continue

                source_after = float(source_row["available_value"]) - transfer_amount
                if source_after < float(source_row["target_value"]):
                    continue

                candidates.append(
                    {
                        "from_account_id": int(str(source_row["id"])),
                        "from_account_name": str(source_row["name"]),
                        "to_account_id": int(str(target_row["id"])),
                        "to_account_name": str(target_row["name"]),
                        "amount": float(round(transfer_amount, 2)),
                    }
                )

        return candidates

    def pick_auto_transfer_candidate(
        self,
        balance_rows: List[Dict[str, str]],
        trigger_ratio: float,
    ) -> Optional[Dict[str, float | int | str]]:
        candidates = self.list_auto_transfer_candidates(balance_rows, trigger_ratio)
        return candidates[0] if candidates else None
