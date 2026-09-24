from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    ts_ms: int  # exchange timestamp of this book state
    bids: tuple[BookLevel, ...]  # best first
    asks: tuple[BookLevel, ...]  # best first


@dataclass(frozen=True)
class Trade:
    ts_ms: int
    price: float
    size: float
    aggressor: Side


@dataclass(frozen=True)
class Candle:
    ts_ms: int  # close time; a candle is only usable once ts_ms <= as_of
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Portfolio:
    equity: float
    peak_equity: float
    day_start_equity: float
    position_qty: float = 0.0  # signed, base units
    avg_entry: float = 0.0


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    qty: float
    limit_price: float
    reason: str = ""


@dataclass
class RiskVerdict:
    approved: bool
    order: Order | None
    reasons: list[str] = field(default_factory=list)
