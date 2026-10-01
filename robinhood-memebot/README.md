# Robinhood Chain memebot

Watches the Uniswap V3 factory on Robinhood Chain (chain ID 4663) for new pools,
waits until a pool is actually funded, asks a decision engine (Jev) for
`buy` / `hold` / `skip`, applies hard gates **in code**, and executes buys:
paper by default, real swaps only with `LIVE_MODE=true`.

```
PoolCreated ──► watch list ──(liquidity ≥ min)──► state ──► decide() ──► hard gates ──► executor
                    │                                         │              │              │
                    └─ window expires: skip ──────────────────┴──────────────┴──► data/decisions.jsonl
                                                                                  data/ledger.jsonl (buys)
```

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in QUOTE_TOKEN at least
```

## Run

```bash
PYTHONPATH=src python -m memebot              # rich dashboard
PYTHONPATH=src python -m memebot --headless   # plain log lines (servers, tmux, CI)
pytest                                         # unit tests, no network needed
```

(`pip install -e .` also works; then just run `memebot`.)

## What you must configure

| Variable | Why |
|---|---|
| `QUOTE_TOKEN` | Token memecoins are paired with (normally WETH). Pools without it are skipped. |
| `QUOTE_USD_PRICE` or `QUOTE_USD_POOL` | Converts the quote reserve to USD. The pool option reads a live `QUOTE/stablecoin` V3 pool. |
| `DECISION_ENGINE=jev` + `TYPESAFE_API_KEY` | Uses `src/memebot/decision_engine.py`. `stub` (default) never buys. |
| `QUOTER_V2_ADDRESS` | Needed to simulate buys. Without it, paper fills use the pool mid price. |
| `SWAP_ROUTER02_ADDRESS`, `PRIVATE_KEY`, `LIVE_MODE=true` | Live trading only. |

None of the WETH / QuoterV2 / SwapRouter02 addresses are hard-coded: take them
from the official Uniswap deployment list for Robinhood Chain and check them on
the block explorer.

## How a decision is made

1. **Detection.** `PoolCreated` logs are polled from the factory every `POLL_INTERVAL_SEC`.
2. **Watching.** A V3 pool is created empty. It's re-read every tick until its quote-side
   liquidity reaches `MIN_LIQUIDITY_USD`, or `WATCH_WINDOW_SEC` expires (→ skip, engine not called).
3. **State** sent to `decide()`: `token_address`, `total_supply`, `owner_renounced`,
   `contract_has_code`, `pool_price` (quote per token, from `slot0`), `liquidity_usd`, plus
   symbol, name, `tvl_usd`, fee tier, pool age.
4. **Engine call.** Runs in a worker thread with a `DECISION_TIMEOUT_SEC` cap. Timeout, exception or
   malformed output = `skip`.
5. **Hard gates** (`gates.py`), any failure = `skip`:
   `liquidity_usd ≥ 20000`, `confidence ≥ 0.70`, `risk_score ≤ 4` (missing score fails),
   `owner_renounced`, `contract_has_code`.
6. **Execution** when the final action is `buy`.
7. **Logging.** Every outcome (buy, hold, skip, expiry, unpaired pool) goes to `DECISIONS_LOG` with the full
   state, Jev's raw answer, each gate's value and threshold, and the execution result.

### `liquidity_usd` is the quote side only

Uniswap V3 has no reserves; the bot reads the pool's token balances.
`liquidity_usd` = quote tokens held by the pool × quote USD price. The memecoin side is
**not** counted: it's valued at the pool's own price, which the deployer sets, and a
single-sided position can make a pool look deep while holding almost no WETH.
The full two-sided figure is still sent and logged as `tvl_usd`.

### `owner_renounced`

`true` only when `owner()` returns `0x0` or `0x…dEaD`. A token without `owner()`
(AccessControl, custom admin) is `owner_status: "unknown"` → `owner_renounced: false` → skipped.
Set `REQUIRE_OWNER_RENOUNCED=false` to disable that gate.

## Executor

For every `buy` that passes the gates:

1. **Limits**: `MAX_OPEN_POSITIONS` and `MAX_SESSION_SPEND_QUOTE` (per process run).
2. **Simulation**: `QuoterV2.quoteExactInputSingle` via `eth_call` (no gas, nothing sent).
   Price impact = shortfall versus the mid price, **pool fee excluded**.
   Impact ≥ `MAX_PRICE_IMPACT` (3%) → `rejected_impact`.
3. **Paper mode** (default): position recorded at the simulated price.
4. **Live mode**: `SwapRouter02.multicall(deadline, [exactInputSingle])`,
   `amountOutMinimum = simulated out × (1 − MAX_SLIPPAGE)`, signed locally, sent, waits for the receipt.
   Paying in native ETH (`PAY_WITH_NATIVE=true`) requires `QUOTE_TOKEN == router.WETH9()`;
   otherwise an exact-amount `approve` is sent first. The amount actually received is read from
   the `Transfer` logs (correct for fee-on-transfer tokens).

Each attempt is written to `LEDGER_LOG` with `decision_price` (the mid price in the state Jev saw),
`sim_price`, `fill_price`, `fill_vs_sim_pct`, `fill_vs_decision_pct`, `tx_hash`, `status`.

Jev returns no price prediction (only action, confidence, risk score), so the
"Jev" column for price comparisons is the price Jev was **shown**, not a price Jev predicted.

### LIVE_MODE safeguards

- Only the exact value `true` (case-insensitive) enables it; `1`, `yes`, an empty value → paper.
- At startup, live mode **refuses to run** if anything is missing: key, quoter, router, chain-ID mismatch,
  `WETH9` mismatch, wallet balance below `TRADE_SIZE_QUOTE`.
- No live swap without a successful simulation.
- `_send()` itself re-checks `LIVE_MODE` before signing.
- The dashboard header turns red with a `LIVE` badge.

## Known limits (read before going live)

- **Honeypots are not detected.** A buy simulation says nothing about whether you can *sell*.
  QuoterV2 can't test that either: its simulation never transfers tokens out of your wallet.
  Many memecoin scams pass every gate above and block sells.
- **No exits.** The bot opens positions; it has no sell logic, stop-loss or take-profit.
  Positions are marked to market on the dashboard only, and they live in memory (the ledger file
  is the persistent record; positions are not reloaded on restart).
- **Front-running.** `amountOutMinimum` caps slippage; it does not prevent being sandwiched up to that cap.
- **Jev's inputs.** The question asks about "momentum" and "buy pressure", but a freshly funded pool has
  no trading history and the state has no such data. Calibrate confidence against the decisions log before
  trusting the 0.70 threshold.
- **Latency.** `decision_engine.py` uses a 10 s HTTP timeout; the runner cuts it at
  `DECISION_TIMEOUT_SEC`, and the latency of each call is logged.

## Layout

```
src/memebot/
  config.py           .env loading
  chain.py            RPC reader: PoolCreated, ERC-20 facts, slot0
  market.py           pool snapshot, USD liquidity, state dict
  pricing.py          V3 price / impact math (pure)
  decision.py         engine loader, timeout, output validation
  decision_engine.py  Jev client (hand-written)
  gates.py            hard gates
  executor.py         QuoterV2 simulation, SwapRouter02 swap, ledger
  pipeline.py         main loop
  dashboard.py        rich UI
  journal.py          JSONL writer
tests/                pytest suite with an in-memory chain
```
