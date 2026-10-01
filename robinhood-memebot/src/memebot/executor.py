"""Buy executor: QuoterV2 simulation, then a SwapRouter02 swap in live mode.

With LIVE_MODE != "true" nothing is ever signed or sent: buys are recorded as
paper positions at the simulated price (or the pool mid price if no quoter is
configured). Every attempt, whatever its outcome, goes to the ledger.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import asdict, dataclass

from eth_account import Account
from web3 import Web3

from . import abis
from .chain import ChainReader
from .config import Config
from .decision import Decision
from .journal import Journal
from .market import PoolSnapshot
from .pricing import from_raw, price_impact, to_raw


class LiveModeRefused(RuntimeError):
    """Raised at startup when LIVE_MODE=true but the setup isn't safe to trade."""


@dataclass
class Position:
    id: int
    opened_at: float
    mode: str
    symbol: str | None
    token: str
    pool: str
    fee: int
    token_is_token0: bool
    amount_in_quote: float
    tokens: float
    entry_price: float  # quote per token, actual (live) or simulated (paper) fill
    current_price: float
    tx_hash: str | None = None

    @property
    def pnl_pct(self) -> float:
        return (self.current_price / self.entry_price - 1) * 100 if self.entry_price else 0.0


def _pct_diff(actual: float | None, reference: float | None) -> float | None:
    if not actual or not reference:
        return None
    return round((actual / reference - 1) * 100, 4)


class Executor:
    def __init__(self, cfg: Config, reader: ChainReader, ledger: Journal):
        self.cfg = cfg
        self.reader = reader
        self.w3 = reader.w3
        self.ledger = ledger
        self.account = Account.from_key(cfg.private_key) if cfg.private_key else None
        self.positions: list[Position] = []
        self.session_spend = 0.0
        self._ids = itertools.count(1)
        self.transfer_topic = Web3.keccak(text=abis.TRANSFER_SIGNATURE)

    @property
    def mode(self) -> str:
        return "live" if self.cfg.live_mode else "paper"

    # --- startup checks -------------------------------------------------------------

    def preflight(self) -> list[str]:
        """Problems that block live trading. Raises LiveModeRefused in live mode."""
        cfg, problems = self.cfg, []
        if not cfg.quote_token:
            problems.append("QUOTE_TOKEN is not set")
        if not cfg.quoter_v2:
            problems.append("QUOTER_V2_ADDRESS is not set (simulation is mandatory before a live swap)")
        if not cfg.live_mode:
            return problems
        if not self.account:
            problems.append("PRIVATE_KEY is not set")
        if not cfg.swap_router02:
            problems.append("SWAP_ROUTER02_ADDRESS is not set")
        if not problems:
            chain_id = self.reader.chain_id()
            if chain_id != cfg.chain_id:
                problems.append(f"RPC chain id {chain_id} != CHAIN_ID {cfg.chain_id}")
            quote = Web3.to_checksum_address(cfg.quote_token)
            if cfg.pay_with_native:
                weth9 = self._router().functions.WETH9().call()
                if Web3.to_checksum_address(weth9) != quote:
                    problems.append(f"PAY_WITH_NATIVE needs QUOTE_TOKEN == router.WETH9() ({weth9})")
                balance = from_raw(self.w3.eth.get_balance(self.account.address), 18)
            else:
                balance = from_raw(self.reader.balance_of(quote, self.account.address) or 0,
                                   self.reader.decimals(quote) or 18)
            if balance < cfg.trade_size_quote:
                problems.append(f"wallet balance {balance} < TRADE_SIZE_QUOTE {cfg.trade_size_quote}")
        if problems:
            raise LiveModeRefused("LIVE_MODE refused: " + "; ".join(problems))
        return problems

    # --- simulation -----------------------------------------------------------------

    def simulate(self, snap: PoolSnapshot) -> dict | None:
        """QuoterV2.quoteExactInputSingle via eth_call: free, nothing is sent."""
        if not self.cfg.quoter_v2:
            return None
        quoter = self.w3.eth.contract(address=Web3.to_checksum_address(self.cfg.quoter_v2), abi=abis.QUOTER_V2)
        amount_in = to_raw(self.cfg.trade_size_quote, snap.quote_decimals)
        out_raw, sqrt_after, ticks, gas = quoter.functions.quoteExactInputSingle(
            (snap.quote, snap.token.address, amount_in, snap.fee, 0)
        ).call()
        tokens_out = from_raw(out_raw, snap.token.decimals or 18)
        return {
            "amount_out_raw": out_raw,
            "tokens_out": tokens_out,
            "price": self.cfg.trade_size_quote / tokens_out if tokens_out else None,
            "price_impact": price_impact(self.cfg.trade_size_quote, tokens_out, snap.price_quote, snap.fee),
            "ticks_crossed": ticks,
            "gas_estimate": gas,
        }

    # --- buy --------------------------------------------------------------------------

    def _limits_problem(self) -> str | None:
        open_count = len(self.positions)
        if open_count >= self.cfg.max_open_positions:
            return f"max open positions reached ({open_count})"
        if self.session_spend + self.cfg.trade_size_quote > self.cfg.max_session_spend_quote + 1e-12:
            return f"session spend cap reached ({self.session_spend}/{self.cfg.max_session_spend_quote})"
        return None

    def buy(self, snap: PoolSnapshot, decision: Decision) -> dict:
        record = {
            "ts": time.time(),
            "mode": self.mode,
            "pool": snap.pool,
            "token": snap.token.address,
            "symbol": snap.token.symbol,
            "fee": snap.fee,
            "amount_in_quote": self.cfg.trade_size_quote,
            "jev": decision.as_dict(),
            # Jev returns no price; this is the mid price it was shown in the state.
            "decision_price": snap.price_quote,
            "sim_price": None,
            "sim_price_impact": None,
            "fill_price": None,
            "tokens": None,
            "tx_hash": None,
            "status": None,
            "error": None,
        }
        try:
            self._buy(snap, record)
        except Exception as exc:
            record["status"], record["error"] = "error", f"{type(exc).__name__}: {exc}"
        record["fill_vs_sim_pct"] = _pct_diff(record["fill_price"], record["sim_price"])
        record["fill_vs_decision_pct"] = _pct_diff(record["fill_price"], record["decision_price"])
        self.ledger.write(record)
        return record

    def _buy(self, snap: PoolSnapshot, record: dict) -> None:
        problem = self._limits_problem()
        if problem:
            record["status"], record["error"] = "refused_limits", problem
            return

        sim = self.simulate(snap)
        if sim:
            record["sim_price"], record["sim_price_impact"] = sim["price"], sim["price_impact"]
            if sim["price_impact"] >= self.cfg.max_price_impact:
                record["status"] = "rejected_impact"
                record["error"] = f"impact {sim['price_impact']:.2%} >= {self.cfg.max_price_impact:.2%}"
                return

        if not self.cfg.live_mode:
            fill = sim["price"] if sim else snap.price_quote
            tokens = sim["tokens_out"] if sim else (self.cfg.trade_size_quote / fill if fill else 0)
            record.update(status="paper", fill_price=fill, tokens=tokens)
            self._open(snap, record)
            return

        if not sim:
            record["status"], record["error"] = "refused", "no simulation available; live swap refused"
            return
        record.update(self._swap(snap, sim))
        if record["status"] == "filled":
            self._open(snap, record)

    def _open(self, snap: PoolSnapshot, record: dict) -> None:
        self.session_spend += self.cfg.trade_size_quote
        self.positions.append(
            Position(
                id=next(self._ids),
                opened_at=record["ts"],
                mode=record["mode"],
                symbol=snap.token.symbol,
                token=snap.token.address,
                pool=snap.pool,
                fee=snap.fee,
                token_is_token0=int(snap.token.address, 16) < int(snap.quote, 16),
                amount_in_quote=self.cfg.trade_size_quote,
                tokens=record["tokens"],
                entry_price=record["fill_price"],
                current_price=record["fill_price"],
                tx_hash=record["tx_hash"],
            )
        )

    # --- live swap ----------------------------------------------------------------------

    def _router(self):
        return self.w3.eth.contract(address=Web3.to_checksum_address(self.cfg.swap_router02), abi=abis.SWAP_ROUTER02)

    def _send(self, fn, value: int = 0):
        if not self.cfg.live_mode:  # second line of defence, never reached in paper mode
            raise LiveModeRefused("refusing to send a transaction: LIVE_MODE is not 'true'")
        tx = fn.build_transaction(
            {
                "from": self.account.address,
                "value": value,
                "nonce": self.w3.eth.get_transaction_count(self.account.address, "pending"),
                "chainId": self.cfg.chain_id,
            }
        )
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.cfg.tx_timeout)
        return Web3.to_hex(tx_hash), receipt

    def _ensure_allowance(self, token: str, amount: int) -> None:
        erc20 = self.w3.eth.contract(address=token, abi=abis.ERC20)
        router = self._router().address
        if erc20.functions.allowance(self.account.address, router).call() >= amount:
            return
        # Exact-amount approval: no standing unlimited allowance on the wallet.
        _, receipt = self._send(erc20.functions.approve(router, amount))
        if receipt["status"] != 1:
            raise RuntimeError("approve transaction reverted")

    def _swap(self, snap: PoolSnapshot, sim: dict) -> dict:
        amount_in = to_raw(self.cfg.trade_size_quote, snap.quote_decimals)
        min_out = int(sim["amount_out_raw"] * (1 - self.cfg.max_slippage))
        params = (snap.quote, snap.token.address, snap.fee, self.account.address, amount_in, min_out, 0)
        router = self._router()
        if not self.cfg.pay_with_native:
            self._ensure_allowance(snap.quote, amount_in)
        call = router.encode_abi("exactInputSingle", args=[params])
        deadline = int(time.time()) + self.cfg.tx_deadline
        value = amount_in if self.cfg.pay_with_native else 0
        tx_hash, receipt = self._send(router.functions.multicall(deadline, [call]), value=value)
        if receipt["status"] != 1:
            return {"status": "reverted", "tx_hash": tx_hash, "gas_used": receipt["gasUsed"]}
        received = self._received(receipt, snap.token.address)
        tokens = from_raw(received, snap.token.decimals or 18)
        return {
            "status": "filled",
            "tx_hash": tx_hash,
            "block": receipt["blockNumber"],
            "gas_used": receipt["gasUsed"],
            "min_out_raw": str(min_out),
            "tokens": tokens,
            "fill_price": self.cfg.trade_size_quote / tokens if tokens else None,
        }

    def _received(self, receipt, token: str) -> int:
        """Tokens actually credited to the wallet (handles fee-on-transfer tokens)."""
        me = self.account.address.lower()
        total = 0
        for log in receipt["logs"]:
            topics = log["topics"]
            if (
                log["address"].lower() == token.lower()
                and len(topics) == 3
                and bytes(topics[0]) == bytes(self.transfer_topic)
                and "0x" + bytes(topics[2])[-20:].hex() == me
            ):
                total += int.from_bytes(bytes(log["data"]), "big")
        return total

    # --- valuation ------------------------------------------------------------------------

    def mark_to_market(self) -> None:
        for pos in self.positions:
            try:
                quote = self.cfg.quote_token
                price = self.reader.pool_price(pos.pool, pos.token, quote)
                if price:
                    pos.current_price = price
            except Exception:
                pass  # keep last known price; the dashboard shows it as-is

    def positions_as_dicts(self) -> list[dict]:
        return [asdict(p) | {"pnl_pct": p.pnl_pct} for p in self.positions]
