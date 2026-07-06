"""In-process, per-IP sliding-window rate limiter for the assistant endpoint.

Why this exists
---------------
`/api/assistant` can call OpenAI, which costs real money per request. Without
a limiter, a single scraper (or a curious visitor holding down "Ask") can
burn through the daily budget in seconds.

What this does
--------------
Two sliding windows per client IP:
    * `assistant_rate_per_minute` requests in any rolling 60 seconds.
    * `assistant_rate_per_hour`   requests in any rolling 3600 seconds.

If either cap is exceeded we raise HTTP 429 with a `Retry-After` header set
to the number of seconds until the oldest offending request ages out.

Trade-offs
----------
* In-process state. Fine for a single-instance demo; if you scale to multiple
  replicas you'll want Redis (each replica has its own counter otherwise).
* No memory eviction of long-idle IPs. For a demo the dict stays tiny;
  in production you'd add a periodic sweep.
"""

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request

from .config import get_settings

# One rolling window covers everything: hour is the outer bound and the
# minute check is done by counting timestamps within the last 60s of it.
_HOUR_SECONDS = 3600
_MINUTE_SECONDS = 60


class SlidingWindowLimiter:
    """Track timestamps of recent requests per key and answer 'ok / try later'.

    Thread-safe: FastAPI/uvicorn dispatches concurrent requests to a shared
    interpreter, so mutations to the internal dict need a lock.
    """

    def __init__(self) -> None:
        # key -> deque of monotonically-increasing epoch-second timestamps.
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, per_minute: int, per_hour: int) -> Optional[float]:
        """Record an attempt and decide whether it's allowed.

        Args:
            key:        The identity we're rate-limiting (usually client IP).
            per_minute: Max requests in the last 60 seconds.
            per_hour:   Max requests in the last 3600 seconds.

        Returns:
            None if the request is allowed (and has been recorded).
            Otherwise a float: seconds until the caller may retry.
        """
        now = time.time()
        with self._lock:
            bucket = self._buckets[key]

            # Age off anything older than the outer window.
            while bucket and now - bucket[0] > _HOUR_SECONDS:
                bucket.popleft()

            # Hour cap.
            if len(bucket) >= per_hour:
                oldest = bucket[0]
                return _HOUR_SECONDS - (now - oldest)

            # Minute cap: count only timestamps in the last 60s.
            in_minute = [t for t in bucket if now - t <= _MINUTE_SECONDS]
            if len(in_minute) >= per_minute:
                return _MINUTE_SECONDS - (now - in_minute[0])

            bucket.append(now)
            return None

    def reset(self) -> None:
        """Clear all recorded timestamps. Used by tests between cases."""
        with self._lock:
            self._buckets.clear()


# Module-level singleton — see `reset()` for testing.
limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    """Best-effort client-IP extraction.

    Honors `X-Forwarded-For` if present (first hop is the real client when
    the app sits behind a trusted reverse proxy). Falls back to the direct
    connection address.

    Args:
        request: The incoming FastAPI Request.

    Returns:
        A string identifier for the caller.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def assistant_rate_limit(request: Request) -> None:
    """FastAPI dependency: raise 429 if the caller has exceeded the caps.

    Wire this into an endpoint via `dependencies=[Depends(assistant_rate_limit)]`.
    Silent (returns None) on success.
    """
    settings = get_settings()
    key = _client_ip(request)
    retry = limiter.check(
        key,
        per_minute=settings.assistant_rate_per_minute,
        per_hour=settings.assistant_rate_per_hour,
    )
    if retry is not None:
        wait = max(1, int(retry) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {wait}s.",
            headers={"Retry-After": str(wait)},
        )
