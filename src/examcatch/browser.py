"""Browser lifecycle and the login session (specyfikacja.md, 2.1, 6.1, 6.7.1)."""

from __future__ import annotations

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
PAGE_SETTLE_MS = 3000
# The frontend logs out after 10 minutes without user activity.
KEEP_ALIVE_INTERVAL_SECONDS = 60
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
        self._pointer_toggle = False

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
        """Starts the mObywatel QR login and waits until the user scans the code."""
        while True:
            try:
                self._start_qr_login()
            except PlaywrightError as e:
                self._screenshot("login-failed")
                self._notifier.info(
                    f"Could not open the mObywatel QR login at {self._page.url}: {_first_line(e)}. Retrying."
                )
                self._page.wait_for_timeout(PAGE_SETTLE_MS)
                continue
            if not self._on_login_page():
                break
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

    def _start_qr_login(self) -> None:
        page = self._page
        page.goto(f"{BASE_URL}/login", wait_until="load")
        page.wait_for_timeout(PAGE_SETTLE_MS)
        if not self._on_login_page():
            return
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
            return
        if MOBYWATEL_LOGIN_HOST not in page.url:
            self._notifier.info("Choosing the mObywatel app.")
            try:
                page.get_by_role("button", name=re.compile("Aplikacja mObywatel")).click(no_wait_after=True)
            except PlaywrightTimeoutError:
                pass  # clicking navigates to the QR page, which may outlast the click; the URL check below decides
            page.wait_for_url(lambda url: MOBYWATEL_LOGIN_HOST in url or _is_logged_in_url(url), timeout=60_000)
            if not self._on_login_page():
                return
        self._notifier.important(
            "Login required",
            "Scan the QR code shown in the ExamCatch browser window with the mObywatel app.",
        )

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

    def _keep_alive(self) -> None:
        if time.monotonic() - self._last_keep_alive < KEEP_ALIVE_INTERVAL_SECONDS:
            return
        self._last_keep_alive = time.monotonic()
        self._pointer_toggle = not self._pointer_toggle
        try:
            self._page.mouse.move(400 if self._pointer_toggle else 600, 300)
        except PlaywrightError:
            pass
