"""Main loop: detect pools -> watch until liquid -> decide -> gate -> execute -> log."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .chain import ChainReader, PoolCreated, TokenInfo
from .config import Config
from .decision import DecisionRunner
from .executor import Executor
from .gates import evaluate_gates, final_action, gates_as_dicts
from .journal import Journal
from .market import QuotePricer, build_state, pair_side, snapshot


@dataclass
class LaunchRow:
    """One line of the dashboard's launch feed."""

    detected_at: float
    pool: str
    token: str
    symbol: str | None = None
    fee: int = 0
    liquidity_usd: float | None = None
    status: str = "watching"  # watching | buy | hold | skip
    jev_action: str | None = None
    confidence: float | None = None
    risk_score: float | None = None
    latency_ms: float | None = None
    reason: str = ""
    execution: str | None = None


@dataclass
class UiState:
    block: int | None = None
    rpc_ok: bool = True
    launches: deque = field(default_factory=lambda: deque(maxlen=30))
    log: deque = field(default_factory=lambda: deque(maxlen=200))
    detected: int = 0
    decided: int = 0
    buys: int = 0
    on_log: Callable[[float, str, str], None] | None = None

    def add_log(self, level: str, msg: str) -> None:
        entry = (time.time(), level, msg)
        self.log.append(entry)
        if self.on_log:
            self.on_log(*entry)


@dataclass
class Watch:
    event: PoolCreated
    token: str
    first_seen: float
    row: LaunchRow
    info: TokenInfo | None = None


class Pipeline:
    def __init__(self, cfg: Config, reader: ChainReader, runner: DecisionRunner,
                 executor: Executor, decisions: Journal, ui: UiState):
        self.cfg, self.reader, self.runner, self.executor = cfg, reader, runner, executor
        self.decisions, self.ui = decisions, ui
        self.pricer = QuotePricer(reader, cfg.quote_token, cfg.quote_usd_price, cfg.quote_usd_pool)
        self.watching: dict[str, Watch] = {}
        self.next_block: int | None = None

    def start(self) -> None:
        latest = self.reader.latest_block()
        if self.cfg.start_block is not None:
            self.next_block = self.cfg.start_block
        else:
            self.next_block = max(0, latest - self.cfg.lookback_blocks)
        self.ui.block = latest
        self.ui.add_log("info", f"scanning from block {self.next_block}")

    # --- one iteration ------------------------------------------------------------

    def tick(self) -> None:
        latest = self.reader.latest_block()
        self.ui.block, self.ui.rpc_ok = latest, True
        while self.next_block <= latest:
            to_block = min(latest, self.next_block + self.cfg.max_block_range - 1)
            for event in self.reader.pool_created_events(self.next_block, to_block):
                self._on_pool_created(event)
            self.next_block = to_block + 1
        for watch in list(self.watching.values()):
            try:
                self._evaluate(watch)
            except Exception as exc:  # one bad token must not stop the loop
                self.ui.add_log("error", f"evaluate {watch.event.pool[:10]}…: {type(exc).__name__}: {exc}")
        self.executor.mark_to_market()

    def _on_pool_created(self, event: PoolCreated) -> None:
        self.ui.detected += 1
        token = pair_side(event, self.cfg.quote_token)
        row = LaunchRow(time.time(), event.pool, token or f"{event.token0}/{event.token1}", fee=event.fee)
        self.ui.launches.appendleft(row)
        if token is None:
            row.status, row.reason = "skip", "not paired with QUOTE_TOKEN"
            self._log_decision(row, event, state=None, decision=None, gates=None, action="skip",
                               reasons=[row.reason])
            return
        self.ui.add_log("info", f"new pool {event.pool[:10]}… token {token[:10]}… fee {event.fee}")
        self.watching[event.pool] = Watch(event, token, time.time(), row)

    def _evaluate(self, watch: Watch) -> None:
        row = watch.row
        if watch.info is None:
            watch.info = self.reader.token_info(watch.token)
            row.symbol = watch.info.symbol
        snap = snapshot(self.reader, watch.event, watch.info, self.cfg.quote_token, self.pricer.usd())
        age = time.time() - watch.first_seen
        state = build_state(snap, age)
        row.liquidity_usd = snap.liquidity_usd

        # A pool is created empty, then initialised and funded. Calling the engine
        # before it holds enough quote liquidity would only ever produce skips.
        liquid = snap.initialized and (snap.liquidity_usd or 0) >= self.cfg.min_liquidity_usd
        if not liquid:
            if age < self.cfg.watch_window:
                row.reason = "waiting for liquidity" if snap.initialized else "not initialised"
                return
            del self.watching[watch.event.pool]
            row.status = "skip"
            row.reason = f"liquidity_usd={snap.liquidity_usd} below {self.cfg.min_liquidity_usd} after watch window"
            self._log_decision(row, watch.event, state, None, None, "skip", [row.reason])
            return

        del self.watching[watch.event.pool]
        decision = self.runner.run(state)
        gates = evaluate_gates(state, decision, self.cfg)
        action, reasons = final_action(decision, gates)
        self.ui.decided += 1
        row.status, row.jev_action = action, decision.action
        row.confidence, row.risk_score, row.latency_ms = decision.confidence, decision.risk_score, decision.latency_ms
        row.reason = "; ".join(reasons) if reasons else "all gates passed"

        execution = None
        if action == "buy":
            self.ui.buys += 1
            execution = self.executor.buy(snap, decision)
            row.execution = execution["status"]
            level = "buy" if execution["status"] in ("paper", "filled") else "warn"
            self.ui.add_log(level, f"BUY {row.symbol} [{execution['status']}] "
                                   f"fill={execution['fill_price']} sim={execution['sim_price']} "
                                   f"{execution['error'] or ''}")
        else:
            self.ui.add_log("info", f"{action.upper()} {row.symbol}: {row.reason}")
        self._log_decision(row, watch.event, state, decision, gates, action, reasons, execution)

    def _log_decision(self, row, event, state, decision, gates, action, reasons, execution=None) -> None:
        self.decisions.write(
            {
                "ts": time.time(),
                "block": event.block,
                "pool_tx": event.tx_hash,
                "pool": event.pool,
                "token": row.token,
                "state": state,
                "jev_raw": decision.raw if decision else None,
                "decision": decision.as_dict() if decision else None,
                "gates": gates_as_dicts(gates) if gates else None,
                "final_action": action,
                "reasons": reasons,
                "execution": execution,
            }
        )
