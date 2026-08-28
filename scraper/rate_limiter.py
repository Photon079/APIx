"""
Async Rate Limiter
Implements polite rate limiting with jittered delays to avoid overwhelming target servers.
"""

import asyncio
import random
import time
import logging

logger = logging.getLogger("apix.rate_limiter")


class AsyncRateLimiter:
    """
    Rate limiter with randomized jitter delays between requests.
    Ensures polite scraping behavior aligned with ethical guidelines.
    """

    def __init__(
        self,
        min_delay: float = 3.0,
        max_delay: float = 7.0,
        max_requests: int = 20,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_requests = max_requests
        self._request_count = 0
        self._last_request_time: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """
        Wait for an appropriate amount of time before the next request.
        Raises RuntimeError if max requests exceeded.
        """
        async with self._lock:
            if self._request_count >= self.max_requests:
                raise RuntimeError(
                    f"Rate limit exceeded: {self._request_count}/{self.max_requests} "
                    f"requests in this session"
                )

            if self._last_request_time is not None:
                elapsed = time.monotonic() - self._last_request_time
                delay = random.uniform(self.min_delay, self.max_delay)
                remaining = delay - elapsed

                if remaining > 0:
                    logger.info(
                        f"Rate limiter: waiting {remaining:.1f}s "
                        f"(request {self._request_count + 1}/{self.max_requests})"
                    )
                    await asyncio.sleep(remaining)

            self._request_count += 1
            self._last_request_time = time.monotonic()

    @property
    def requests_remaining(self) -> int:
        """Number of requests remaining in this session."""
        return max(0, self.max_requests - self._request_count)

    @property
    def request_count(self) -> int:
        """Total requests made in this session."""
        return self._request_count

    def reset(self) -> None:
        """Reset the rate limiter for a new session."""
        self._request_count = 0
        self._last_request_time = None
        logger.info("Rate limiter reset")

    def get_stats(self) -> dict:
        """Return current rate limiter statistics."""
        return {
            "requests_made": self._request_count,
            "max_requests": self.max_requests,
            "requests_remaining": self.requests_remaining,
            "min_delay_seconds": self.min_delay,
            "max_delay_seconds": self.max_delay,
        }
