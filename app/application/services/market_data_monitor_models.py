from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Tuple


@dataclass(frozen=True)
class WatchTarget:
    exchange_code: str
    market_type: str
    symbol: str


@dataclass(frozen=True)
class ExchangeWsTarget:
    exchange_code: str
    market_type: str
    symbol: str
    ws_symbol: str


@dataclass(frozen=True)
class BackfillTaskSpec:
    task_key: str
    exchange_code: str
    market_type: str
    task_type: str
    symbols: Tuple[str, ...]
    chunk_index: int = 1
    chunk_total: int = 1


@dataclass
class BackfillTaskState:
    task_key: str
    exchange_code: str
    market_type: str
    task_type: str
    symbol_count: int = 0
    is_running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_duration_ms: int = 0
    last_success_count: int = 0
    last_missing_count: int = 0
    last_error_message: str = ""
    last_round_id: int = 0
