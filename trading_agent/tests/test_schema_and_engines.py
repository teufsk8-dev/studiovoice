import unittest

from helpers import ROOT, book, candles, pf
from tradeagent.engines import EngineError, JevEngine, StubEngine
from tradeagent.escalation import parse_verdict
from tradeagent.schema import DecisionSchema, SchemaError, parse_decision
from tradeagent.state_engine import build_snapshot

SCHEMA = DecisionSchema.load(ROOT / "schemas" / "decision_v1.json")


def raw(**over):
    r = {"regime": {"probs": {"trending": 0.7, "mean_reverting": 0.1, "high_vol": 0.1, "crisis": 0.1}},
         "direction": {"probs": {"long": 0.9, "short": 0.05, "neutral": 0.05}},
         "toxic_flow": {"probs": {"true": 0.1, "false": 0.9}},
         "setup_quality": {"probs": {"0": 0.1, "1": 0.1, "2": 0.7, "3": 0.1}},
         "risk_state": {"probs": {"safe": 0.9, "near_limit": 0.05, "reduce": 0.05}}}
    r.update(over)
    return r


class SchemaTest(unittest.TestCase):
    def test_parse(self):
        j = parse_decision(SCHEMA, raw())
        self.assertEqual(j["direction"].value, "long")
        self.assertAlmostEqual(j["direction"].confidence, 0.9)
        self.assertIs(j["toxic_flow"].value, False)
        self.assertEqual(j["setup_quality"].value, 2)

    def test_rejects_bad(self):
        for bad in ({"direction": {"probs": {"up": 1.0}}},
                    {"direction": {"probs": {"long": 0.5, "short": 0.1, "neutral": 0.1}}},
                    {"direction": {"probs": {"long": 1.5}}}):
            with self.assertRaises(SchemaError):
                parse_decision(SCHEMA, raw(**bad))
        r = raw()
        del r["regime"]
        with self.assertRaises(SchemaError):
            parse_decision(SCHEMA, r)

    def test_stub_engine_valid(self):
        s = build_snapshot(1_000, book(), candles(), [], pf())
        j = StubEngine().decide(SCHEMA, s)
        self.assertEqual(set(j), set(SCHEMA.fields))

    def test_jev_without_config_errors(self):
        s = build_snapshot(1_000, book(), candles(), [], pf())
        with self.assertRaises(EngineError):
            JevEngine(api_key="", url="").decide(SCHEMA, s)

    def test_escalation_cannot_open(self):
        self.assertEqual(parse_verdict('{"action":"buy"}').action, "hold")
        self.assertEqual(parse_verdict("garbage").action, "hold")
        self.assertEqual(parse_verdict('ok {"action":"flatten","rationale":"x"}').action, "flatten")


if __name__ == "__main__":
    unittest.main()
