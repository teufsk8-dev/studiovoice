"""Read-only access to Robinhood Chain: factory events, ERC-20 facts, pool prices."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from web3 import Web3
from web3.exceptions import ContractLogicError

from . import abis
from .pricing import from_raw, quote_per_token

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEAD_ADDRESSES = {ZERO_ADDRESS, "0x000000000000000000000000000000000000dEaD"}


@dataclass(frozen=True)
class PoolCreated:
    block: int
    tx_hash: str
    token0: str
    token1: str
    fee: int
    tick_spacing: int
    pool: str


@dataclass(frozen=True)
class TokenInfo:
    address: str
    has_code: bool
    name: str | None
    symbol: str | None
    decimals: int | None
    total_supply_raw: int | None
    owner: str | None
    # "renounced" (owner is 0x0 / 0xdead), "active", or "unknown" (no owner()).
    owner_status: str

    @property
    def owner_renounced(self) -> bool:
        return self.owner_status == "renounced"

    @property
    def total_supply(self) -> float | None:
        if self.total_supply_raw is None or self.decimals is None:
            return None
        return from_raw(self.total_supply_raw, self.decimals)


@dataclass(frozen=True)
class Slot0:
    sqrt_price_x96: int
    tick: int

    @property
    def initialized(self) -> bool:
        return self.sqrt_price_x96 != 0


def _word_to_address(word: bytes) -> str:
    return Web3.to_checksum_address(word[-20:])


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= 1 << (bits - 1) else value


def decode_pool_created(log) -> PoolCreated:
    """Decode a raw PoolCreated log (indexed token0, token1, fee; data tickSpacing, pool)."""
    topics = log["topics"]
    data = bytes(log["data"])
    return PoolCreated(
        block=log["blockNumber"],
        tx_hash=Web3.to_hex(log["transactionHash"]),
        token0=_word_to_address(bytes(topics[1])),
        token1=_word_to_address(bytes(topics[2])),
        fee=int.from_bytes(bytes(topics[3]), "big"),
        tick_spacing=_signed(int.from_bytes(data[0:32], "big"), 256),
        pool=_word_to_address(data[32:64]),
    )


class ChainReader:
    def __init__(self, rpc_url: str, factory: str, timeout: float = 10.0):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        self.factory = Web3.to_checksum_address(factory)
        self.pool_created_topic = Web3.to_hex(Web3.keccak(text=abis.POOL_CREATED_SIGNATURE))

    # --- chain -----------------------------------------------------------------

    def chain_id(self) -> int:
        return self.w3.eth.chain_id

    def latest_block(self) -> int:
        return self.w3.eth.block_number

    def pool_created_events(self, from_block: int, to_block: int) -> list[PoolCreated]:
        logs = self.w3.eth.get_logs(
            {
                "address": self.factory,
                "topics": [self.pool_created_topic],
                "fromBlock": from_block,
                "toBlock": to_block,
            }
        )
        return [decode_pool_created(log) for log in logs]

    # --- ERC-20 -----------------------------------------------------------------

    def _call(self, address: str, abi: list, fn: str, *args):
        """Call a view function; None if it reverts or doesn't exist."""
        contract = self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        try:
            return getattr(contract.functions, fn)(*args).call()
        except (ContractLogicError, ValueError, OverflowError):
            # ValueError covers empty return data (function not implemented).
            return None
        except Exception as exc:  # web3 raises various decoding errors
            if "Could not decode" in str(exc) or "execution reverted" in str(exc):
                return None
            raise

    def has_code(self, address: str) -> bool:
        return len(self.w3.eth.get_code(Web3.to_checksum_address(address))) > 0

    @lru_cache(maxsize=4096)
    def decimals(self, token: str) -> int | None:
        return self._call(token, abis.ERC20, "decimals")

    @lru_cache(maxsize=4096)
    def symbol(self, token: str) -> str | None:
        return self._call(token, abis.ERC20, "symbol")

    def balance_of(self, token: str, holder: str) -> int | None:
        return self._call(token, abis.ERC20, "balanceOf", Web3.to_checksum_address(holder))

    def token_info(self, token: str) -> TokenInfo:
        token = Web3.to_checksum_address(token)
        code = self.has_code(token)
        if not code:
            return TokenInfo(token, False, None, None, None, None, None, "unknown")
        owner = self._call(token, abis.OWNABLE, "owner")
        if owner is None:
            status = "unknown"
        elif owner in DEAD_ADDRESSES:
            status = "renounced"
        else:
            status = "active"
        return TokenInfo(
            address=token,
            has_code=True,
            name=self._call(token, abis.ERC20, "name"),
            symbol=self.symbol(token),
            decimals=self.decimals(token),
            total_supply_raw=self._call(token, abis.ERC20, "totalSupply"),
            owner=owner,
            owner_status=status,
        )

    # --- Uniswap V3 pools ---------------------------------------------------------

    def slot0(self, pool: str) -> Slot0:
        result = self._call(pool, abis.POOL_V3, "slot0")
        if result is None:
            return Slot0(0, 0)
        return Slot0(sqrt_price_x96=result[0], tick=result[1])

    def pool_price(self, pool: str, token: str, quote: str) -> float:
        """Current price of `token` in `quote` units, from slot0."""
        s0 = self.slot0(pool)
        t_dec, q_dec = self.decimals(token), self.decimals(quote)
        if not s0.initialized or t_dec is None or q_dec is None:
            return 0.0
        token_is_token0 = int(token, 16) < int(quote, 16)
        return quote_per_token(s0.sqrt_price_x96, token_is_token0, t_dec, q_dec)

    def pool_tokens(self, pool: str) -> tuple[str, str, int]:
        return (
            self._call(pool, abis.POOL_V3, "token0"),
            self._call(pool, abis.POOL_V3, "token1"),
            self._call(pool, abis.POOL_V3, "fee"),
        )
