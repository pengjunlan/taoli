"""Prototype API payload presenters for dashboard and opportunity feeds."""

import math
import time
from copy import deepcopy
from typing import Dict, List

from app.shared.utils.formatters import (
    format_countdown,
    format_percent,
    format_signed_percent,
    format_usd_compact,
)


START_TS = time.time()


BASE_FUNDING_ROWS = [
    {
        "symbol": "BTC",
        "long_exchange": "Binance",
        "short_exchange": "OKX",
        "annual": 11.82,
        "net_rate": 0.0168,
        "spread": 0.08,
        "depth": 2_600_000,
        "settlement_seconds": 6138,
    },
    {
        "symbol": "ETH",
        "long_exchange": "Bybit",
        "short_exchange": "Gate",
        "annual": 10.94,
        "net_rate": 0.0151,
        "spread": -0.04,
        "depth": 1_900_000,
        "settlement_seconds": 7803,
    },
    {
        "symbol": "SOL",
        "long_exchange": "OKX",
        "short_exchange": "Bybit",
        "annual": 8.74,
        "net_rate": 0.0121,
        "spread": 0.01,
        "depth": 1_300_000,
        "settlement_seconds": 7912,
    },
    {
        "symbol": "XRP",
        "long_exchange": "Binance",
        "short_exchange": "Gate",
        "annual": 8.12,
        "net_rate": 0.0114,
        "spread": -0.02,
        "depth": 920_000,
        "settlement_seconds": 3524,
    },
    {
        "symbol": "DOGE",
        "long_exchange": "Gate",
        "short_exchange": "OKX",
        "annual": 7.34,
        "net_rate": 0.0102,
        "spread": 0.02,
        "depth": 780_000,
        "settlement_seconds": 2887,
    },
    {
        "symbol": "LINK",
        "long_exchange": "Binance",
        "short_exchange": "Bybit",
        "annual": 6.93,
        "net_rate": 0.0098,
        "spread": 0.05,
        "depth": 650_000,
        "settlement_seconds": 4855,
    },
]

BASE_SPREAD_ROWS = [
    {
        "symbol": "ETH",
        "buy_exchange": "Bybit",
        "sell_exchange": "Gate",
        "latest_spread": 0.42,
        "net_spread": 0.31,
        "fees": 0.11,
        "depth": 920_000,
        "position_size": 120_000,
    },
    {
        "symbol": "BTC",
        "buy_exchange": "OKX",
        "sell_exchange": "Binance",
        "latest_spread": 0.33,
        "net_spread": 0.24,
        "fees": 0.09,
        "depth": 1_800_000,
        "position_size": 240_000,
    },
    {
        "symbol": "XRP",
        "buy_exchange": "Gate",
        "sell_exchange": "Binance",
        "latest_spread": 0.29,
        "net_spread": 0.18,
        "fees": 0.11,
        "depth": 510_000,
        "position_size": 70_000,
    },
    {
        "symbol": "SOL",
        "buy_exchange": "Bybit",
        "sell_exchange": "OKX",
        "latest_spread": 0.24,
        "net_spread": 0.15,
        "fees": 0.09,
        "depth": 680_000,
        "position_size": 90_000,
    },
    {
        "symbol": "DOGE",
        "buy_exchange": "OKX",
        "sell_exchange": "Gate",
        "latest_spread": 0.20,
        "net_spread": 0.12,
        "fees": 0.08,
        "depth": 470_000,
        "position_size": 55_000,
    },
    {
        "symbol": "LINK",
        "buy_exchange": "Binance",
        "sell_exchange": "Bybit",
        "latest_spread": 0.17,
        "net_spread": 0.10,
        "fees": 0.07,
        "depth": 360_000,
        "position_size": 45_000,
    },
]

BASE_ALERTS = [
    {"time": "09:28", "level": "高", "message": "OKX 账户 2 的对冲完整度低于 95%"},
    {"time": "09:16", "level": "中", "message": "ETH 价差策略出现一次下单延迟峰值"},
    {"time": "08:54", "level": "低", "message": "Bybit 行情推送已自动重连"},
    {"time": "08:31", "level": "高", "message": "SOL 资金费策略接近最大敞口限制"},
]


def _elapsed_seconds() -> float:
    return time.time() - START_TS

def _metric_delta(value: float, digits: int = 2, signed: bool = True) -> str:
    if signed:
        return format_signed_percent(value, digits)
    return f"{value:.{digits}f}%"


def build_topbar_metrics() -> List[Dict[str, str]]:
    elapsed = _elapsed_seconds()
    opportunity_delta = math.sin(elapsed / 15) * 8
    avg_rate = 0.0148 + math.sin(elapsed / 9) * 0.0012
    peak_spread = 0.42 + math.cos(elapsed / 7) * 0.05
    hedge_ratio = 97.6 + math.sin(elapsed / 11) * 1.4

    return [
        {
            "key": "opportunities",
            "label": "24小时机会数",
            "value": f"{212 + int(opportunity_delta)}",
            "delta": _metric_delta(4.8 + math.sin(elapsed / 10), 1),
            "tone": "positive",
        },
        {
            "key": "funding",
            "label": "平均净资金费",
            "value": format_percent(avg_rate, 4),
            "delta": _metric_delta(0.0021 + math.cos(elapsed / 8) * 0.0008, 4),
            "tone": "positive",
        },
        {
            "key": "spread",
            "label": "跨所价差峰值",
            "value": format_percent(peak_spread, 2),
            "delta": _metric_delta(math.sin(elapsed / 6) * 0.06, 2),
            "tone": "brand" if peak_spread >= 0.4 else "warning",
        },
        {
            "key": "hedge",
            "label": "对冲完整度",
            "value": f"{hedge_ratio:.1f}%",
            "delta": _metric_delta(0.9 + math.sin(elapsed / 9) * 0.6, 1),
            "tone": "positive",
        },
    ]


def build_funding_rows() -> List[Dict[str, object]]:
    elapsed = _elapsed_seconds()
    rows: List[Dict[str, object]] = []

    for index, item in enumerate(BASE_FUNDING_ROWS):
        phase = elapsed / 8 + index * 0.9
        annual = item["annual"] + math.sin(phase) * 0.26
        net_rate = max(item["net_rate"] + math.cos(phase) * 0.0007, 0.0002)
        spread = item["spread"] + math.sin(phase * 1.2) * 0.045
        depth = int(item["depth"] * (1 + math.cos(phase * 0.7) * 0.08))
        total = max(int(item["settlement_seconds"]), 1)
        remaining = max(total - int(elapsed) % total, 0)

        rows.append(
            {
                "symbol": item["symbol"],
                "long_exchange": item["long_exchange"],
                "short_exchange": item["short_exchange"],
                "annual_value": round(annual, 2),
                "annual": f"{annual:.2f}%",
                "net_rate_value": round(net_rate, 4),
                "net_rate": format_percent(net_rate, 4),
                "spread_value": round(spread, 2),
                "spread": format_signed_percent(spread, 2),
                "depth_value": depth,
                "depth": format_usd_compact(depth),
                "settlement_seconds": remaining,
                "settlement": format_countdown(remaining),
            }
        )

    rows.sort(key=lambda current: current["annual_value"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def build_spread_rows() -> List[Dict[str, object]]:
    elapsed = _elapsed_seconds()
    rows: List[Dict[str, object]] = []

    for index, item in enumerate(BASE_SPREAD_ROWS):
        phase = elapsed / 7 + index * 1.1
        latest_spread = max(item["latest_spread"] + math.sin(phase) * 0.06, 0.02)
        fees = max(item["fees"] + math.cos(phase) * 0.01, 0.03)
        net_spread = max(latest_spread - fees, 0.01)
        depth = int(item["depth"] * (1 + math.sin(phase * 0.8) * 0.09))
        position_size = int(item["position_size"] * (1 + math.cos(phase * 0.5) * 0.1))

        rows.append(
            {
                "symbol": item["symbol"],
                "buy_exchange": item["buy_exchange"],
                "sell_exchange": item["sell_exchange"],
                "latest_spread_value": round(latest_spread, 2),
                "latest_spread": format_signed_percent(latest_spread, 2),
                "net_spread_value": round(net_spread, 2),
                "net_spread": format_signed_percent(net_spread, 2),
                "fees_value": round(fees, 2),
                "fees": format_percent(fees, 2),
                "depth_value": depth,
                "depth": format_usd_compact(depth),
                "position_size_value": position_size,
                "position_size": format_usd_compact(position_size),
            }
        )

    rows.sort(key=lambda current: current["net_spread_value"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def build_dashboard_payload() -> Dict[str, object]:
    funding_rows = build_funding_rows()
    spread_rows = build_spread_rows()
    daily_profit = 18420 + math.sin(_elapsed_seconds() / 6) * 1450
    active_strategies = 14 + int((math.sin(_elapsed_seconds() / 20) + 1) * 1.5)
    connected_exchanges = 4
    risk_events = 2 + int((math.cos(_elapsed_seconds() / 18) + 1) * 0.5)

    return {
        "channel": "dashboard",
        "topbar_metrics": build_topbar_metrics(),
        "summary_cards": [
            {
                "label": "今日预估收益",
                "value": f"${daily_profit:,.0f}",
                "change": "+12.6%",
                "tone": "positive",
            },
            {
                "label": "运行中策略",
                "value": str(active_strategies),
                "change": "2条待人工确认",
                "tone": "brand",
            },
            {
                "label": "已连接交易所",
                "value": f"{connected_exchanges} / 4",
                "change": "全部在线",
                "tone": "neutral",
            },
            {
                "label": "风险事件",
                "value": str(risk_events),
                "change": "高优先级需先处理",
                "tone": "warning",
            },
        ],
        "featured": [
            {
                "title": "最大资金费机会",
                "symbol": f"{funding_rows[0]['symbol']}USDT",
                "detail": f"{funding_rows[0]['long_exchange']} 做多 / {funding_rows[0]['short_exchange']} 做空",
                "primary": funding_rows[0]["annual"],
                "primary_label": "当前年化",
                "secondary": f"距结算 {funding_rows[0]['settlement']}",
                "tone": "positive",
            },
            {
                "title": "最大价差机会",
                "symbol": f"{spread_rows[0]['symbol']}USDT",
                "detail": f"{spread_rows[0]['buy_exchange']} 买入 / {spread_rows[0]['sell_exchange']} 卖出",
                "primary": spread_rows[0]["net_spread"],
                "primary_label": "净价差",
                "secondary": f"可成交深度 {spread_rows[0]['depth']}",
                "tone": "brand",
            },
        ],
        "funding_preview": funding_rows[:4],
        "spread_preview": spread_rows[:4],
        "alerts": deepcopy(BASE_ALERTS),
    }


def build_funding_payload() -> Dict[str, object]:
    return {
        "channel": "funding",
        "topbar_metrics": build_topbar_metrics(),
        "opportunity_count": 128,
        "rows": build_funding_rows(),
    }


def build_spread_payload() -> Dict[str, object]:
    return {
        "channel": "spread",
        "topbar_metrics": build_topbar_metrics(),
        "opportunity_count": 84,
        "rows": build_spread_rows(),
    }
