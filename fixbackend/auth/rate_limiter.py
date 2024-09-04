from datetime import timedelta
from textwrap import dedent
from typing import Tuple
from fixbackend.types import Redis

from fixcloudutils.util import utc


class LoginRateLimiter:
    def __init__(
        self,
        redis: Redis,
        limit: int,
        window: timedelta,
    ):
        """
        :param redis: Redis connection
        :param requests: Maximum number of requests allowed in the window
        :param window: Time window when the requests are counted
        :param refill_rate: Number of tokens to add to the bucket per second
        """
        self.redis = redis
        self.limit = limit
        self.window = window
        self.refill_rate = limit / window.total_seconds()

    def _new_tokens(self, tokens: int, ttl: int) -> float:
        now = utc().timestamp()
        last_update = now + ttl - self.window.total_seconds()
        time_passed = now - last_update
        return min(self.limit, tokens + time_passed * self.refill_rate)

    async def check(self, username: str) -> bool:
        [tokens, ttl] = await self.redis.eval(
            """ local ttl = redis.call('TTL', KEYS[1])
                local tokens = redis.call('GET', KEYS[1])
                return {tokens, ttl}
            """,
            1,
            f"rate_limit:{username}",
        )

        if tokens is None:
            return True
        tokens = int(tokens)
        ttl = int(ttl)
        new_tokens = self._new_tokens(tokens, ttl)
        return new_tokens >= 1

    async def consume(self, username: str) -> bool:
        [tokens, ttl] = await self.redis.eval(
            dedent(
                """
                local bucket_key = KEYS[1]
                local limit = tonumber(KEYS[2])
                local window = tonumber(KEYS[3])

                local tokens = redis.call('GET', bucket_key)
                local ttl = window
                -- get or create the bucket and ttl
                if not tokens then
                    redis.call('SET', bucket_key, limit)
                    redis.call('EXPIRE', bucket_key, window)
                    tokens = limit
                else
                    ttl = redis.call('TTL', bucket_key)
                    tokens = tonumber(tokens)
                end

                -- decrement the number of tokens in the bucket if possible
                if tokens > 0 then
                    redis.call('DECR', bucket_key)
                end

                return {tokens, ttl}
            """
            ),
            3,
            f"rate_limit:{username}",
            self.limit,
            int(self.window.total_seconds()),
        )

        tokens = int(tokens)
        ttl = int(ttl)

        new_tokens = self._new_tokens(tokens, ttl)

        if new_tokens < 1:
            return False

        return True
