"""Browser lifecycle and the login session (specyfikacja.md, 2.1, 6.1, 6.7.1)."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from examcatch.api import SessionExpiredError
from examcatch.config import BrowserConfig
from examcatch.notify import Notifier
from examcatch.service import BASE_URL

LOGIN_TIMEOUT = timedelta(minutes=10)
PAGE_SETTLE_MS = 3000
# The frontend logs out after 10 minutes without user activity.
KEEP_ALIVE_INTERVAL_SECONDS = 60
# Safety net: the application must never start a payment.
PAYMENT_INIT_ROUTE = "**/payments/init/**"


@contextmanager
def open_browser(config: BrowserConfig) -> Iterator[Page]:
    config.profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(config.profile_dir),
            headless=False,
            locale="pl-PL",
            viewport={"width": 1400, "height": 900},
        )
        try:
            context.route(PAYMENT_INIT_ROUTE, _abort)
            # The service blocks a second tab of the application, so everything happens in one page.
            yield context.pages[0] if context.pages else context.new_page()
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass


def _abort(route: Route) -> None:
    route.abort()


class Session:
    def __init__(self, page: Page, notifier: Notifier):
        self._page = page
        self._notifier = notifier
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
        page.get_by_text("login.gov.pl").first.click()
        page.wait_for_url("**login.gov.pl/**", timeout=60_000)
        page.get_by_role("button", name=re.compile("Aplikacja mObywatel")).click(no_wait_after=True)
        self._notifier.important(
            "Login required",
            "Scan the QR code shown in the ExamCatch browser window with the mObywatel app.",
        )

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
