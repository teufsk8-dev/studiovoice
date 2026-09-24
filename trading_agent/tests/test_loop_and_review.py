import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, Side, Trade, book, candles, pf
from tradeagent.engines import StubEngine
from tradeagent.loop import Agent, PaperExchange
from tradeagent.review import load, review, write_proposal
from tradeagent.risk import RiskLimits, RiskManager
from tradeagent.schema import DecisionSchema

SCHEMA_PATH = ROOT / "schemas" / "decision_v1.json"


class LoopTest(unittest.TestCase):
    def test_end_to_end_paper(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "dec.jsonl"
            agent = Agent(DecisionSchema.load(SCHEMA_PATH), StubEngine(), RiskManager(RiskLimits()),
                          PaperExchange(), pf(), log_path=log)
            for i in range(40):
                mid = 100 + i * 0.05
                ts = 1_000 + i * 60_000
                agent.step(ts, book(mid=mid, ts=ts, bid_sz=9, ask_sz=1), candles(ts_end=ts, start=mid - 1.5, step=0.05),
                           [Trade(ts - 1_000, mid, 2.0, Side.BUY)])
            rows = load(log)
            self.assertEqual(len(rows), 40)
            self.assertTrue(any(r.get("fill") for r in rows))
            # never exceeds position cap
            for r in rows:
                self.assertLessEqual(abs(r["pos"]) * r["snap"]["mid"], 0.2 * 10_000 * 1.2)
            res = review(rows)
            self.assertEqual(res.n, 39)
            p = write_proposal(res, SCHEMA_PATH, Path(d) / "prop")
            self.assertTrue(p.exists())
            self.assertIn("PROPOSED", p.read_text())


if __name__ == "__main__":
    unittest.main()
