"""Domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from examcatch.service import BASE_URL

WARSAW = ZoneInfo("Europe/Warsaw")


def now() -> datetime:
    return datetime.now(WARSAW)


@dataclass(frozen=True, order=True)
class Slot:
    """A free practical exam slot at an exam center. Ordered by start time."""

    start: datetime
    center_id: int
    center_name: str = field(compare=False)
    places: int = field(compare=False)
    exam_id: str | None = field(default=None, compare=False)

    @property
    def key(self) -> tuple[int, datetime]:
        return self.center_id, self.start

    def describe(self) -> str:
        return f"{self.center_name}, {self.start:%d.%m.%Y %H:%M} ({self.places} free places)"


@dataclass(frozen=True)
class Profile:
    """Candidate driver profile (PKK) used for reservations."""

    number: str
    category: str
    profile_type: str = "Pkk"


@dataclass(frozen=True)
class Reservation:
    """A slot held for the user until payment."""

    id: str
    slot: Slot
    reserved_at: datetime

    @property
    def link(self) -> str:
        # The service has no confirmed per-reservation URL; reservations are listed under "Lista moich spraw".
        return f"{BASE_URL}/cases"
