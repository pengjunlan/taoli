"""System exchange config service."""

from __future__ import annotations

from typing import Dict, List

from app.application.dto.requests import SystemExchangeConfigUpdateRequest
from app.domain.entities import AuthUser
from app.infrastructure.persistence.system_exchange_repository import system_exchange_repository
from app.shared.exceptions import AccountPersistenceError, AccountValidationError


EXCHANGE_LABELS = {
    "binance": "Binance",
    "bitget": "Bitget",
    "okx": "OKX",
    "gate": "Gate",
    "htx": "HTX",
}


class SystemExchangeConfigService:
    def list_config_rows(self) -> List[Dict[str, object]]:
        rows = system_exchange_repository.list_configs()
        return [self._build_row(row) for row in rows]

    def get_config_map(self) -> Dict[str, Dict[str, object]]:
        rows = system_exchange_repository.list_configs()
        return {
            str(row["exchange_code"]): {
                "exchange_code": str(row["exchange_code"]),
                "is_enabled": bool(row.get("is_enabled")),
                "use_public_api": bool(row.get("use_public_api")),
                "api_key": str(row.get("api_key") or ""),
                "api_secret": str(row.get("api_secret") or ""),
                "api_passphrase": str(row.get("api_passphrase") or ""),
                "remark": str(row.get("remark") or ""),
            }
            for row in rows
        }

    def get_config_detail(self, exchange_code: str) -> Dict[str, object] | None:
        row = system_exchange_repository.get_config_by_exchange_code(exchange_code.strip().lower())
        if row is None:
            return None
        return {
            "exchange_code": str(row.get("exchange_code") or ""),
            "exchange_label": EXCHANGE_LABELS.get(str(row.get("exchange_code") or ""), str(row.get("exchange_code") or "").upper()),
            "is_enabled": bool(row.get("is_enabled")),
            "use_public_api": bool(row.get("use_public_api")),
            "api_key": str(row.get("api_key") or ""),
            "api_secret": str(row.get("api_secret") or ""),
            "api_passphrase": str(row.get("api_passphrase") or ""),
            "remark": str(row.get("remark") or ""),
            "updated_at": self._format_datetime(row.get("updated_at")),
        }

    def update_config(
        self,
        payload: SystemExchangeConfigUpdateRequest,
        _: AuthUser,
    ) -> Dict[str, object]:
        exchange_code = str(payload.exchange_code or "").strip().lower()
        if exchange_code not in EXCHANGE_LABELS:
            raise AccountValidationError("系统交易所代码不在支持范围内。")

        try:
            entity = system_exchange_repository.upsert_config(
                exchange_code=exchange_code,
                is_enabled=bool(payload.is_enabled),
                use_public_api=bool(payload.use_public_api),
                api_key=str(payload.api_key or "").strip(),
                api_secret=str(payload.api_secret or "").strip(),
                api_passphrase=str(payload.api_passphrase or "").strip(),
                remark=str(payload.remark or "").strip(),
            )
        except Exception as exc:
            raise AccountPersistenceError("保存系统交易所配置失败：数据库操作异常。") from exc

        return self._build_row(
            {
                "id": entity.id,
                "exchange_code": entity.exchange_code,
                "is_enabled": entity.is_enabled,
                "use_public_api": entity.use_public_api,
                "api_key": entity.api_key,
                "api_secret": entity.api_secret,
                "api_passphrase": entity.api_passphrase,
                "remark": entity.remark,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at,
            }
        )

    def build_summary_cards(self, rows: List[Dict[str, object]]) -> List[Dict[str, str]]:
        enabled_count = sum(1 for row in rows if bool(row.get("is_enabled")))
        public_count = sum(1 for row in rows if bool(row.get("use_public_api")))
        private_count = sum(
            1
            for row in rows
            if bool(row.get("is_enabled")) and not bool(row.get("use_public_api"))
        )
        ready_count = sum(1 for row in rows if str(row.get("config_status") or "") == "已配置")

        return [
            {
                "key": "exchange_count",
                "label": "交易所数量",
                "value": str(len(rows)),
                "change": "当前支持的系统级交易所配置",
                "tone": "brand",
            },
            {
                "key": "enabled_count",
                "label": "已启用",
                "value": str(enabled_count),
                "change": "这些交易所会参与系统公共数据同步",
                "tone": "positive",
            },
            {
                "key": "mode_count",
                "label": "私有模式",
                "value": str(private_count),
                "change": f"公开接口 {public_count} / 私有接口 {private_count}",
                "tone": "brand",
            },
            {
                "key": "ready_count",
                "label": "已配置密钥",
                "value": str(ready_count),
                "change": "仅统计已填写系统 API Key/Secret 的交易所",
                "tone": "warning" if ready_count < enabled_count else "positive",
            },
        ]

    def _build_row(self, row: Dict[str, object]) -> Dict[str, object]:
        exchange_code = str(row.get("exchange_code") or "")
        api_key = str(row.get("api_key") or "")
        api_secret = str(row.get("api_secret") or "")
        api_passphrase = str(row.get("api_passphrase") or "")
        use_public_api = bool(row.get("use_public_api"))
        has_private_config = bool(api_key and api_secret)

        if use_public_api:
            mode_label = "公开接口"
            config_status = "公开模式"
            config_tone = "brand"
        elif has_private_config:
            mode_label = "系统私有接口"
            config_status = "已配置"
            config_tone = "positive"
        else:
            mode_label = "系统私有接口"
            config_status = "未配置"
            config_tone = "warning"

        return {
            "id": int(row.get("id") or 0),
            "exchange_code": exchange_code,
            "exchange_label": EXCHANGE_LABELS.get(exchange_code, exchange_code.upper()),
            "is_enabled": bool(row.get("is_enabled")),
            "status_label": "已启用" if bool(row.get("is_enabled")) else "已停用",
            "status_tone": "positive" if bool(row.get("is_enabled")) else "warning",
            "use_public_api": use_public_api,
            "mode_label": mode_label,
            "config_status": config_status,
            "config_tone": config_tone,
            "api_key": self._mask_secret(api_key, left=4, right=4),
            "api_secret": self._mask_secret(api_secret, left=3, right=3),
            "api_passphrase": "已配置" if api_passphrase else "未配置",
            "remark": str(row.get("remark") or "--"),
            "updated_at": self._format_datetime(row.get("updated_at")),
        }

    def _mask_secret(self, value: str, *, left: int, right: int) -> str:
        if not value:
            return "--"
        if len(value) <= left + right:
            return value
        return f"{value[:left]}...{value[-right:]}"

    def _format_datetime(self, value) -> str:
        if value is None:
            return "--"
        return value.strftime("%Y-%m-%d %H:%M")


system_exchange_config_service = SystemExchangeConfigService()
