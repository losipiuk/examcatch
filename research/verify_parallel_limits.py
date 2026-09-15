"""Checks whether separate browsers (profiles) get separate request limits.

The service's authors allow up to 4 parallel browsers. This opens two new browsers with their own profiles, logs
each in (a QR code scan per browser), and compares X-RateLimit-Remaining:

1. browser 1: 3 nearest-slot requests and 1 full schedule request,
2. browser 2: 1 request of each kind; remaining 9 means the limit is per browser, less means it is shared,
3. browser 1: 1 more nearest-slot request, to see whether logging in browser 2 ended browser 1's session.

7 requests in total. Reservation-changing requests and payments are blocked. No personal data is printed.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from examcatch.api import ApiError, ServiceApi  # noqa: E402
from examcatch.browser import BROWSER_ARGS, PAYMENT_INIT_ROUTE, Session  # noqa: E402
from examcatch.notify import Notifier  # noqa: E402
from examcatch.ratelimit import RateLimiter  # noqa: E402
from examcatch.reservation import DRY_RUN_BLOCKED_ROUTES  # noqa: E402
from examcatch.service import ALL_SCHEDULE_PATH, NEAREST_SCHEDULE_PATH  # noqa: E402

CENTER_ID = 25
PROFILES = (Path(".examcatch/limit-test-1"), Path(".examcatch/limit-test-2"))
notifier = Notifier()


class Browser:
    def __init__(self, playwright, name: str, profile_dir: Path):
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=False, args=list(BROWSER_ARGS), locale="pl-PL",
            viewport={"width": 1200, "height": 850},
        )
        for pattern in (PAYMENT_INIT_ROUTE, *DRY_RUN_BLOCKED_ROUTES):
            self.context.route(pattern, lambda route: route.abort())
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.session = Session(self.page, notifier, Path(".examcatch/screenshots"))
        self.limiter = RateLimiter()
        self.api = ServiceApi(self.page, self.limiter)
        self.profile = None

    def login(self) -> None:
        notifier.info(f"{self.name}: logging in (scan the QR code in this browser window if asked)")
        self.session.ensure_logged_in()
        self.profile = self.api.pkk_profiles()[0]

    def request(self, kind: str) -> None:
        start = date.today() + timedelta(days=2)
        path = NEAREST_SCHEDULE_PATH if kind == "nearest" else ALL_SCHEDULE_PATH
        try:
            if kind == "nearest":
                self.api.nearest_practice_slots(self.profile, [CENTER_ID], start)
            else:
                self.api.all_practice_slots(self.profile, CENTER_ID, start)
            status = "200"
        except ApiError as e:
            status = f"HTTP {e.status}"
        budget = self.limiter.budget(path)
        reset = f"{budget.reset_at:%H:%M:%S}" if budget.reset_at else "?"
        notifier.info(f"RESULT {self.name} {kind:7} -> {status}, remaining {budget.remaining}/{budget.limit}, reset {reset}")


with sync_playwright() as playwright:
    first = Browser(playwright, "browser-1", PROFILES[0])
    first.login()
    for _ in range(3):
        first.request("nearest")
    first.request("full")

    second = Browser(playwright, "browser-2", PROFILES[1])
    second.login()
    second.request("nearest")
    second.request("full")

    first.request("nearest")
    notifier.info("DONE")
    for browser in (first, second):
        browser.context.close()
