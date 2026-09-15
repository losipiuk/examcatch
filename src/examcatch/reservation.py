"""Reserving a slot by clicking through the service's reservation form (specyfikacja.md, 2.2, 6.7.2).

Steps 1-5 were verified on the live service (--dry-run and --test-reservation). The flow stops at the confirmation
step, which holds the slot; the payment step (6) is left to the user.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from examcatch.api import ApiError, ServiceApi, SessionExpiredError
from examcatch.errors import CenterNotAllowedError, FatalError, ReservationError
from examcatch.models import Reservation, Slot, now
from examcatch.notify import Notifier
from examcatch.service import BASE_URL, HELD_RESERVATION_STATUSES

NEXT_BUTTON_LABEL = "Zapisz i przejdź dalej"
PKK_PROFILE_TYPE_LABEL = "PKK - Profil kandydata na kierowcę (PKK)"
SINGLE_CENTER_MODE_LABEL = "Wybierz ośrodek WORD i pokaż wszystkie terminy egzaminów"
PRACTICAL_EXAM_LABEL = re.compile(r"^\s*Egzamin praktyczny\s*$")
POLISH_LANGUAGE_LABEL = re.compile(r"^\s*(język\s+)?polski\s*$", re.IGNORECASE)
# Choosing a slot opens a "Potwierdź wybrany egzamin" dialog with this confirmation button.
SLOT_CONFIRMATION_LABEL = "Potwierdź i przejdź dalej"
SLOT_STEP_LABEL = "Termin"
DIALOG_TIMEOUT_MS = 5000
# Shown on the confirmation step once the slot is held for the user.
CONFIRMED_MESSAGE = "Rezerwacja została potwierdzona"
# Part of the service's error when the PKK profile belongs to a different WORD than the chosen exam center.
WRONG_CENTER_MESSAGE = "innym niż podany w rezerwacji"
# Material icon names rendered as text inside alerts.
ALERT_ICON_WORDS = frozenset({"warning", "error", "info", "check_circle", "close"})
ELEMENT_TIMEOUT_MS = 15_000
STEP_SETTLE_MS = 2000
CONFIRMATION_TIMEOUT_SECONDS = 120
UNKNOWN_RESERVATION_ID = "unknown (see the reservation list)"
# Requests aborted in dry run mode, so that filling in the form can never create or hold a reservation.
DRY_RUN_BLOCKED_ROUTES = (
    "**/Reservations/create*",
    "**/Reservations/confirm/**",
    "**/Reservations/reschedule*",
    "**/Reservations/cancel*",
)


def clean_alert_text(text: str) -> str:
    """Alert text without the icon names the page renders as words (e.g. "warning ... close")."""
    words = text.split()
    while words and words[0] in ALERT_ICON_WORDS:
        words.pop(0)
    while words and words[-1] in ALERT_ICON_WORDS:
        words.pop()
    return " ".join(words)


class ReservationFlow:
    def __init__(
        self,
        page: Page,
        api: ServiceApi,
        notifier: Notifier,
        screenshots_dir: Path,
        clock: Callable[[], datetime] = now,
    ):
        self._page = page
        self._api = api
        self._notifier = notifier
        self._screenshots_dir = screenshots_dir
        self._clock = clock
        self._describe_steps = False

    def reserve(self, slot: Slot) -> Reservation:
        """Clicks through the form up to the payment step, which holds the slot for the user.

        Raises ReservationError when this slot cannot be reserved, FatalError when the account setup is
        unsupported, and SessionExpiredError when the user got logged out.
        """
        try:
            self._select_profile_and_center(slot)
            self._select_slot(slot)
            self._select_language()
            self._submit_summary()
            self._wait_for_confirmation(slot)
        except ReservationError:
            self._screenshot("reservation-failed")
            raise
        except PlaywrightError as e:
            self._screenshot("reservation-failed")
            raise ReservationError(f"unexpected page state: {e}") from e
        reserved_at = self._clock()
        self._screenshot("reservation-confirmed")
        return Reservation(id=self._find_reservation_id(slot), slot=slot, reserved_at=reserved_at)

    def preview(self, slot: Slot) -> None:
        """Dry run: fills in the form up to the summary step and reports what it shows, without submitting it."""
        self._describe_steps = True
        try:
            self._select_profile_and_center(slot)
            self._select_slot(slot)
            self._select_language()
            if not self._appears(self._page.locator("app-step-summary")):
                raise ReservationError("the summary step was not reached")
            self._describe_step("summary")
            # The page scrolls inside a container, so a full-page screenshot misses the bottom of the summary.
            self._page.locator("app-step-summary").first.evaluate("element => element.scrollIntoView({block: 'end'})")
            self._page.wait_for_timeout(500)
            self._screenshot("dry-run-summary-end")
            submit_visible = self._page.locator("button:visible").filter(has_text=NEXT_BUTTON_LABEL).count() > 0
            self._notifier.info(f"[summary] submit button {NEXT_BUTTON_LABEL!r} visible: {submit_visible}")
        except PlaywrightError as e:
            raise ReservationError(f"unexpected page state: {e}") from e
        finally:
            self._screenshot("dry-run")
            self._describe_steps = False

    def _select_profile_and_center(self, slot: Slot) -> None:
        page = self._page
        page.goto(f"{BASE_URL}/reservation", wait_until="load")
        self._ensure_logged_in()
        page.get_by_text(PKK_PROFILE_TYPE_LABEL).click(timeout=ELEMENT_TIMEOUT_MS)

        page.locator("#profileNumber").click(timeout=ELEMENT_TIMEOUT_MS)
        profiles = self._visible_options()
        count = profiles.count() if self._appears(profiles) else 0
        if count != 1:
            raise FatalError(f"Expected exactly one PKK profile in the reservation form, found {count}")
        profiles.first.click()

        # The "nearest dates" mode shows only one slot per center, so pick the center explicitly.
        page.get_by_text(SINGLE_CENTER_MODE_LABEL).click(timeout=ELEMENT_TIMEOUT_MS)
        page.locator("#word").click(timeout=ELEMENT_TIMEOUT_MS)
        page.locator("#word-input").fill(slot.center_name)
        center = self._visible_options().filter(has_text=slot.center_name)
        if not self._appears(center):
            raise ReservationError(f"exam center {slot.center_name!r} not found in the form")
        center.first.click()
        self._click_next()

    def _select_slot(self, slot: Slot) -> None:
        page = self._page
        page.locator("mat-radio-button").filter(has_text=PRACTICAL_EXAM_LABEL).first.click(timeout=ELEMENT_TIMEOUT_MS)

        day_label = f"{slot.start:%d/%m/%Y}"
        day_panel = page.locator("mat-expansion-panel.day").filter(
            has=page.locator("mat-expansion-panel-header", has_text=day_label)
        )
        if not self._appears(day_panel):
            # The form lists days from its default start date (today + 2 days); earlier days need an explicit date.
            date_input = page.locator("#startDate")
            date_input.fill(day_label)
            date_input.press("Enter")
            date_input.blur()
            if not self._appears(day_panel):
                raise ReservationError(f"day {day_label} is no longer offered")
        day_panel.first.locator("mat-expansion-panel-header").click()

        time_row = day_panel.first.locator("app-timetable-row-exam").filter(has_text=f"{slot.start:%H:%M}")
        if not self._appears(time_row):
            raise ReservationError(f"{slot.describe()} is no longer offered")
        time_row.first.locator("mat-checkbox").click()
        confirm = page.locator("[role=dialog], mat-dialog-container").locator("button").filter(
            has_text=SLOT_CONFIRMATION_LABEL
        )
        if self._appears(confirm, timeout_ms=DIALOG_TIMEOUT_MS):
            confirm.first.click()
            page.wait_for_timeout(STEP_SETTLE_MS)
        if self._active_step_label().endswith(SLOT_STEP_LABEL):
            self._click_next()

    def _select_language(self) -> None:
        page = self._page
        page.wait_for_timeout(STEP_SETTLE_MS)
        if self._describe_steps:
            self._describe_step("language and OSK vehicle")
        polish =page.locator("mat-radio-button:visible").filter(has_text=POLISH_LANGUAGE_LABEL)
        if polish.count():
            polish.first.click()
        else:
            for select in page.locator("mtx-select:visible, mat-select:visible").all():
                attributes = " ".join(
                    value for name in ("id", "formcontrolname", "aria-label") if (value := select.get_attribute(name))
                ).lower()
                if "lang" not in attributes and "język" not in attributes:
                    continue
                if "polski" not in select.inner_text().lower():
                    select.click()
                    self._visible_options().filter(has_text=POLISH_LANGUAGE_LABEL).first.click(
                        timeout=ELEMENT_TIMEOUT_MS
                    )
                break
        # The OSK vehicle data on this step is optional and left empty.
        self._click_next()

    def _submit_summary(self) -> None:
        # The summary has no consents to tick; it is submitted with the usual "Zapisz i przejdź dalej" button.
        self._page.locator("app-step-summary").wait_for(state="visible", timeout=ELEMENT_TIMEOUT_MS)
        self._click_next()

    def _wait_for_confirmation(self, slot: Slot) -> None:
        """Waits for "Rezerwacja została potwierdzona"; the slot is then held ("PlaceReserved") for 30 minutes.

        The payment step only opens when the user asks for it, so the flow stops here.
        """
        page = self._page
        deadline = time.monotonic() + CONFIRMATION_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            self._ensure_logged_in()
            if page.get_by_text(CONFIRMED_MESSAGE).first.is_visible() or page.locator("app-step-payment").first.is_visible():
                return
            alert = page.locator("app-general-alert-dialog:visible, mat-snack-bar-container:visible")
            if alert.count():
                message = clean_alert_text(alert.first.inner_text()) or "the service reported an error"
                if WRONG_CENTER_MESSAGE in message:
                    raise CenterNotAllowedError(slot.center_id, message)
                raise ReservationError(message)
            page.wait_for_timeout(1000)
        raise ReservationError("the reservation was not confirmed in time")

    def _find_reservation_id(self, slot: Slot) -> str:
        # The slot is already held at this point, so failing to find its number must not fail the reservation.
        try:
            reservations = self._api.reservations()
        except ApiError as e:
            self._notifier.info(f"Could not read the reservation list: {e}")
            return UNKNOWN_RESERVATION_ID
        held = [
            reservation
            for reservation in reservations
            if reservation.get("status") in HELD_RESERVATION_STATUSES
            and reservation.get("organizationId") == slot.center_id
            and reservation.get("practiceExamDate") == slot.start.date().isoformat()
            and str(reservation.get("practiceExamTime") or "").startswith(f"{slot.start:%H:%M}")
        ]
        if not held:
            self._notifier.info("The new reservation was not found in the reservation list.")
            return UNKNOWN_RESERVATION_ID
        return str(max(held, key=lambda reservation: reservation.get("reservationDate") or "")["id"])

    def _describe_step(self, name: str) -> None:
        """Reports labels of the current step's controls (dry run diagnostics, scoped to the form)."""
        stepper = self._page.locator("mat-stepper, mat-horizontal-stepper, mat-vertical-stepper")
        scope = stepper.first if stepper.count() else self._page.locator("body")

        def labels(selector: str) -> list[str]:
            return [text[:80] for element in scope.locator(selector).all() if (text := " ".join(element.inner_text().split()))]

        fields = [
            " ".join(value for attribute in ("id", "formcontrolname", "aria-label") if (value := element.get_attribute(attribute)))
            for element in scope.locator(
                "mtx-select:visible, mat-select:visible, input[type=text]:visible, textarea:visible"
            ).all()
        ]
        self._notifier.info(f"[{name}] radio buttons: {labels('mat-radio-button:visible')}")
        self._notifier.info(f"[{name}] fields: {fields}")
        self._notifier.info(f"[{name}] checkboxes: {labels('mat-checkbox:visible')}")
        self._notifier.info(f"[{name}] buttons: {labels('button:visible')}")

    def _click_next(self) -> None:
        # Every step has a button with this label; only the current step's one is visible.
        self._page.locator("button:visible").filter(has_text=NEXT_BUTTON_LABEL).first.click(timeout=ELEMENT_TIMEOUT_MS)
        self._page.wait_for_timeout(STEP_SETTLE_MS)

    def _visible_options(self) -> Locator:
        return self._page.locator("[role=option]:visible")

    def _appears(self, locator: Locator, timeout_ms: int = ELEMENT_TIMEOUT_MS) -> bool:
        try:
            locator.first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            return False

    def _active_step_label(self) -> str:
        """Label of the current stepper step, e.g. "2 Termin"."""
        header = self._page.locator("mat-step-header[aria-selected=true]")
        return " ".join(header.first.inner_text().split()) if header.count() else ""

    def _ensure_logged_in(self) -> None:
        if "/login" in self._page.url:
            raise SessionExpiredError("redirected to the login page")

    def _screenshot(self, name: str) -> None:
        try:
            self._screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = self._screenshots_dir / f"{self._clock():%Y%m%d-%H%M%S}-{name}.png"
            self._page.screenshot(path=str(path), full_page=True)
            self._notifier.info(f"Screenshot saved to {path}.")
        except (OSError, PlaywrightError):
            pass
