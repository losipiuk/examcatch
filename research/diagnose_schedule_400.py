"""Diagnoses HTTP 400 from the schedule endpoints using the stored ExamCatch browser session.

Findings so far (2026-09-14):
- MultipleCentersExams: 200 with the 5 nearby centers the frontend sends, 400 with [26, 25].
- OneCenterExam: 200 with [26], 400 with [26, 25].
- MultipleCentersExams error: "Exactly 5 exam centers must be provided when searching for the fastest terms";
  any 5 centers work ([26, 25, 1, 2, 3] -> 200).

Sends the variants below and prints status, rate limit headers and the response (error bodies in full).
Long digit sequences are masked. Reservation-changing requests are blocked.
"""

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from examcatch.api import ServiceApi, _FETCH_SCRIPT  # noqa: E402
from examcatch.browser import open_browser  # noqa: E402
from examcatch.config import BrowserConfig  # noqa: E402
from examcatch.ratelimit import RateLimiter  # noqa: E402
from examcatch.reservation import DRY_RUN_BLOCKED_ROUTES  # noqa: E402
from examcatch.service import BASE_URL, NEAREST_SCHEDULE_PATH  # noqa: E402


def mask(text: str) -> str:
    return re.sub(r"\d{11,}", "<digits>", text)


with open_browser(BrowserConfig(), DRY_RUN_BLOCKED_ROUTES, lambda url: print("BLOCKED", url)) as page:
    page.goto(f"{BASE_URL}/cases", wait_until="load")
    page.wait_for_timeout(3000)
    print("url:", page.url)
    if "/login" in page.url:
        sys.exit("not logged in; run the dry run first to log in")

    profile = ServiceApi(page, RateLimiter()).pkk_profiles()[0]
    start = (date.today() + timedelta(days=2)).isoformat()
    base = {"startDate": start, "category": 5, "profileNumber": profile.number, "profileType": "Pkk"}
    variants = [
        ("nearest, [26, 25] (error body)", NEAREST_SCHEDULE_PATH, dict(base, organizationId=[26, 25])),
        ("nearest, [26, 25, 1, 2, 3] (any five centers)", NEAREST_SCHEDULE_PATH, dict(base, organizationId=[26, 25, 1, 2, 3])),
    ]
    for name, path, body in variants:
        response = page.evaluate(_FETCH_SCRIPT, {"path": path, "method": "POST", "body": body})
        limits = {k: v for k, v in response["headers"].items() if "ratelimit" in k}
        text = response["text"]
        try:
            parsed = json.loads(text)
            if response["status"] == 200 and isinstance(parsed, list):
                summary = f"list[{len(parsed)}] wordIds={[center.get('wordId') for center in parsed]}"
            else:
                summary = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            summary = f"non-JSON text: {text[:300]!r}"
        print(f"\n### {name} (startDate {start}) -> HTTP {response['status']} {limits}")
        print(mask(summary)[:1500])
        page.wait_for_timeout(1000)
