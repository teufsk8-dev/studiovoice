import unittest

from helpers import pf
from tradeagent.risk import RiskLimits, RiskManager
from tradeagent.types import Order, Side


def order(side=Side.BUY, qty=1.0, px=100.0):
    return Order("BTC-USD", side, qty, px)


class RiskTest(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(RiskLimits())

    def test_clips_order_size(self):
        v = self.rm.check(order(qty=100), pf(), 100, 2, 0)
        self.assertTrue(v.approved)
        self.assertAlmostEqual(v.order.qty, 5.0)  # 5% of 10k / 100

    def test_drawdown_trips_and_latches(self):
        p = pf(equity=8_400, peak=10_000)
        v = self.rm.check(order(), p, 100, 2, 0)
        self.assertFalse(v.approved)
        self.assertTrue(self.rm.kill.tripped)
        p.equity = 10_000  # recovery does not un-trip
        self.assertFalse(self.rm.check(order(), p, 100, 2, 0).approved)
        self.rm.kill.reset("operator reviewed")
        self.assertTrue(self.rm.check(order(), pf(), 100, 2, 0).approved)

    def test_tripped_still_allows_reducing(self):
        self.rm.kill.trip("test")
        v = self.rm.check(order(side=Side.SELL, qty=1), pf(pos=3), 100, 2, 0)
        self.assertTrue(v.approved)

    def test_daily_loss_halts_new_risk(self):
        v = self.rm.check(order(), pf(equity=9_600, day=10_000, peak=10_000), 100, 2, 0)
        self.assertFalse(v.approved)

    def test_position_cap(self):
        v = self.rm.check(order(qty=5), pf(pos=20), 100, 2, 0)  # already 20% notional
        self.assertFalse(v.approved)

    def test_stale_and_wide(self):
        self.assertFalse(self.rm.check(order(), pf(), 100, 2, 10_000).approved)
        self.assertFalse(self.rm.check(order(), pf(), 100, 40, 0).approved)

    def test_price_band(self):
        self.assertFalse(self.rm.check(order(px=102), pf(), 100, 2, 0).approved)

    def test_disarmed_refuses_everything(self):
        self.rm.kill.armed = False
        self.assertFalse(self.rm.check(order(), pf(), 100, 2, 0).approved)


if __name__ == "__main__":
    unittest.main()
