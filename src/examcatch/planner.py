"""Two-stage check strategy: when a full schedule check is worth its request (specyfikacja.md, 2.7.1)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from examcatch.criteria import SlotCriteria
from examcatch.models import Slot

_UNSEEN = object()


@dataclass(frozen=True)
class Decision:
    # Nearest slots that already satisfy the criteria, earliest first.
    matches: tuple[Slot, ...]
    # Centers whose full schedule should be fetched.
    full_check_centers: tuple[int, ...]


class CheckPlanner:
    def __init__(self, criteria: SlotCriteria, full_check_min_interval: timedelta):
        self._criteria = criteria
        self._min_interval = full_check_min_interval
        self._previous_nearest: dict[int, object] = {}
        self._last_full_check: dict[int, datetime] = {}

    def decide(
        self, nearest: Mapping[int, Slot | None], now: datetime, before: datetime | None = None
    ) -> Decision:
        """Plans the next step from the nearest slot per center.

        `before` is the start of the current reservation when monitoring for earlier slots.
        """
        matches: list[Slot] = []
        full_check: list[int] = []
        for center_id, slot in nearest.items():
            previous = self._previous_nearest.get(center_id, _UNSEEN)
            self._previous_nearest[center_id] = slot.start if slot else None
            if slot is None or not self._criteria.may_precede_matches(slot, now, before):
                continue
            if self._criteria.matches(slot, now, before):
                matches.append(slot)
                # When searching, the nearest acceptable slot is the best one; nothing more to look for.
                if before is None:
                    continue
            changed = previous is _UNSEEN or previous != slot.start
            last_check = self._last_full_check.get(center_id)
            due = last_check is None or now - last_check >= self._min_interval
            if changed or due:
                full_check.append(center_id)
        return Decision(tuple(sorted(matches)), tuple(full_check))

    def record_full_check(self, center_ids: Iterable[int], now: datetime) -> None:
        for center_id in center_ids:
            self._last_full_check[center_id] = now
