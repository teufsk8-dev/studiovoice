"""Escalation to the slow "brain" (Claude via the Anthropic Messages API).

Contract: an escalation can only make the book SAFER. Allowed verdicts are
  hold    - no new risk until next candle (default on any failure)
  reduce  - halve the position
  flatten - close the position
It can never open or increase a position. The live candle that triggered the
escalation always HOLDs; the verdict is applied when it arrives.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import urllib.request
from dataclasses import dataclass

ALLOWED = ("hold", "reduce", "flatten")


@dataclass(frozen=True)
class EscalationVerdict:
    action: str
    rationale: str


def parse_verdict(text: str) -> EscalationVerdict:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
        action = str(obj.get("action", "hold")).lower()
    except (ValueError, json.JSONDecodeError):
        return EscalationVerdict("hold", "unparseable verdict")
    if action not in ALLOWED:
        return EscalationVerdict("hold", f"disallowed action {action!r}")
    return EscalationVerdict(action, str(obj.get("rationale", ""))[:500])


class ClaudeEscalator:
    def __init__(self, model: str | None = None, timeout_s: float = 60.0):
        self.model = model or os.environ.get("ESCALATION_MODEL", "claude-opus-5-5")
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.timeout_s = timeout_s
        self._q: queue.Queue = queue.Queue(maxsize=8)
        self.results: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, context: dict) -> bool:
        try:
            self._q.put_nowait(context)
            return True
        except queue.Full:
            return False  # already busy escalating; the loop keeps holding

    def _worker(self) -> None:
        while True:
            ctx = self._q.get()
            self.results.put(self.review(ctx))

    def review(self, ctx: dict) -> EscalationVerdict:
        if not self.api_key:
            return EscalationVerdict("hold", "no ANTHROPIC_API_KEY")
        prompt = (
            "You are the risk reviewer of an automated crypto strategy. The fast model flagged "
            "low confidence or a crisis regime. Given the state and recent decisions below, reply "
            'with JSON only: {"action": "hold"|"reduce"|"flatten", "rationale": "..."}. '
            "You cannot open or add to positions.\n\n" + json.dumps(ctx, default=str)[:20000]
        )
        body = {"model": self.model, "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                data = json.loads(r.read())
            text = "".join(b.get("text", "") for b in data.get("content", []))
        except Exception as e:
            return EscalationVerdict("hold", f"escalation failed: {e}")
        return parse_verdict(text)
