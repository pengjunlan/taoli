from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "views" / "templates"))

router = APIRouter()

NAV_ITEMS = [
    {"key": "dashboard", "label": "首页", "href": "/dashboard"},
    {"key": "funding_arbitrage", "label": "资金费套利", "href": "/funding-arbitrage"},
    {"key": "spread_arbitrage", "label": "价差套利", "href": "/spread-arbitrage"},
    {"key": "strategy_list", "label": "规则管理", "href": "/strategies"},
    {"key": "positions_orders", "label": "持仓订单", "href": "/positions-orders"},
    {"key": "accounts", "label": "账户调度", "href": "/accounts"},
    {"key": "risk_alerts", "label": "风控告警", "href": "/risk-alerts"},
]


def render_page(
    request: Request,
    template_name: str,
    page_key: str,
    page_title: str,
    page_subtitle: str,
    *,
    page_css: str = "",
    page_js: str = "",
    show_shell: bool = True,
    **context,
) -> HTMLResponse:
    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "app_name": "ArbiMatrix",
            "page_key": page_key,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
            "page_css": page_css,
            "page_js": page_js,
            "show_shell": show_shell,
            "nav_items": NAV_ITEMS,
            **context,
        },
    )


def dashboard_context() -> dict:
    return {
        "summary_cards": [
            {"label": "今日预估收益", "value": "$18,420", "change": "+12.6%", "tone": "positive"},
            {"label": "自动规则组", "value": "6", "change": "3组运行中", "tone": "brand"},
            {"label": "已连接交易所", "value": "4 / 4", "change": "全部在线", "tone": "neutral"},
            {"label": "风险事件", "value": "2", "change": "1条需人工处理", "tone": "warning"},
        ],
        "dashboard_rows": dashboard_rows(),
        "alerts": [
            {"time": "09:28", "level": "高", "message": "OKX 账户 2 的对冲完整度低于 95%"},
            {"time": "09:16", "level": "中", "message": "ETH 价差策略出现一次下单延迟峰值"},
            {"time": "08:54", "level": "低", "message": "Bybit 行情推送已自动重连"},
            {"time": "08:31", "level": "高", "message": "SOL 资金费策略接近最大敞口限制"},
        ],
    }


def dashboard_rows() -> List[Dict[str, str]]:
    funding_items = [
        {
            "rank": row["rank"],
            "type": "资金费套利",
            "type_tone": "brand",
            "symbol": row["symbol"],
            "pair_title": "费率组合",
            "line_a": f"做多 {row['symbol']}/USDT · {row['long_exchange']}",
            "line_a_tone": "positive",
            "line_b": f"做空 {row['symbol']}/USDT · {row['short_exchange']}",
            "line_b_tone": "negative",
            "yield_label": "当前年化",
            "yield_value": row["annual"],
            "metric_label": "净资金费率",
            "metric_value": row["net_rate"],
            "edge_label": "价差率",
            "edge_value": row["spread"],
            "edge_tone": "positive" if "+" in row["spread"] else "negative",
            "liquidity": row["depth"],
            "position_qty": row["position_qty"],
            "avg_price": row["avg_price"],
            "position_value": row["position_value"],
            "highlight_label": "距离结算",
            "highlight_value": row["settlement"],
            "detail_link": "/funding-arbitrage",
        }
        for row in funding_rows()[:3]
    ]

    spread_items = [
        {
            "rank": row["rank"],
            "type": "价差套利",
            "type_tone": "positive",
            "symbol": row["symbol"],
            "pair_title": "价差组合",
            "line_a": f"买入 {row['symbol']}/USDT · {row['buy_exchange']}",
            "line_a_tone": "positive",
            "line_b": f"卖出 {row['symbol']}/USDT · {row['sell_exchange']}",
            "line_b_tone": "negative",
            "yield_label": "最新价差",
            "yield_value": row["latest_spread"],
            "metric_label": "净价差",
            "metric_value": row["net_spread"],
            "edge_label": "手续费",
            "edge_value": row["fees"],
            "edge_tone": "",
            "liquidity": row["depth"],
            "position_qty": row["position_qty"],
            "avg_price": row["avg_price"],
            "position_value": row["position_value"],
            "highlight_label": "建议仓位",
            "highlight_value": row["position_size"],
            "detail_link": "/spread-arbitrage",
        }
        for row in spread_rows()[:3]
    ]

    rows = funding_items + spread_items
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def funding_rows() -> List[Dict[str, str]]:
    return [
        {
            "rank": 1,
            "symbol": "BTC",
            "long_exchange": "Binance",
            "short_exchange": "OKX",
            "annual": "11.82%",
            "net_rate": "0.0168%",
            "spread": "+0.08%",
            "depth": "$2.6M",
            "position_qty": "2.30 BTC",
            "avg_price": "104,286",
            "position_value": "$239.9K",
            "settlement": "01:42:18",
        },
        {
            "rank": 2,
            "symbol": "ETH",
            "long_exchange": "Bybit",
            "short_exchange": "Gate",
            "annual": "10.94%",
            "net_rate": "0.0151%",
            "spread": "-0.04%",
            "depth": "$1.9M",
            "position_qty": "29.10 ETH",
            "avg_price": "4,122",
            "position_value": "$120.0K",
            "settlement": "02:10:03",
        },
        {
            "rank": 3,
            "symbol": "SOL",
            "long_exchange": "OKX",
            "short_exchange": "Bybit",
            "annual": "8.74%",
            "net_rate": "0.0121%",
            "spread": "+0.01%",
            "depth": "$1.3M",
            "position_qty": "615 SOL",
            "avg_price": "146.34",
            "position_value": "$90.0K",
            "settlement": "02:11:52",
        },
        {
            "rank": 4,
            "symbol": "XRP",
            "long_exchange": "Binance",
            "short_exchange": "Gate",
            "annual": "8.12%",
            "net_rate": "0.0114%",
            "spread": "-0.02%",
            "depth": "$920K",
            "position_qty": "318,000 XRP",
            "avg_price": "0.2201",
            "position_value": "$70.0K",
            "settlement": "00:58:44",
        },
        {
            "rank": 5,
            "symbol": "DOGE",
            "long_exchange": "Gate",
            "short_exchange": "OKX",
            "annual": "7.34%",
            "net_rate": "0.0102%",
            "spread": "+0.02%",
            "depth": "$780K",
            "position_qty": "255,000 DOGE",
            "avg_price": "0.2157",
            "position_value": "$55.0K",
            "settlement": "00:48:07",
        },
        {
            "rank": 6,
            "symbol": "LINK",
            "long_exchange": "Binance",
            "short_exchange": "Bybit",
            "annual": "6.93%",
            "net_rate": "0.0098%",
            "spread": "+0.05%",
            "depth": "$650K",
            "position_qty": "3,200 LINK",
            "avg_price": "14.06",
            "position_value": "$45.0K",
            "settlement": "01:20:55",
        },
    ]


def spread_rows() -> List[Dict[str, str]]:
    return [
        {
            "rank": 1,
            "symbol": "ETH",
            "buy_exchange": "Bybit",
            "sell_exchange": "Gate",
            "latest_spread": "+0.42%",
            "net_spread": "+0.31%",
            "fees": "0.11%",
            "depth": "$920K",
            "position_qty": "29.10 ETH",
            "avg_price": "4,122",
            "position_value": "$120.0K",
            "position_size": "$120K",
        },
        {
            "rank": 2,
            "symbol": "BTC",
            "buy_exchange": "OKX",
            "sell_exchange": "Binance",
            "latest_spread": "+0.33%",
            "net_spread": "+0.24%",
            "fees": "0.09%",
            "depth": "$1.8M",
            "position_qty": "2.30 BTC",
            "avg_price": "104,286",
            "position_value": "$239.9K",
            "position_size": "$240K",
        },
        {
            "rank": 3,
            "symbol": "XRP",
            "buy_exchange": "Gate",
            "sell_exchange": "Binance",
            "latest_spread": "+0.29%",
            "net_spread": "+0.18%",
            "fees": "0.11%",
            "depth": "$510K",
            "position_qty": "318,000 XRP",
            "avg_price": "0.2201",
            "position_value": "$70.0K",
            "position_size": "$70K",
        },
        {
            "rank": 4,
            "symbol": "SOL",
            "buy_exchange": "Bybit",
            "sell_exchange": "OKX",
            "latest_spread": "+0.24%",
            "net_spread": "+0.15%",
            "fees": "0.09%",
            "depth": "$680K",
            "position_qty": "615 SOL",
            "avg_price": "146.34",
            "position_value": "$90.0K",
            "position_size": "$90K",
        },
        {
            "rank": 5,
            "symbol": "DOGE",
            "buy_exchange": "OKX",
            "sell_exchange": "Gate",
            "latest_spread": "+0.20%",
            "net_spread": "+0.12%",
            "fees": "0.08%",
            "depth": "$470K",
            "position_qty": "255,000 DOGE",
            "avg_price": "0.2157",
            "position_value": "$55.0K",
            "position_size": "$55K",
        },
        {
            "rank": 6,
            "symbol": "LINK",
            "buy_exchange": "Binance",
            "sell_exchange": "Bybit",
            "latest_spread": "+0.17%",
            "net_spread": "+0.10%",
            "fees": "0.07%",
            "depth": "$360K",
            "position_qty": "3,200 LINK",
            "avg_price": "14.06",
            "position_value": "$45.0K",
            "position_size": "$45K",
        },
    ]


def strategy_context() -> dict:
    return {
        "summary_cards": [
            {"label": "规则组总数", "value": "6", "change": "资金费 3 组 / 价差 3 组", "tone": "brand"},
            {"label": "运行中", "value": "3", "change": "自动执行正常", "tone": "positive"},
            {"label": "暂停中", "value": "2", "change": "暂停自动执行", "tone": "warning"},
            {"label": "异常中", "value": "1", "change": "需优先处理", "tone": "negative"},
        ],
        "rule_rows": [
            {
                "name": "主力资金费规则",
                "type": "资金费套利",
                "scope": "Binance / OKX / Bybit",
                "status": "运行中",
                "pnl": "+$8,240",
                "exposure": "$420K",
            },
            {
                "name": "高深度价差规则",
                "type": "价差套利",
                "scope": "BTC / ETH / SOL 优先",
                "status": "运行中",
                "pnl": "+$5,110",
                "exposure": "$360K",
            },
            {
                "name": "夜间资金费规则",
                "type": "资金费套利",
                "scope": "00:00 - 08:00 自动执行",
                "status": "异常",
                "pnl": "-$120",
                "exposure": "$75K",
            },
            {
                "name": "补充价差规则",
                "type": "价差套利",
                "scope": "XRP / DOGE / LINK",
                "status": "暂停",
                "pnl": "+$640",
                "exposure": "$0",
            },
            {
                "name": "保守资金费规则",
                "type": "资金费套利",
                "scope": "低杠杆 / 高流动性",
                "status": "暂停",
                "pnl": "+$1,260",
                "exposure": "$0",
            },
            {
                "name": "全市场价差规则",
                "type": "价差套利",
                "scope": "已配置交易所全量扫描",
                "status": "运行中",
                "pnl": "+$2,180",
                "exposure": "$210K",
            },
        ],
    }


def positions_context() -> dict:
    return {
        "summary_cards": [
            {"label": "净敞口", "value": "$18K", "change": "控制在阈值内", "tone": "positive"},
            {"label": "未成交订单", "value": "7", "change": "2笔等待处理", "tone": "warning"},
            {"label": "对冲完整度", "value": "97.6%", "change": "较上一小时 +0.4%", "tone": "brand"},
            {"label": "浮动盈亏", "value": "+$6,940", "change": "+3.8%", "tone": "positive"},
        ],
        "positions_rows": [
            {
                "symbol": "BTCUSDT",
                "strategy": "BTC 资金费收割",
                "long_exchange": "Binance",
                "short_exchange": "OKX",
                "size": "$240K",
                "hedge": "完整",
                "pnl": "+$3,280",
            },
            {
                "symbol": "ETHUSDT",
                "strategy": "ETH 跨所价差捕捉",
                "long_exchange": "Bybit",
                "short_exchange": "Gate",
                "size": "$120K",
                "hedge": "完整",
                "pnl": "+$1,460",
            },
            {
                "symbol": "SOLUSDT",
                "strategy": "SOL 夜间资金费",
                "long_exchange": "OKX",
                "short_exchange": "Bybit",
                "size": "$75K",
                "hedge": "偏差 4.3%",
                "pnl": "-$120",
            },
        ],
        "order_rows": [
            {"time": "09:32:14", "symbol": "BTCUSDT", "exchange": "OKX", "side": "卖出", "status": "部分成交", "size": "$60K"},
            {"time": "09:31:58", "symbol": "ETHUSDT", "exchange": "Gate", "side": "卖出", "status": "待成交", "size": "$40K"},
            {"time": "09:30:41", "symbol": "SOLUSDT", "exchange": "Bybit", "side": "买入", "status": "待撤单", "size": "$25K"},
        ],
        "fill_rows": [
            {"time": "09:29:12", "symbol": "BTCUSDT", "exchange": "Binance", "side": "买入", "price": "104,285.4", "size": "$80K"},
            {"time": "09:27:20", "symbol": "ETHUSDT", "exchange": "Bybit", "side": "买入", "price": "4,121.8", "size": "$36K"},
            {"time": "09:18:05", "symbol": "DOGEUSDT", "exchange": "Gate", "side": "卖出", "price": "0.2154", "size": "$18K"},
        ],
    }


def accounts_context() -> dict:
    return {
        "summary_cards": [
            {"label": "参与调度账户", "value": "4", "change": "全部已纳入资金监控", "tone": "brand"},
            {"label": "总可用保证金", "value": "$1.82M", "change": "可按规则重新分配", "tone": "positive"},
            {"label": "失衡账户", "value": "2", "change": "Gate / Bybit 低于目标", "tone": "warning"},
            {"label": "自动均衡", "value": "已开启", "change": "阈值 8% · 冷却 15 分钟", "tone": "brand"},
        ],
        "balance_rows": [
            {
                "name": "Binance 主账户",
                "exchange": "Binance",
                "role": "主出金 / 现货中转",
                "available": "$620K",
                "target": "$455K",
                "deviation": "+$165K",
                "status": "可转出",
                "status_tone": "brand",
                "plan_lines": ["转出 $120K 至 Gate", "转出 $45K 至 Bybit"],
            },
            {
                "name": "OKX 套利账户",
                "exchange": "OKX",
                "role": "跨所主套利账户",
                "available": "$540K",
                "target": "$455K",
                "deviation": "+$85K",
                "status": "可转出",
                "status_tone": "brand",
                "plan_lines": ["转出 $85K 至 Gate"],
            },
            {
                "name": "Bybit 高频账户",
                "exchange": "Bybit",
                "role": "高频执行账户",
                "available": "$410K",
                "target": "$455K",
                "deviation": "-$45K",
                "status": "待补足",
                "status_tone": "warning",
                "plan_lines": ["待接收 $45K", "未补足前限制大额新开仓"],
            },
            {
                "name": "Gate 备份账户",
                "exchange": "Gate",
                "role": "备援账户 / 低余额",
                "available": "$250K",
                "target": "$455K",
                "deviation": "-$205K",
                "status": "严重失衡",
                "status_tone": "warning",
                "plan_lines": ["待接收 $205K", "到账前暂停自动开仓"],
            },
        ],
        "transfer_rows": [
            {
                "time": "09:43:12",
                "route_from": "Binance 主账户",
                "route_to": "Gate 备份账户",
                "amount": "$120K",
                "reason": "一键平均分配",
                "status": "处理中",
                "status_tone": "warning",
                "result": "等待链上到账后恢复 Gate 自动开仓",
            },
            {
                "time": "09:39:08",
                "route_from": "OKX 套利账户",
                "route_to": "Gate 备份账户",
                "amount": "$85K",
                "reason": "自动失衡修复",
                "status": "已创建",
                "status_tone": "brand",
                "result": "调拨任务已进入执行队列",
            },
            {
                "time": "09:21:44",
                "route_from": "Binance 主账户",
                "route_to": "Bybit 高频账户",
                "amount": "$45K",
                "reason": "低于目标资金区间",
                "status": "完成",
                "status_tone": "positive",
                "result": "Bybit 可用保证金已恢复到目标区间",
            },
        ],
        "address_rows": [
            {
                "account": "Gate 备份账户",
                "exchange": "Gate",
                "asset": "USDT",
                "network": "TRC20",
                "address": "TQ9m...8kLp",
                "memo": "无",
                "usage": "跨交易所自动调拨",
                "status": "已验证",
                "status_tone": "positive",
                "note": "允许自动均衡直接使用",
            },
            {
                "account": "Bybit 高频账户",
                "exchange": "Bybit",
                "asset": "USDT",
                "network": "ERC20",
                "address": "0x7a1c...91bf",
                "memo": "无",
                "usage": "人工确认后调拨",
                "status": "待复核",
                "status_tone": "warning",
                "note": "大额调拨需人工确认网络与手续费",
            },
            {
                "account": "OKX 套利账户",
                "exchange": "OKX",
                "asset": "USDT",
                "network": "内部划转",
                "address": "子账户 UID 18372",
                "memo": "无",
                "usage": "主账户到子账户",
                "status": "内部可用",
                "status_tone": "brand",
                "note": "无需链上地址，走交易所内部划转",
            },
        ],
        "account_rows": [
            {
                "name": "Binance 主账户",
                "exchange": "Binance",
                "status": "在线",
                "status_tone": "positive",
                "available": "$620K",
                "mode": "全仓 / 单向",
                "leverage": "3x",
                "rebalance": "已参与",
                "rebalance_tone": "positive",
            },
            {
                "name": "OKX 套利账户",
                "exchange": "OKX",
                "status": "在线",
                "status_tone": "positive",
                "available": "$540K",
                "mode": "全仓 / 双向",
                "leverage": "2x",
                "rebalance": "已参与",
                "rebalance_tone": "positive",
            },
            {
                "name": "Bybit 高频账户",
                "exchange": "Bybit",
                "status": "在线",
                "status_tone": "positive",
                "available": "$410K",
                "mode": "逐仓 / 单向",
                "leverage": "3x",
                "rebalance": "已参与",
                "rebalance_tone": "positive",
            },
            {
                "name": "Gate 备份账户",
                "exchange": "Gate",
                "status": "权限待确认",
                "status_tone": "warning",
                "available": "$250K",
                "mode": "全仓 / 单向",
                "leverage": "2x",
                "rebalance": "受限",
                "rebalance_tone": "warning",
            },
        ],
    }


def risk_context() -> dict:
    return {
        "summary_cards": [
            {"label": "风险评分", "value": "78 / 100", "change": "整体可控", "tone": "positive"},
            {"label": "今日告警", "value": "9", "change": "高等级 2 条", "tone": "warning"},
            {"label": "人工接管", "value": "1", "change": "SOL 策略处理中", "tone": "negative"},
            {"label": "全局模式", "value": "谨慎", "change": "自动开仓受限", "tone": "brand"},
        ],
        "risk_rules": [
            {"title": "最大单策略仓位", "value": "$250K", "usage": "当前最高使用 $240K"},
            {"title": "最大总仓位", "value": "$1.20M", "usage": "当前使用 $976K"},
            {"title": "最大滑点阈值", "value": "0.12%", "usage": "当前峰值 0.08%"},
            {"title": "最大未对冲时长", "value": "45 秒", "usage": "当前峰值 18 秒"},
        ],
        "alerts": [
            {"time": "09:28", "level": "高", "message": "SOL 夜间资金费策略对冲偏差超过预警线"},
            {"time": "09:14", "level": "中", "message": "Gate 账户权限状态等待人工确认"},
            {"time": "08:59", "level": "低", "message": "Bybit 行情连接自动恢复"},
        ],
        "event_rows": [
            {"time": "09:28:14", "scope": "策略", "object": "SOL 夜间资金费", "level": "高", "result": "已暂停并等待人工接管"},
            {"time": "09:14:36", "scope": "账户", "object": "Gate 备份账户", "level": "中", "result": "已限制自动开仓"},
            {"time": "08:59:11", "scope": "连接", "object": "Bybit 行情通道", "level": "低", "result": "自动重连成功"},
            {"time": "08:34:57", "scope": "订单", "object": "ETH 价差策略", "level": "中", "result": "重试下单成功"},
        ],
    }


@router.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/login.html",
        "login",
        "大宝-套利系统登录",
        "请输入账号和密码。",
        page_css="login.css",
        page_js="login.js",
        show_shell=False,
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/register.html",
        "register",
        "注册账号",
        "填写账号信息完成注册。",
        page_css="login.css",
        page_js="register.js",
        show_shell=False,
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/dashboard.html",
        "dashboard",
        "多交易所套利总览",
        "统一查看自动监控、可执行机会和关键风险状态。",
        page_css="dashboard.css",
        page_js="dashboard.js",
        **dashboard_context(),
    )


@router.get("/funding-arbitrage", response_class=HTMLResponse)
async def funding_arbitrage_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/funding_arbitrage.html",
        "funding_arbitrage",
        "资金费套利",
        "重点展示自动扫描到的资金费机会，以及统一的规则参数与执行入口。",
        page_css="funding_arbitrage.css",
        page_js="funding_arbitrage.js",
        rows=funding_rows(),
    )


@router.get("/spread-arbitrage", response_class=HTMLResponse)
async def spread_arbitrage_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/spread_arbitrage.html",
        "spread_arbitrage",
        "跨交易所价差套利",
        "重点展示跨所自动监控机会，以及按规则统一执行的价差套利逻辑。",
        page_css="spread_arbitrage.css",
        page_js="spread_arbitrage.js",
        rows=spread_rows(),
    )


@router.get("/strategies", response_class=HTMLResponse)
async def strategy_list_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/strategy_list.html",
        "strategy_list",
        "自动规则管理",
        "管理全局自动执行规则组，而不是逐个交易对手工建策略。",
        page_css="strategy_list.css",
        page_js="strategy_list.js",
        **strategy_context(),
    )


@router.get("/positions-orders", response_class=HTMLResponse)
async def positions_orders_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/positions_orders.html",
        "positions_orders",
        "持仓与订单",
        "统一查看自动套利后的持仓状态、异常订单和最近成交。",
        page_css="positions_orders.css",
        page_js="positions_orders.js",
        **positions_context(),
    )


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/accounts.html",
        "accounts",
        "账户与资金调度",
        "统一管理交易所账户、资金均衡、一键分配和自动失衡修复。",
        page_css="accounts.css",
        page_js="accounts.js",
        **accounts_context(),
    )


@router.get("/risk-alerts", response_class=HTMLResponse)
async def risk_alerts_page(request: Request) -> HTMLResponse:
    return render_page(
        request,
        "pages/risk_alerts.html",
        "risk_alerts",
        "风控与告警",
        "集中查看会影响自动执行、资金均衡和收益波动的关键风险事件。",
        page_css="risk_alerts.css",
        page_js="risk_alerts.js",
        **risk_context(),
    )
