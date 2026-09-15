"""Choosing the next check within the service's request limits (specyfikacja.md, 2.7.1-2.7.3).

The nearest-slot and full schedule endpoints have separate limits, so checks alternate between them. Extra checks
are planned for when a competitor's unpaid hold on a slot we lost may expire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from examcatch.criteria import SlotCriteria
from examcatch.models import Slot

_UNSEEN = object()


@dataclass(frozen=True)
class PlannedCheck:
    """A nearest-slot check of all centers (center_id None) or a full schedule check of one center."""

    center_id: int | None = None

    @property
    def is_full(self) -> bool:
        return self.center_id is not None


NEAREST_CHECK = PlannedCheck()


class CheckScheduler:
    def __init__(
        self,
        criteria: SlotCriteria,
        nearest_horizon: timedelta,
        hold: timedelta,
        release_checks_in_window: int,
        release_check_grace: timedelta,
    ):
        self._criteria = criteria
        self._nearest_horizon = nearest_horizon
        self._hold = hold
        self._release_checks_in_window = max(release_checks_in_window, 1)
        self._release_check_grace = release_check_grace
        self._previous_nearest: dict[int, object] = {}
        self._urgent_full: list[int] = []
        self._release_checks: list[tuple[datetime, int]] = []
        self._last_seen: dict[tuple[int, datetime], datetime] = {}
        self._full_rotation = 0
        self._full_next = False

    def choose(
        self,
        now: datetime,
        center_ids: Sequence[int],
        can_nearest: bool,
        can_full: bool,
        before: datetime | None = None,
    ) -> PlannedCheck | None:
        """Picks the next check, or None when neither endpoint has requests to spare.

        `before` is the start of the current reservation when monitoring for earlier slots.
        """
        due = sorted((at, center_id) for at, center_id in self._release_checks if at <= now and center_id in center_ids)
        if due and (can_full or can_nearest):
            self._release_checks.remove(due[0])
            return PlannedCheck(due[0][1]) if can_full else NEAREST_CHECK

        self._urgent_full = [center_id for center_id in self._urgent_full if center_id in center_ids]
        if self._urgent_full and can_full:
            return PlannedCheck(self._urgent_full.pop(0))

        useful = [center_id for center_id in center_ids if self._full_check_useful(center_id, now, before)]
        if can_full and useful and (self._full_next or not can_nearest):
            self._full_next = False
            center_id = useful[self._full_rotation % len(useful)]
            self._full_rotation += 1
            return PlannedCheck(center_id)
        if can_nearest:
            self._full_next = True
            return NEAREST_CHECK
        return None

    def record_nearest(
        self, nearest: Mapping[int, Slot | None], now: datetime, before: datetime | None = None
    ) -> list[Slot]:
        """Stores the nearest slot per center and returns the acceptable ones, earliest first."""
        matches: list[Slot] = []
        for center_id, slot in nearest.items():
            previous = self._previous_nearest.get(center_id, _UNSEEN)
            self._previous_nearest[center_id] = slot
            if slot is None:
                continue
            if self._criteria.matches(slot, now, before):
                matches.append(slot)
                self._last_seen[slot.key] = now
                # When searching, the nearest acceptable slot is the best one; nothing more to look for.
                if before is None:
                    continue
            changed = not isinstance(previous, Slot) or previous.start != slot.start
            if changed and self._criteria.may_precede_matches(slot, now, before) and center_id not in self._urgent_full:
                self._urgent_full.append(center_id)
        return sorted(matches)

    def record_full(
        self, center_id: int, slots: Sequence[Slot], now: datetime, before: datetime | None = None
    ) -> list[Slot]:
        """Returns the acceptable slots of a full schedule, earliest first."""
        if center_id in self._urgent_full:
            self._urgent_full.remove(center_id)
        matches = sorted(slot for slot in slots if self._criteria.matches(slot, now, before))
        for slot in matches:
            self._last_seen[slot.key] = now
        return matches

    def record_lost_slot(self, slot: Slot, now: datetime) -> list[datetime]:
        """Plans checks for when someone else's unpaid hold on the slot may expire; returns their times.

        The competitor reserved the slot between our last sighting and now, so their unpaid reservation is cancelled
        between last sighting + hold and now + hold. Checks are spread evenly over that window, ending at its upper
        bound, plus one check a grace period later in case the service cancels with a delay.
        """
        earliest = self._last_seen.get(slot.key, now) + self._hold
        latest = now + self._hold
        count = self._release_checks_in_window
        if count == 1 or latest <= earliest:
            moments = {latest}
        else:
            step = (latest - earliest) / (count - 1)
            moments = {earliest + step * index for index in range(count)}
        if self._release_check_grace > timedelta(0):
            moments.add(latest + self._release_check_grace)
        planned = sorted(moment for moment in moments if moment > now)
        self._release_checks.extend((moment, slot.center_id) for moment in planned)
        return planned

    def next_wakeup(self, now: datetime, interval: timedelta) -> datetime:
        """When to check next: after the regular interval, or earlier for a planned release check."""
        return min([now + interval, *(at for at, _ in self._release_checks if at > now)])

    def _full_check_useful(self, center_id: int, now: datetime, before: datetime | None) -> bool:
        nearest = self._previous_nearest.get(center_id, _UNSEEN)
        if nearest is _UNSEEN:
            return True
        if nearest is None:
            # Nothing within the nearest-slot endpoint's horizon; only a window reaching beyond it can hold slots.
            return self._criteria.window_end(now) > now + self._nearest_horizon
        assert isinstance(nearest, Slot)
        return self._criteria.may_precede_matches(nearest, now, before)
