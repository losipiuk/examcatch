"""Browser lifecycle and the login session (specyfikacja.md, 2.1, 6.1, 6.7.1)."""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, Response, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from examcatch.api import SessionExpiredError
from examcatch.config import BrowserConfig
from examcatch.models import now
from examcatch.notify import Attachment, EmailChannel, Notifier
from examcatch.service import BASE_URL

# The mObywatel login page gets its code here: {"value": "data:image/png;base64,...", "token": "8;D;1;..."}.
# The token is what the QR code encodes and what the app accepts under "Wpisz kod" (specyfikacja.md, 6.1).
QR_CODE_API_PATH = "/api/login/auth/qr-code"
# A code is valid for 5 minutes; the page then offers this button instead of refreshing by itself.
QR_CODE_VALIDITY = timedelta(minutes=5)
QR_REFRESH_LABEL = "Odśwież kod QR"
QR_EXPIRY_GRACE_SECONDS = 5
QR_RESPONSE_TIMEOUT_MS = 15_000
# The expired-code view may render a few seconds after the timer ends.
QR_REFRESH_TIMEOUT_MS = 30_000
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
# Cookies holding the portal session; clearing them (without logging out) starts a fresh login.
PORTAL_SESSION_COOKIES = ("__Secure-PUDOJT", "__Secure-PUDOJTMD")
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


def renewal_due(logged_in_at: float | None, current: float, renew_after: timedelta | None) -> bool:
    """Whether a session that started at `logged_in_at` (monotonic seconds) should be renewed at `current`."""
    return (
        renew_after is not None
        and logged_in_at is not None
        and current - logged_in_at >= renew_after.total_seconds()
    )


def qr_refresh_button(page: Page) -> Locator:
    """The "Odśwież kod QR" control shown once a login code has expired (matched by text, whatever its role)."""
    return page.locator("button, [role=button], [role=link]").filter(has_text=QR_REFRESH_LABEL).first


@dataclass(frozen=True)
class LoginCode:
    """A mObywatel login code: the QR image and the same code as text."""

    text: str
    image_png: bytes | None
    expires_at: datetime


def parse_login_code(token: str, image_data_uri: str | None, received_at: datetime) -> LoginCode:
    """Builds a login code from the login page's API response.

    The token looks like "8;D;1;;;9216;;<uuid>;<issued epoch>;<expires epoch>;<host>;0;3;;"; its validity is taken
    from the two timestamps (relative to `received_at`, to avoid clock differences), else 5 minutes.
    """
    validity = QR_CODE_VALIDITY
    epochs = [int(part) for part in token.split(";") if re.fullmatch(r"\d{10}", part)]
    if len(epochs) >= 2 and epochs[1] > epochs[0]:
        validity = timedelta(seconds=epochs[1] - epochs[0])
    image = None
    prefix = "data:image/png;base64,"
    if image_data_uri and image_data_uri.startswith(prefix):
        try:
            image = base64.b64decode(image_data_uri[len(prefix):], validate=True)
        except (binascii.Error, ValueError):
            image = None
    return LoginCode(text=token, image_png=image, expires_at=received_at + validity)


class Session:
    def __init__(
        self,
        page: Page,
        notifier: Notifier,
        screenshots_dir: Path,
        renew_after: timedelta | None = None,
        max_login_code_notifications: int = 12,
    ):
        self._page = page
        self._notifier = notifier
        self._screenshots_dir = screenshots_dir
        self._renew_after = renew_after
        self._max_code_notifications = max_login_code_notifications
        self._last_keep_alive = time.monotonic()
        self._logged_in_at: float | None = None
        self._qr_response: Response | None = None
        page.on("response", self._remember_qr_response)

    def ensure_logged_in(self) -> None:
        """Opens the service and logs in when the stored session is not valid."""
        self._page.goto(f"{BASE_URL}/cases", wait_until="load")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        if self._on_login_page():
            self.login()
        elif self._logged_in_at is None:
            # A session kept in the browser profile; its real login time is unknown, so count from now.
            self._logged_in_at = time.monotonic()

    def renew_if_due(self) -> None:
        """Renews the session before the service ends it, about an hour after login (specyfikacja.md, 2.1).

        Only the portal's session cookies are cleared, without logging out, so a still valid login.gov.pl session can
        log in again without a QR code. Otherwise the usual QR login runs.
        """
        current = time.monotonic()
        if not renewal_due(self._logged_in_at, current, self._renew_after):
            return
        assert self._logged_in_at is not None
        minutes = int((current - self._logged_in_at) // 60)
        self._notifier.info(f"Renewing the session before the service ends it (logged in {minutes} min ago).")
        # Leave the portal first, so its frontend does not react to the missing cookies.
        self._page.goto("about:blank")
        for name in PORTAL_SESSION_COOKIES:
            self._page.context.clear_cookies(name=name)
        qr_needed = self.login()
        self._notifier.info("Session renewed " + ("after a QR code scan." if qr_needed else "without a QR code."))

    def ensure_service_page(self) -> None:
        """Makes sure the page is on the service origin, which API calls need; raises when logged out."""
        if not self._on_login_page():
            return
        self._page.goto(f"{BASE_URL}/cases", wait_until="load")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        if self._on_login_page():
            raise SessionExpiredError("not logged in")

    def login(self) -> bool:
        """Logs in with the mObywatel app; returns whether a login code had to be used.

        Every login code shown is sent to the user (QR image and text) up to the configured limit per login, an
        expired code is refreshed on the page, and a completed login is confirmed by e-mail.
        """
        codes_sent = 0
        code_needed = False
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
            code_needed = code_needed or qr_shown
            logged_in, codes_sent = self._wait_for_code_use(codes_sent)
            if logged_in:
                break
            self._notifier.info("The login page did not offer a new code; starting the login again.")
        self._page.wait_for_timeout(PAGE_SETTLE_MS)
        self._logged_in_at = time.monotonic()
        if code_needed:
            self._notifier.important(
                "Logged in",
                "ExamCatch is logged in and keeps checking. The service ends the session about an hour after login; "
                "a new login code will be sent then.",
                channel_names={EmailChannel.name},
            )
        else:
            self._notifier.info("Logged in (no QR code needed).")
        return code_needed

    def wait(self, duration: timedelta) -> None:
        """Waits while keeping the browser responsive and the session active."""
        remaining = duration.total_seconds()
        while remaining > 0:
            step = min(remaining, 1.0)
            self._page.wait_for_timeout(step * 1000)
            remaining -= step
            self._keep_alive()

    def _wait_for_code_use(self, codes_sent: int) -> tuple[bool, int]:
        """Sends each new login code and waits for its use, refreshing codes that expire.

        Returns whether the login completed and the updated number of codes sent. False means the page did not offer
        a new code, so the login flow has to start again.
        """
        page = self._page
        while True:
            self._wait_for_qr_response()
            code = self._take_login_code()
            wait_seconds = QR_CODE_VALIDITY.total_seconds()
            if code is not None:
                if self._max_code_notifications == 0 or codes_sent < self._max_code_notifications:
                    self._send_login_code(code, first=codes_sent == 0)
                    codes_sent += 1
                    if codes_sent == self._max_code_notifications:
                        self._notifier.info(
                            "Login code notification limit reached; further codes are shown in the browser window only."
                        )
                wait_seconds = max((code.expires_at - now()).total_seconds(), 0) + QR_EXPIRY_GRACE_SECONDS
            try:
                page.wait_for_url(_is_logged_in_url, timeout=wait_seconds * 1000)
                return True, codes_sent
            except PlaywrightTimeoutError:
                pass
            refresh = qr_refresh_button(page)
            try:
                refresh.wait_for(state="visible", timeout=QR_REFRESH_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                return _is_logged_in_url(page.url), codes_sent
            self._notifier.info("The login code expired; getting a new one.")
            refresh.click()

    def _send_login_code(self, code: LoginCode, first: bool) -> None:
        attachments = (
            [Attachment("mobywatel-login-qr.png", code.image_png, "image/png")] if code.image_png else []
        )
        self._notifier.important(
            "Login required" if first else "New login code",
            f"Log ExamCatch in with the mObywatel app before {code.expires_at:%H:%M}:\n"
            "- scan the QR code (attached, also shown in the ExamCatch browser window): "
            "mObywatel > Kod QR > Zeskanuj kod QR, or\n"
            "- on the phone: copy the code below, then in mObywatel choose Kod QR > Zeskanuj kod QR > Wpisz kod, "
            "paste it, choose Dalej and then Udostępnij dane.\n\n"
            f"{code.text}",
            attachments=attachments,
        )

    def _remember_qr_response(self, response: Response) -> None:
        # Only store it here: calling Playwright from an event handler is not allowed in the sync API.
        if QR_CODE_API_PATH in response.url and response.ok:
            self._qr_response = response

    def _wait_for_qr_response(self) -> None:
        deadline = time.monotonic() + QR_RESPONSE_TIMEOUT_MS / 1000
        while self._qr_response is None and time.monotonic() < deadline:
            self._page.wait_for_timeout(250)

    def _take_login_code(self) -> LoginCode | None:
        response, self._qr_response = self._qr_response, None
        if response is None:
            return None
        try:
            data = response.json()
        except (PlaywrightError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("token"):
            return None
        value = data.get("value")
        return parse_login_code(str(data["token"]), value if isinstance(value, str) else None, now())

    def _start_qr_login(self) -> bool:
        """Opens the login flow; returns whether the mObywatel QR code is shown (False when already logged in)."""
        page = self._page
        self._qr_response = None
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
