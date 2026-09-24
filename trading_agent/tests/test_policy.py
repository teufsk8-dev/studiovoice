import unittest

from tradeagent.policy import PolicyConfig, code_risk_state, decide, kelly_fraction
from tradeagent.schema import Judgment


def J(direction="long", conf=0.85, quality=2, risk="safe", toxic=False, regime="trending"):
    rest = (1 - conf) / 2
    dp = {d: (conf if d == direction else rest) for d in ("long", "short", "neutral")}
    return {
        "direction": Judgment(direction, dp),
        "regime": Judgment(regime, {regime: 0.9}),
        "setup_quality": Judgment(quality, {quality: 0.9}),
        "risk_state": Judgment(risk, {risk: 0.9}),
        "toxic_flow": Judgment(toxic, {toxic: 0.9}),
    }


class PolicyTest(unittest.TestCase):
    cfg = PolicyConfig()

    def test_fires_when_all_gates_pass(self):
        r = decide(J(), "safe", self.cfg)
        self.assertEqual(r.action, "long")
        self.assertGreater(r.size_frac, 0)

    def test_gates(self):
        for kw in ({"conf": 0.80}, {"quality": 1}, {"risk": "near_limit"}, {"toxic": True},
                   {"direction": "neutral"}):
            self.assertEqual(decide(J(**kw), "safe", self.cfg).action, "hold", kw)

    def test_code_risk_state_overrides_model(self):
        self.assertEqual(decide(J(risk="safe"), "reduce", self.cfg).action, "hold")

    def test_escalation(self):
        self.assertTrue(decide(J(conf=0.55), "safe", self.cfg).escalate)
        r = decide(J(regime="crisis"), "safe", self.cfg)
        self.assertTrue(r.escalate)
        self.assertEqual(r.action, "hold")

    def test_quarter_kelly_cap(self):
        cfg = PolicyConfig(kelly_fraction=1.0)  # config cannot exceed quarter Kelly
        r = decide(J(conf=0.95), "safe", cfg)
        full = kelly_fraction(0.95, cfg.reward_risk, cfg.round_trip_cost_bps / cfg.stop_bps)
        self.assertAlmostEqual(r.size_frac, 0.25 * full)

    def test_kelly_zero_without_edge(self):
        self.assertEqual(kelly_fraction(0.3, 1.0), 0.0)
        self.assertAlmostEqual(kelly_fraction(0.6, 1.0), 0.2)

    def test_costs_can_kill_edge(self):
        cfg = PolicyConfig(reward_risk=0.3, round_trip_cost_bps=40, stop_bps=50)
        self.assertEqual(decide(J(conf=0.81), "safe", cfg).action, "hold")

    def test_code_risk_state(self):
        self.assertEqual(code_risk_state(0.0, 0.0, 0.0, 0.15, 0.03, 0.2), "safe")
        self.assertEqual(code_risk_state(0.06, 0.0, 0.0, 0.15, 0.03, 0.2), "near_limit")
        self.assertEqual(code_risk_state(0.11, 0.0, 0.0, 0.15, 0.03, 0.2), "reduce")


if __name__ == "__main__":
    unittest.main()
