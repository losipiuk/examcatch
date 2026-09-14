"""Calls to the service's REST API made from inside the logged-in browser page (specyfikacja.md, 2.7, 6.7.3)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any

from playwright.sync_api import Page

from examcatch.models import WARSAW, Profile, Slot
from examcatch.ratelimit import RateLimiter
from examcatch.service import (
    ALL_SCHEDULE_PATH,
    CATEGORY_CODES,
    FILLER_CENTER_IDS,
    NEAREST_SCHEDULE_CENTER_COUNT,
    NEAREST_SCHEDULE_PATH,
    PKK_PROFILES_PATH,
    RESERVATIONS_PATH,
)

# Runs inside the page, so requests carry the session cookies and look exactly like the frontend's own calls.
_FETCH_SCRIPT = """async ({path, method, body}) => {
  const headers = {Accept: 'application/json'};
  if (body !== null) {
    headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(path, {
    method,
    headers,
    body: body === null ? undefined : JSON.stringify(body),
  });
  const responseHeaders = {};
  response.headers.forEach((value, key) => { responseHeaders[key] = value; });
  return {status: response.status, headers: responseHeaders, text: await response.text()};
}"""


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class SessionExpiredError(ApiError):
    """The session is no longer valid; the user has to log in again."""


class RateLimitedError(ApiError):
    def __init__(self, message: str, reset_at: datetime | None):
        super().__init__(message, status=429)
        self.reset_at = reset_at


class ServiceApi:
    def __init__(self, page: Page, limiter: RateLimiter):
        self._page = page
        self._limiter = limiter

    def pkk_profiles(self) -> list[Profile]:
        data = self._request("GET", PKK_PROFILES_PATH)
        return _parsed(lambda: [Profile(number=str(item["pkkNumber"]), category=str(item["categoryName"])) for item in data])

    def nearest_practice_slots(
        self, profile: Profile, center_ids: Iterable[int], start_date: date
    ) -> dict[int, Slot | None]:
        """Nearest practical exam slot per center (a cheap request, used to detect changes).

        One request per 5 centers: the endpoint needs exactly 5, so each group is padded with other centers.
        """
        wanted = list(dict.fromkeys(center_ids))
        result: dict[int, Slot | None] = {}
        for offset in range(0, len(wanted), NEAREST_SCHEDULE_CENTER_COUNT):
            group = wanted[offset:offset + NEAREST_SCHEDULE_CENTER_COUNT]
            body = schedule_request_body(profile, pad_center_ids(group, exclude=wanted), start_date)
            data = self._request("POST", NEAREST_SCHEDULE_PATH, body)
            nearest = _parsed(lambda: parse_nearest_slots(data))
            result.update({center_id: nearest.get(center_id) for center_id in group})
        return result

    def all_practice_slots(self, profile: Profile, center_id: int, start_date: date) -> list[Slot]:
        """All practical exam slots at one center; the endpoint accepts exactly one center."""
        data = self._request("POST", ALL_SCHEDULE_PATH, schedule_request_body(profile, [center_id], start_date))
        return _parsed(lambda: parse_all_slots(data))

    def reservations(self) -> list[dict[str, Any]]:
        data = self._request("GET", RESERVATIONS_PATH)
        return data if isinstance(data, list) else []

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        response = self._page.evaluate(_FETCH_SCRIPT, {"path": path, "method": method, "body": body})
        status = int(response["status"])
        self._limiter.update(path, response["headers"])
        data = _decode(response["text"])
        if status in (401, 403):
            raise SessionExpiredError(f"{method} {path}: HTTP {status}", status, data)
        if status == 429:
            budget = self._limiter.budget(path)
            budget.remaining = 0
            raise RateLimitedError(f"{method} {path}: request limit exceeded", budget.reset_at)
        if status >= 400:
            raise ApiError(f"{method} {path}: HTTP {status}{_problem_details(data)}", status, data)
        return data


def schedule_request_body(profile: Profile, center_ids: Iterable[int], start_date: date) -> dict[str, Any]:
    try:
        category = CATEGORY_CODES.index(profile.category.upper())
    except ValueError:
        raise ApiError(f"unsupported licence category {profile.category!r}") from None
    return {
        "startDate": start_date.isoformat(),
        # Must be a list even for a single center; a plain number is rejected with HTTP 400.
        "organizationId": list(center_ids),
        "category": category,
        "profileNumber": profile.number,
        "profileType": profile.profile_type,
    }


def pad_center_ids(center_ids: list[int], exclude: Iterable[int] = ()) -> list[int]:
    """Pads up to NEAREST_SCHEDULE_CENTER_COUNT ids with filler centers not in `center_ids` or `exclude`."""
    taken = set(center_ids) | set(exclude)
    fillers = [center_id for center_id in FILLER_CENTER_IDS if center_id not in taken]
    return [*center_ids, *fillers[:NEAREST_SCHEDULE_CENTER_COUNT - len(center_ids)]]


def parse_nearest_slots(data: Any) -> dict[int, Slot | None]:
    result: dict[int, Slot | None] = {}
    for center in data:
        slots = [slot for entry in center.get("examCollectionForDay") or [] if (slot := _parse_entry(entry))]
        result[int(center["wordId"])] = min(slots, default=None)
    return result


def parse_all_slots(data: Any) -> list[Slot]:
    return sorted(
        slot
        for day in data.get("examCollectionForDay") or []
        for entry in day.get("examCollections") or []
        if (slot := _parse_entry(entry))
    )


def _parse_entry(entry: dict[str, Any]) -> Slot | None:
    if entry.get("examType") != "Practice" or not entry.get("practiceDateTime"):
        return None
    places = int(entry.get("placePracticeAmount") or 0)
    if places <= 0:
        return None
    center_id = int(entry["organizationId"])
    return Slot(
        start=datetime.fromisoformat(entry["practiceDateTime"]).replace(tzinfo=WARSAW),
        center_id=center_id,
        center_name=entry.get("organizationName") or str(center_id),
        places=places,
        exam_id=entry.get("practiceId"),
    )


def _problem_details(data: Any) -> str:
    """Error message and details from the service's error response (an object or a list of objects)."""
    def describe(item: dict[str, Any]) -> str:
        return " ".join(str(item[key]) for key in ("code", "field", "message") if item.get(key))

    parts: list[str] = []
    for item in data if isinstance(data, list) else [data]:
        if not isinstance(item, dict):
            continue
        parts.append(describe(item))
        parts.extend(describe(detail) for detail in item.get("details") or [] if isinstance(detail, dict))
    parts = [part for part in parts if part]
    return f" ({'; '.join(parts)})" if parts else ""


def _decode(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parsed[T](parse: Callable[[], T]) -> T:
    try:
        return parse()
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ApiError(f"unexpected response format: {e!r}") from e
