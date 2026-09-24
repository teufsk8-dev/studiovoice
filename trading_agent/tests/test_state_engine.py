import unittest

from helpers import book, candles, pf
from tradeagent.state_engine import LookaheadError, build_snapshot
from tradeagent.types import Side, Trade


class StateEngineTest(unittest.TestCase):
    def test_basic_fields(self):
        s = build_snapshot(1_000, book(bid_sz=9, ask_sz=1), candles(), [], pf())
        self.assertAlmostEqual(s.fields["mid"], 100.0)
        self.assertAlmostEqual(s.fields["spr_bps"], 2.0, places=3)
        self.assertAlmostEqual(s.fields["imb5"], 0.8)
        self.assertEqual(s.fields["dd"], 0.0)

    def test_under_400_tokens(self):
        s = build_snapshot(1_000, book(), candles(), [], pf())
        self.assertLess(s.est_tokens(), 400)

    def test_rejects_future_book(self):
        with self.assertRaises(LookaheadError):
            build_snapshot(999, book(ts=1_000), candles(ts_end=999), [], pf())

    def test_rejects_future_candle(self):
        with self.assertRaises(LookaheadError):
            build_snapshot(1_000, book(), candles(ts_end=1_001), [], pf())

    def test_rejects_future_trade(self):
        with self.assertRaises(LookaheadError):
            build_snapshot(1_000, book(), candles(), [Trade(1_001, 100, 1, Side.BUY)], pf())

    def test_crossed_book(self):
        b = book(spread=-0.1)
        with self.assertRaises(ValueError):
            build_snapshot(1_000, b, candles(), [], pf())

    def test_drawdown_inventory(self):
        s = build_snapshot(1_000, book(), candles(), [], pf(equity=9_000, peak=10_000, pos=10))
        self.assertAlmostEqual(s.fields["dd"], 0.1)
        self.assertAlmostEqual(s.fields["inv_pct"], 1000 / 9000, places=4)


if __name__ == "__main__":
    unittest.main()
