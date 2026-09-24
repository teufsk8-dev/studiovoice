import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradeagent.types import BookLevel, Candle, OrderBook, Portfolio, Side, Trade  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def book(mid=100.0, spread=0.02, ts=1_000, bid_sz=5.0, ask_sz=5.0, sym="BTC-USD"):
    h = spread / 2
    return OrderBook(sym, ts,
                     tuple(BookLevel(mid - h - i * 0.01, bid_sz) for i in range(5)),
                     tuple(BookLevel(mid + h + i * 0.01, ask_sz) for i in range(5)))


def candles(n=30, start=100.0, step=0.0, ts_end=1_000):
    return [Candle(ts_end - (n - 1 - i) * 60_000, 0, 0, 0, start + i * step, 1) for i in range(n)]


def pf(equity=10_000.0, peak=None, day=None, pos=0.0, entry=0.0):
    return Portfolio(equity, peak or equity, day or equity, pos, entry)
