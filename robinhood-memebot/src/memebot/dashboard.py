"""Rich terminal dashboard: launch feed, decisions, positions, action log."""

from __future__ import annotations

import time

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import Config
from .executor import Executor
from .pipeline import UiState

STATUS_STYLE = {"buy": "bold black on green", "hold": "yellow", "skip": "dim", "watching": "cyan"}
LOG_STYLE = {"buy": "bold green", "warn": "yellow", "error": "bold red", "info": ""}


def _short(addr: str | None) -> str:
    return f"{addr[:6]}…{addr[-4:]}" if addr and len(addr) > 12 else (addr or "-")


def _hms(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _num(value, fmt: str = "{:,.0f}") -> str:
    return "-" if value is None else fmt.format(value)


def _header(cfg: Config, ui: UiState, executor: Executor, started: float) -> Panel:
    mode = Text(" LIVE ", style="bold white on red") if cfg.live_mode else Text(" PAPER ", style="bold black on cyan")
    rpc = Text("RPC ok", style="green") if ui.rpc_ok else Text("RPC error", style="bold red")
    line = Text.assemble(
        mode, "  ", rpc,
        f"  chain {cfg.chain_id}  block {ui.block or '-'}  engine {cfg.decision_engine}",
        f"  pools {ui.detected}  decided {ui.decided}  buys {ui.buys}",
        f"  spend {executor.session_spend:g}/{cfg.max_session_spend_quote:g}",
        f"  up {int(time.time() - started)}s",
    )
    return Panel(line, title="Robinhood Chain memebot", border_style="red" if cfg.live_mode else "cyan")


def _launches(ui: UiState) -> Panel:
    table = Table(expand=True, box=None, header_style="bold")
    for col in ("time", "token", "pool", "fee", "liq $", "jev", "conf", "risk", "ms", "final", "reason"):
        table.add_column(col, no_wrap=col != "reason", overflow="ellipsis")
    for r in list(ui.launches)[:15]:
        style = STATUS_STYLE.get(r.status, "")
        table.add_row(
            _hms(r.detected_at), r.symbol or _short(r.token), _short(r.pool), str(r.fee),
            _num(r.liquidity_usd), r.jev_action or "-", _num(r.confidence, "{:.2f}"),
            _num(r.risk_score, "{:g}"), _num(r.latency_ms),
            Text(r.status.upper() + (f" ({r.execution})" if r.execution else ""), style=style),
            r.reason, style="on dark_green" if r.status == "buy" else None,
        )
    return Panel(table, title="New pools")


def _positions(executor: Executor) -> Panel:
    table = Table(expand=True, box=None, header_style="bold")
    for col in ("#", "mode", "token", "in", "entry", "now", "pnl %", "tx"):
        table.add_column(col, no_wrap=True)
    for p in executor.positions:
        pnl = p.pnl_pct
        table.add_row(
            str(p.id), p.mode, p.symbol or _short(p.token), f"{p.amount_in_quote:g}",
            f"{p.entry_price:.3e}", f"{p.current_price:.3e}",
            Text(f"{pnl:+.2f}", style="green" if pnl >= 0 else "red"), _short(p.tx_hash),
        )
    return Panel(table, title=f"Positions ({len(executor.positions)})")


def _log(ui: UiState, height: int = 14) -> Panel:
    lines = [Text(f"{_hms(ts)} {msg}", style=LOG_STYLE.get(level, "")) for ts, level, msg in list(ui.log)[-height:]]
    return Panel(Group(*lines), title="Actions")


def render(cfg: Config, ui: UiState, executor: Executor, started: float) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(_header(cfg, ui, executor, started), size=3),
        Layout(_launches(ui), ratio=3),
        Layout(name="bottom", ratio=2),
    )
    layout["bottom"].split_row(Layout(_positions(executor)), Layout(_log(ui)))
    return layout
