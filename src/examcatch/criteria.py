"""Rules deciding whether a slot is acceptable (specyfikacja.md, section 2.4)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from examcatch.config import SearchConfig
from examcatch.models import Slot


class SlotCriteria:
    def __init__(self, search: SearchConfig, center_ids: Iterable[int]):
        self._search = search
        self._center_ids = frozenset(center_ids)

    def earliest_start(self, now: datetime) -> datetime:
        return now + self._search.min_lead_time

    def window_end(self, now: datetime) -> datetime:
        return now + timedelta(days=self._search.window_days)

    def search_start_date(self, now: datetime) -> date:
        return self.earliest_start(now).date()

    def rejection_reason(self, slot: Slot, now: datetime, before: datetime | None = None) -> str | None:
        """Returns why the slot is not acceptable, or None when it is.

        `before` is the start of the current reservation; only strictly earlier slots are acceptable then.
        """
        if slot.center_id not in self._center_ids:
            return "exam center is not configured"
        start_time = slot.start.time()
        if not self._search.start_time_from <= start_time <= self._search.start_time_to:
            return "start time is outside the allowed range"
        if slot.start < self.earliest_start(now):
            return "starts too soon"
        if slot.start > self.window_end(now):
            return "outside the search window"
        if before is not None and slot.start >= before:
            return "not earlier than the current reservation"
        return None

    def matches(self, slot: Slot, now: datetime, before: datetime | None = None) -> bool:
        return self.rejection_reason(slot, now, before) is None

    def may_precede_matches(self, slot: Slot, now: datetime, before: datetime | None = None) -> bool:
        """Whether acceptable slots can exist at or after this slot, given it is the nearest one at its center.

        When the nearest slot already lies beyond the window (or the current reservation), nothing at that
        center can be acceptable, so a full schedule check would be wasted.
        """
        if slot.start > self.window_end(now):
            return False
        return before is None or slot.start < before
