"""Main loop: search, reserve, wait for payment, monitor for earlier slots (specyfikacja.md, 2.2-2.8)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, timedelta

from playwright.sync_api import Error as PlaywrightError

from examcatch.api import ApiError, RateLimitedError, ServiceApi, SessionExpiredError
from examcatch.browser import Session
from examcatch.config import Config
from examcatch.console import ConsoleInput
from examcatch.criteria import SlotCriteria
from examcatch.errors import FatalError, ReservationError
from examcatch.models import Profile, Reservation, Slot, now
from examcatch.notify import Notifier
from examcatch.planner import CheckPlanner
from examcatch.ratelimit import RateLimiter
from examcatch.reservation import ReservationFlow
from examcatch.service import ALL_SCHEDULE_PATH, NEAREST_SCHEDULE_HORIZON, NEAREST_SCHEDULE_PATH

PAID_COMMAND = "paid"
# The reservation form searches from today + 2 days by default; used if the API rejects earlier start dates.
SERVICE_DEFAULT_START_OFFSET = timedelta(days=2)


class App:
    def __init__(
        self,
        config: Config,
        session: Session,
        api: ServiceApi,
        limiter: RateLimiter,
        flow: ReservationFlow,
        notifier: Notifier,
        console: ConsoleInput,
        clock: Callable[[], datetime] = now,
    ):
        self._config = config
        self._session = session
        self._api = api
        self._limiter = limiter
        self._flow = flow
        self._notifier = notifier
        self._console = console
        self._clock = clock
        self._center_ids = tuple(center.id for center in config.centers)
        self._center_names = {center.id: center.name for center in config.centers}
        self._criteria = SlotCriteria(config.search, self._center_ids)
        self._planner = self._new_planner()
        self._profile: Profile | None = None
        self._use_service_default_start = False

    def run(self) -> None:
        self._session.ensure_logged_in()
        self._profile = self._with_session(self._load_profile)
        while True:
            reservation = self._search_until_reserved()
            if self._await_payment(reservation):
                self._monitor(reservation)

    def dry_run(self) -> None:
        """Tests the reservation form up to the summary step without reserving anything."""
        self._session.ensure_logged_in()
        self._profile = self._with_session(self._load_profile)

        def nearest() -> dict[int, Slot | None]:
            self._session.ensure_service_page()
            return self._nearest_slots(self._clock())

        try:
            slots = sorted(slot for slot in self._with_session(nearest).values() if slot)
        except (ApiError, PlaywrightError) as e:
            self._notifier.info(f"Could not read the nearest slots: {e}")
            slots = []
        if not slots:
            self._notifier.info("No nearest slots (the endpoint looks about a month ahead); reading full schedules.")
            slots = self._any_full_schedule_slots()
        if not slots:
            self._notifier.info("No practical exam slots are offered at the configured centers; nothing to test.")
            return
        current = self._clock()
        matching = [slot for slot in slots if self._criteria.matches(slot, current)]
        slot = (matching or slots)[0]
        reason = "meets the criteria" if matching else "does not meet the criteria, used only to test the form"
        self._notifier.info(f"Dry run with {slot.describe()} ({reason}).")
        try:
            self._with_session(lambda: self._flow.preview(slot))
        except ReservationError as e:
            self._notifier.info(f"Dry run failed: {e}")
            return
        self._notifier.info("Dry run finished. Nothing was submitted.")

    def _any_full_schedule_slots(self) -> list[Slot]:
        """Slots from the first configured center with any, for the dry run."""
        current = self._clock()
        for center_id in self._center_ids:
            try:
                slots = self._with_session(
                    lambda: self._api.all_practice_slots(self._require_profile(), center_id, self._start_date(current))
                )
            except (ApiError, PlaywrightError) as e:
                self._notifier.info(f"Could not read the full schedule of center {center_id}: {e}")
                continue
            if slots:
                return slots
        return []

    def _load_profile(self) -> Profile:
        self._session.ensure_service_page()
        profiles = self._api.pkk_profiles()
        if len(profiles) != 1:
            raise FatalError(f"Expected exactly one PKK profile available for reservation, found {len(profiles)}")
        self._notifier.info(f"Using the PKK profile for category {profiles[0].category}.")
        return profiles[0]

    def _search_until_reserved(self) -> Reservation:
        self._planner = self._new_planner()
        self._notifier.info("Searching for a slot.")
        while True:
            for slot in self._check(before=None):
                reservation = self._reserve(slot)
                if reservation is not None:
                    return reservation
            self._session.wait(self._config.polling.detector_interval)

    def _reserve(self, slot: Slot) -> Reservation | None:
        self._notifier.info(f"Reserving {slot.describe()}.")
        try:
            reservation = self._with_session(lambda: self._flow.reserve(slot))
        except ReservationError as e:
            self._notifier.info(f"Could not reserve {slot.describe()}: {e}")
            return None
        deadline = reservation.reserved_at + self._config.payment.hold
        self._notifier.important(
            "Exam reserved",
            f"{slot.describe()}\n"
            f"Reservation number: {reservation.id}\n"
            f"Pay by {deadline:%H:%M}: {reservation.link}\n"
            f"After paying, type '{PAID_COMMAND}' and press Enter in the ExamCatch terminal.",
        )
        return reservation

    def _await_payment(self, reservation: Reservation) -> bool:
        """Reminds about the payment until the user confirms it; returns False when the hold expires."""
        payment = self._config.payment
        deadline = reservation.reserved_at + payment.hold
        next_reminder = reservation.reserved_at + payment.reminder_interval
        self._console.drain()
        while (current := self._clock()) < deadline:
            command = self._console.poll()
            if command is not None:
                if command.lower() == PAID_COMMAND:
                    self._notifier.info("Payment confirmed. Watching for earlier slots.")
                    return True
                self._notifier.info(f"Unknown command {command!r}. Type '{PAID_COMMAND}' after paying.")
            if current >= next_reminder:
                minutes_left = math.ceil((deadline - current).total_seconds() / 60)
                self._notifier.important(
                    "Payment reminder",
                    f"{reservation.slot.describe()}\n{minutes_left} min left to pay: {reservation.link}",
                )
                next_reminder += payment.reminder_interval
            self._session.wait(timedelta(seconds=1))
        self._notifier.important(
            "Reservation expired",
            f"Payment for {reservation.slot.describe()} was not confirmed in time. Searching again.",
        )
        return False

    def _monitor(self, reservation: Reservation) -> None:
        """Notifies about every new slot earlier than the reservation; runs until the application is stopped."""
        self._planner = self._new_planner()
        notified: set[tuple[int, datetime]] = set()
        while True:
            for slot in self._check(before=reservation.slot.start):
                if slot.key in notified:
                    continue
                notified.add(slot.key)
                self._notifier.important(
                    "Earlier slot available",
                    f"{slot.describe()}\nYour reservation: {reservation.slot.describe()}",
                )
            self._session.wait(self._config.polling.detector_interval)

    def _check(self, before: datetime | None) -> list[Slot]:
        """Acceptable slots found in this cycle, earliest first. Failures are reported and yield no slots."""
        try:
            return self._with_session(lambda: self._check_once(before))
        except RateLimitedError as e:
            self._notifier.info(f"Request limit exceeded{_until(e.reset_at)}.")
        except (ApiError, PlaywrightError) as e:
            self._notifier.info(f"Check failed, retrying in the next cycle: {e}")
        return []

    def _check_once(self, before: datetime | None) -> list[Slot]:
        self._session.ensure_service_page()
        current = self._clock()
        if not self._limiter.can_spend(NEAREST_SCHEDULE_PATH, current, self._config.polling.detector_reserve):
            reset_at = self._limiter.budget(NEAREST_SCHEDULE_PATH).reset_at
            self._notifier.info(f"Request budget for checks used up{_until(reset_at)}.")
            return []

        nearest = self._nearest_slots(current)
        self._notifier.info("Nearest practical exams: " + "; ".join(
            f"{self._center_names.get(center_id, center_id)}: {slot.start:%d.%m %H:%M}" if slot
            else f"{self._center_names.get(center_id, center_id)}: none"
            for center_id, slot in nearest.items()
        ))
        decision = self._planner.decide(nearest, current, before)
        found = {slot.key: slot for slot in decision.matches}
        if decision.full_check_centers:
            for slot in self._full_check(decision.full_check_centers, current):
                if self._criteria.matches(slot, current, before):
                    found[slot.key] = slot
        return sorted(found.values())

    def _nearest_slots(self, current: datetime) -> dict[int, Slot | None]:
        profile = self._require_profile()
        try:
            return self._api.nearest_practice_slots(profile, self._center_ids, self._start_date(current))
        except ApiError as e:
            if e.status != 400 or self._use_service_default_start:
                raise
            rejected = e
        # Maybe the start date is earlier than the service accepts; retry once with the form's default start date.
        default_start = (current + SERVICE_DEFAULT_START_OFFSET).date()
        if default_start <= self._criteria.search_start_date(current):
            raise rejected
        slots = self._api.nearest_practice_slots(profile, self._center_ids, default_start)
        self._use_service_default_start = True
        self._notifier.info(f"The service rejected an earlier start date ({rejected}); searching from {default_start}.")
        return slots

    def _full_check(self, center_ids: tuple[int, ...], current: datetime) -> list[Slot]:
        # The full schedule endpoint accepts one center per request.
        reserve = self._config.polling.reservation_reserve
        start_date = self._start_date(current)
        slots: list[Slot] = []
        for center_id in center_ids:
            if not self._limiter.can_spend(ALL_SCHEDULE_PATH, current, reserve):
                self._postpone_full_check()
                break
            slots.extend(self._api.all_practice_slots(self._require_profile(), center_id, start_date))
            self._planner.record_full_check((center_id,), current)
        return slots

    def _postpone_full_check(self) -> list[Slot]:
        reset_at = self._limiter.budget(ALL_SCHEDULE_PATH).reset_at
        self._notifier.info(f"Full check postponed to keep requests for a reservation{_until(reset_at)}.")
        return []

    def _start_date(self, current: datetime) -> date:
        start = self._criteria.search_start_date(current)
        if self._use_service_default_start:
            start = max(start, (current + SERVICE_DEFAULT_START_OFFSET).date())
        return start

    def _with_session[T](self, action: Callable[[], T]) -> T:
        while True:
            try:
                return action()
            except SessionExpiredError:
                self._relogin()

    def _relogin(self) -> None:
        self._notifier.important(
            "Session expired",
            "Press Enter in the ExamCatch terminal, then scan the QR code in the browser window to log in again.",
        )
        self._console.drain()
        while self._console.poll() is None:
            self._session.wait(timedelta(seconds=1))
        self._session.login()

    def _require_profile(self) -> Profile:
        if self._profile is None:
            raise FatalError("PKK profile is not loaded")
        return self._profile

    def _new_planner(self) -> CheckPlanner:
        return CheckPlanner(self._criteria, self._config.polling.full_check_min_interval, NEAREST_SCHEDULE_HORIZON)


def _until(moment: datetime | None) -> str:
    return f" until {moment:%H:%M}" if moment else ""
