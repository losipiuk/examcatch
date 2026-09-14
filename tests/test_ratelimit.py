from datetime import datetime, timedelta

from examcatch.models import WARSAW
from examcatch.ratelimit import RateLimiter

NOW = datetime(2026, 9, 14, 20, 0, tzinfo=WARSAW)
RESET = NOW + timedelta(hours=1)


def headers(remaining: int, reset: datetime = RESET) -> dict[str, str]:
    return {
        "x-ratelimit-limit": "10",
        "X-RateLimit-Remaining": str(remaining),
        "x-ratelimit-reset": str(int(reset.timestamp())),
    }


def test_unknown_budget_allows_requests():
    assert RateLimiter().can_spend("/a", NOW, reserve=2)


def test_keeps_reserve():
    limiter = RateLimiter()
    limiter.update("/a", headers(remaining=3))
    assert limiter.can_spend("/a", NOW, reserve=2)

    limiter.update("/a", headers(remaining=2))
    assert not limiter.can_spend("/a", NOW, reserve=2)
    assert limiter.can_spend("/a", NOW, reserve=1)


def test_budget_refills_after_reset():
    limiter = RateLimiter()
    limiter.update("/a", headers(remaining=0))
    assert not limiter.can_spend("/a", NOW)
    assert limiter.can_spend("/a", RESET, reserve=2)
    assert limiter.budget("/a").reset_at == RESET


def test_endpoints_are_independent():
    limiter = RateLimiter()
    limiter.update("/a", headers(remaining=0))
    assert limiter.can_spend("/b", NOW)


def test_ignores_malformed_headers():
    limiter = RateLimiter()
    limiter.update("/a", {"x-ratelimit-remaining": "lots"})
    assert limiter.budget("/a").remaining is None
    assert limiter.can_spend("/a", NOW)
