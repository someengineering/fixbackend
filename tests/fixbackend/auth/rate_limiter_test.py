import pytest
from datetime import timedelta
from fixbackend.auth.rate_limiter import LoginRateLimiter
from fixbackend.types import Redis
import asyncio


@pytest.fixture
def rate_limiter(redis: Redis) -> LoginRateLimiter:
    return LoginRateLimiter(redis=redis, limit=5, window=timedelta(seconds=1))


@pytest.mark.asyncio
async def test_consume(rate_limiter: LoginRateLimiter) -> None:
    assert await rate_limiter.consume("user") is True


@pytest.mark.asyncio
async def test_consume_exceed_limit(rate_limiter: LoginRateLimiter) -> None:
    # Ensure the bucket is empty initially
    for _ in range(5):
        assert await rate_limiter.consume("user") is True
    assert await rate_limiter.consume("user") is False
    # Wait for the window to expire
    await asyncio.sleep(1)
    assert await rate_limiter.consume("user") is True
