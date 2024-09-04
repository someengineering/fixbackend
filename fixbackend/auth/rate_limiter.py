from datetime import timedelta
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

    async def _get_bucket(self, username: str) -> Tuple[float, int]:
        bucket = await self.redis.hgetall(f"rate_limit:{username}")
        if not bucket:
            return utc().timestamp(), self.limit
        return float(bucket["last_update"]), int(bucket["tokens"])

    async def _update_bucket(self, username: str, last_update: float, tokens: int) -> None:
        await self.redis.hmset(f"rate_limit:{username}", {"last_update": last_update, "tokens": tokens})
        await self.redis.expire(f"rate_limit:{username}", int(2 * self.window.total_seconds()))

    async def check(self, username: str) -> bool:
        last_update, tokens = await self._get_bucket(username)
        now = utc().timestamp()
        time_passed = now - last_update
        new_tokens = min(self.limit, tokens + time_passed * self.refill_rate)
        return new_tokens >= 1

    async def consume(self, username: str) -> bool:
        last_update, tokens = await self._get_bucket(username)
        now = utc().timestamp()
        time_passed = now - last_update
        new_tokens = min(self.limit, tokens + time_passed * self.refill_rate)

        if new_tokens < 1:
            return False

        await self._update_bucket(username, now, int(new_tokens) - 1)
        return True
