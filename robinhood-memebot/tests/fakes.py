from memebot.chain import PoolCreated, Slot0, TokenInfo
from memebot.pricing import Q96

from conftest import POOL, QUOTE, TOKEN


class FakeReader:
    """In-memory stand-in for ChainReader: one pool, liquidity set by the test."""

    w3 = None

    def __init__(self, owner_status="renounced"):
        self.block = 100
        self.events = [PoolCreated(100, "0xabc", TOKEN, QUOTE, 10000, 200, POOL)]
        self.quote_balance = 0
        self.sqrt = 0
        self.owner_status = owner_status

    def chain_id(self):
        return 4663

    def latest_block(self):
        return self.block

    def pool_created_events(self, a, b):
        out = [e for e in self.events if a <= e.block <= b]
        return out

    def token_info(self, token):
        return TokenInfo(token, True, "Meme", "MEME", 18, 10**27, None, self.owner_status)

    def decimals(self, token):
        return 18

    def slot0(self, pool):
        return Slot0(self.sqrt, 0)

    def balance_of(self, token, holder):
        return self.quote_balance if token.lower() == QUOTE else 10**24

    def pool_price(self, pool, token, quote):
        return 0.002

    def fund(self, quote_amount):
        self.sqrt = Q96 // 1000  # raw price 1e-6 quote per token (token is token0)
        self.quote_balance = int(quote_amount * 10**18)
