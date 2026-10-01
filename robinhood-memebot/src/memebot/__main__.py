"""Entry point: python -m memebot [--headless] [--env FILE]"""

from __future__ import annotations

import argparse
import sys
import time

from .chain import ChainReader
from .config import load_config
from .decision import DecisionRunner, load_engine
from .executor import Executor, LiveModeRefused
from .journal import Journal
from .pipeline import Pipeline, UiState


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="memebot", description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the .env file")
    parser.add_argument("--headless", action="store_true", help="plain log output instead of the dashboard")
    args = parser.parse_args(argv)

    cfg = load_config(args.env)
    if not cfg.quote_token:
        print("QUOTE_TOKEN is not set in .env (the token new pools are paired with, usually WETH).")
        return 2

    reader = ChainReader(cfg.rpc_url, cfg.factory)
    executor = Executor(cfg, reader, Journal(cfg.ledger_log))
    try:
        warnings = executor.preflight()
    except LiveModeRefused as exc:
        print(exc)
        return 3
    runner = DecisionRunner(load_engine(cfg.decision_engine), cfg.decision_timeout)
    ui = UiState()
    if args.headless:
        ui.on_log = lambda ts, level, msg: print(
            f"{time.strftime('%H:%M:%S', time.localtime(ts))} [{level}] {msg}", flush=True
        )
    for w in warnings:
        ui.add_log("warn", w)
    if cfg.live_mode:
        ui.add_log("warn", f"LIVE MODE: real swaps of {cfg.trade_size_quote} from {executor.account.address}")
    pipeline = Pipeline(cfg, reader, runner, executor, Journal(cfg.decisions_log), ui)

    try:
        pipeline.start()
    except Exception as exc:
        print(f"Cannot reach RPC {cfg.rpc_url}: {type(exc).__name__}: {exc}")
        runner.shutdown()
        return 4

    started = time.time()
    try:
        if args.headless:
            _run_headless(cfg, pipeline, ui)
        else:
            from rich.live import Live

            from .dashboard import render

            with Live(render(cfg, ui, executor, started), refresh_per_second=4, screen=True) as live:
                _loop(cfg, pipeline, ui, lambda: live.update(render(cfg, ui, executor, started)))
    except KeyboardInterrupt:
        pass
    finally:
        runner.shutdown()
    return 0


def _loop(cfg, pipeline: Pipeline, ui: UiState, refresh) -> None:
    errors = 0
    while True:
        try:
            pipeline.tick()
            errors = 0
        except Exception as exc:
            errors += 1
            ui.rpc_ok = False
            ui.add_log("error", f"tick failed: {type(exc).__name__}: {exc}")
        refresh()
        # Back off on repeated RPC errors, up to 30s.
        time.sleep(min(30.0, cfg.poll_interval * (2 ** min(errors, 4))))


def _run_headless(cfg, pipeline: Pipeline, ui: UiState) -> None:
    _loop(cfg, pipeline, ui, lambda: None)


if __name__ == "__main__":
    sys.exit(main())
