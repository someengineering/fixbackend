from datetime import timedelta
from textwrap import dedent
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
        """
        self.redis = redis
        self.limit = limit
        self.window = window
        self.refill_rate = limit / window.total_seconds()

    def _new_tokens(self, tokens: int, ttl: int) -> float:
        time_passed = self.window.total_seconds() - ttl
        return min(self.limit, tokens + time_passed * self.refill_rate)

    async def check(self, key: str) -> bool:
        [tokens, ttl] = await self.redis.eval(
            """ local ttl = redis.call('TTL', KEYS[1])
                local tokens = redis.call('GET', KEYS[1])
                return {tokens, ttl}
            """,
            1,
            f"rate_limit:{key}",
        )  # type: ignore

        if tokens is None:
            return True
        tokens = int(tokens)
        ttl = int(ttl)
        new_tokens = self._new_tokens(tokens, ttl)
        return new_tokens >= 1

    async def consume(self, key: str) -> bool:
        allowed: int = await self.redis.eval(
            dedent(
                """
                local bucket_key = KEYS[1]
                local limit = tonumber(KEYS[2])
                local window = tonumber(KEYS[3])
                local now = tonumber(KEYS[4])
                local refill_rate = limit / window

                -- get or create the bucket and ttl
                local tokens = redis.call('GET', bucket_key)
                local ttl = window
                if not tokens then
                    redis.call('SET', bucket_key, limit)
                    tokens = limit
                else
                    ttl = redis.call('TTL', bucket_key)
                    tokens = tonumber(tokens)
                end

                -- calculate the new number of tokens
                local time_passed = window - ttl
                local new_tokens = math.min(limit, tokens + time_passed * refill_rate)

                if new_tokens < 1 then
                    return 0
                end

                -- decrement the number of tokens in the bucket and update the ttl
                redis.call('DECR', bucket_key)
                redis.call('EXPIRE', bucket_key, window)

                return 1
            """
            ),
            4,
            f"rate_limit:{key}",
            self.limit,
            int(self.window.total_seconds()),
            utc().timestamp(),
        )  # type: ignore

        return bool(allowed)
