"""Shared formatting helpers for presentation output."""

def format_signed_percent(value: float, digits: int = 2) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{digits}f}%"


def format_percent(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}%"


def format_usd_compact(value: float) -> str:
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:.0f}"


def format_countdown(seconds: int) -> str:
    seconds = max(seconds, 0)
    hours, remainder = divmod(seconds, 3600)
    minutes, second = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{second:02d}"
