"""Browser lifecycle and the login session (specyfikacja.md, 2.1, 6.1, 6.7.1)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from examcatch.api import SessionExpiredError
from examcatch.config import BrowserConfig
from examcatch.notify import Notifier
from examcatch.service import BASE_URL

LOGIN_TIMEOUT = timedelta(minutes=10)
# Host of the page showing the mObywatel QR code.
MOBYWATEL_LOGIN_HOST = "login.mobywatel.gov.pl"
# Accessible name of the login method option on login.gov.pl.
MOBYWATEL_OPTION = re.compile("Aplikacja mObywatel")
PAGE_SETTLE_MS = 3000
# The frontend logs out after 10 minutes without user activity (specyfikacja.md, 6.2).
KEEP_ALIVE_INTERVAL_SECONDS = 60
# The frontend's inactivity timer listens for these events on window and does not check whether they are trusted.
ACTIVITY_SCRIPT = "() => window.dispatchEvent(new MouseEvent('mousemove'))"
# During the last 2 minutes the frontend ignores activity and shows this dialog; its button extends the session.
SESSION_WARNING_BUTTON = "app-session-timeout-warning-dialog .session-timeout-warning__actions button"
# Where the frontend records why it ended the session (the reason is removed once the login page shows it).
LOGOUT_REASON_KEY = "pudo.session.end.reason"
LOGOUT_EVENTS_KEY = "pudo.session.end.events"
READ_LOGOUT_REASON_SCRIPT = (
    f"() => ({{reason: sessionStorage.getItem('{LOGOUT_REASON_KEY}'), "
    f"events: sessionStorage.getItem('{LOGOUT_EVENTS_KEY}')}})"
)
# Safety net: the application must never start a payment.
PAYMENT_INIT_ROUTE = "**/payments/init/**"
# Keep timers and rendering running when the user minimizes or covers the window, so the page keeps its session
# alive and the reservation form can be clicked through.
BROWSER_ARGS = (
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
)


@contextmanager
def open_browser(
    config: BrowserConfig,
    blocked_routes: Sequence[str] = (),
    on_blocked: Callable[[str], None] | None = None,
) -> Iterator[Page]:
    """Opens a headed browser; requests matching `blocked_routes` (and payment initiation) are aborted."""
    config.profile_dir.mkdir(parents=True, exist_ok=True)

    def block(route: Route) -> None:
        if on_blocked:
            on_blocked(route.request.url)
        route.abort()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(config.profile_dir),
            headless=False,
            args=list(BROWSER_ARGS),
            locale="pl-PL",
            viewport={"width": 1400, "height": 900},
        )
        try:
            for pattern in (PAYMENT_INIT_ROUTE, *blocked_routes):
                context.route(pattern, block)
            # The service blocks a second tab of the application, so everything happens in one page.
            yield context.pages[0] if context.pages else context.new_page()
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass


def describe_logout_reason(reason_json: str | None, events_json: str | None) -> str | None:
    """Formats the frontend's stored logout reason, e.g. "idle_timeout at 2026-09-15T12:40:45.000Z".

    Falls back to the latest recorded session event when the reason itself was already consumed.
    """
    event = _load_json(reason_json)
    if not isinstance(event, dict):
        events = _load_json(events_json)
        event = events[-1] if isinstance(events, list) and events else None
    if not isinstance(event, dict) or not event.get("reason"):
        return None
    parts = [str(event["reason"])]
    if event.get("details"):
        parts.append(f"({event['details']})")
    if event.get("timestamp"):
        parts.append(f"at {event['timestamp']}")
    return " ".join(parts)


def _load_json(text: str | None) -> object:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _is_logged_in_url(url: str) -> bool:
    return url.startswith(BASE_URL) and "/login" not in url


def _first_line(error: Exception) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__


class Session:
    def __init__(self, page: Page, notifier: Notifier, screenshots_dir: Path):
        self._page = page
        self._notifier = notifier
        self._screenshots_dir = screenshots_dir
        self._last_keep_alive = time.monotonic()

    def ensure_logged_in(self) -> None:
        """Opens the service and logs in when the stored session is not valid."""
        self._page.goto(f"{BASE_URL}/cases", wait_until="load")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        if self._on_login_page():
            self.login()

    def ensure_service_page(self) -> None:
        """Makes sure the page is on the service origin, which API calls need; raises when logged out."""
        if not self._on_login_page():
            return
        self._page.goto(f"{BASE_URL}/cases", wait_until="load")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        if self._on_login_page():
            raise SessionExpiredError("not logged in")

    def login(self) -> None:
        """Logs in again through a still valid login.gov.pl session, or shows the mObywatel QR code and waits for a scan.

        The user is notified once per login, not for every refreshed QR code.
        """
        notified = False
        while True:
            try:
                qr_shown = self._start_qr_login()
            except PlaywrightError as e:
                self._screenshot("login-failed")
                self._notifier.info(
                    f"Could not open the mObywatel QR login at {self._page.url}: {_first_line(e)}. Retrying."
                )
                self._page.wait_for_timeout(PAGE_SETTLE_MS)
                continue
            if not self._on_login_page():
                break
            if qr_shown and not notified:
                self._notifier.important(
                    "Login required",
                    "Scan the QR code shown in the ExamCatch browser window with the mObywatel app.",
                )
                notified = True
            try:
                self._page.wait_for_url(
                    lambda url: url.startswith(BASE_URL) and "/login" not in url,
                    timeout=LOGIN_TIMEOUT.total_seconds() * 1000,
                )
                break
            except PlaywrightTimeoutError:
                self._notifier.info("Login was not completed in time; showing a new QR code.")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        self._notifier.info("Logged in.")

    def wait(self, duration: timedelta) -> None:
        """Waits while keeping the browser responsive and the session active."""
        remaining = duration.total_seconds()
        while remaining > 0:
            step = min(remaining, 1.0)
            self._page.wait_for_timeout(step * 1000)
            remaining -= step
            self._keep_alive()

    def _start_qr_login(self) -> bool:
        """Opens the login flow; returns whether the mObywatel QR code is shown (False when already logged in)."""
        page = self._page
        page.goto(f"{BASE_URL}/login", wait_until="load")
        page.wait_for_timeout(PAGE_SETTLE_MS)
        if not self._on_login_page():
            return False
        self._dismiss_cookie_banner()
        self._notifier.info("Choosing login.gov.pl.")
        try:
            page.get_by_text("login.gov.pl").first.click(no_wait_after=True)
        except PlaywrightTimeoutError:
            pass  # the click may already have navigated away; the URL check below decides
        # login.gov.pl may return straight to the service (its session is still valid) or open the mObywatel QR page
        # right away (it remembers the last login method).
        page.wait_for_url(
            lambda url: "login.gov.pl" in url or MOBYWATEL_LOGIN_HOST in url or _is_logged_in_url(url),
            timeout=60_000,
        )
        if not self._on_login_page():
            return False
        if MOBYWATEL_LOGIN_HOST not in page.url:
            self._notifier.info("Choosing the mObywatel app.")
            # The option used to be a button; since 2026-09-15 it is a tile with role "link". Accept either.
            option = page.get_by_role("link", name=MOBYWATEL_OPTION).or_(page.get_by_role("button", name=MOBYWATEL_OPTION))
            try:
                option.first.click(no_wait_after=True, timeout=15_000)
            except PlaywrightTimeoutError:
                if MOBYWATEL_LOGIN_HOST not in page.url and not _is_logged_in_url(page.url):
                    raise PlaywrightTimeoutError("the 'Aplikacja mObywatel' option was not found on login.gov.pl") from None
            page.wait_for_url(lambda url: MOBYWATEL_LOGIN_HOST in url or _is_logged_in_url(url), timeout=60_000)
            if not self._on_login_page():
                return False
        return True

    def _screenshot(self, name: str) -> None:
        try:
            self._screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = self._screenshots_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.png"
            self._page.screenshot(path=str(path), full_page=True)
            self._notifier.info(f"Screenshot saved to {path}.")
        except (OSError, PlaywrightError):
            pass

    def _dismiss_cookie_banner(self) -> None:
        try:
            self._page.get_by_text("ODRZUĆ WSZYSTKIE").first.click(timeout=5000)
        except PlaywrightError:
            pass

    def _on_login_page(self) -> bool:
        url = self._page.url
        return not url.startswith(BASE_URL) or "/login" in url

    def logout_reason(self) -> str | None:
        """The reason the service's frontend recorded for ending the session, if the page can still read it."""
        if not self._page.url.startswith(BASE_URL):
            return None
        try:
            stored = self._page.evaluate(READ_LOGOUT_REASON_SCRIPT)
        except PlaywrightError:
            return None
        return describe_logout_reason(stored.get("reason"), stored.get("events"))

    def _keep_alive(self) -> None:
        """Keeps the frontend's inactivity timer from ending the session.

        A dispatched activity event also works while the display is off and does not move the user's pointer.
        """
        if time.monotonic() - self._last_keep_alive < KEEP_ALIVE_INTERVAL_SECONDS:
            return
        self._last_keep_alive = time.monotonic()
        if self._on_login_page():
            return
        try:
            extend = self._page.locator(SESSION_WARNING_BUTTON)
            if extend.count() and extend.first.is_visible():
                extend.first.click()
                self._notifier.info("Confirmed the service's inactivity warning to keep the session.")
            self._page.evaluate(ACTIVITY_SCRIPT)
        except PlaywrightError:
            pass
