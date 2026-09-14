"""Tracking of the service's per-endpoint request limits (specyfikacja.md, 2.7.2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from examcatch.models import WARSAW


@dataclass
class EndpointBudget:
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None

    def update(self, headers: Mapping[str, str]) -> None:
        normalized = {key.lower(): value for key, value in headers.items()}
        limit = _parse_int(normalized.get("x-ratelimit-limit"))
        remaining = _parse_int(normalized.get("x-ratelimit-remaining"))
        reset = _parse_int(normalized.get("x-ratelimit-reset"))
        if limit is not None:
            self.limit = limit
        if remaining is not None:
            self.remaining = remaining
        if reset is not None:
            self.reset_at = datetime.fromtimestamp(reset, WARSAW)

    def remaining_at(self, now: datetime) -> int | None:
        """Requests left at `now`, or None when unknown. The window is fixed, so it refills at `reset_at`."""
        if self.reset_at is not None and now >= self.reset_at:
            return self.limit
        return self.remaining

    def can_spend(self, now: datetime, reserve: int = 0) -> bool:
        """Whether one more request leaves at least `reserve` requests in the current window."""
        remaining = self.remaining_at(now)
        return remaining is None or remaining > reserve


class RateLimiter:
    def __init__(self) -> None:
        self._budgets: dict[str, EndpointBudget] = {}

    def budget(self, endpoint: str) -> EndpointBudget:
        return self._budgets.setdefault(endpoint, EndpointBudget())

    def update(self, endpoint: str, headers: Mapping[str, str]) -> None:
        self.budget(endpoint).update(headers)

    def can_spend(self, endpoint: str, now: datetime, reserve: int = 0) -> bool:
        return self.budget(endpoint).can_spend(now, reserve)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
