"""Response shapes follow what the service returned during exploration (specyfikacja.md, 6.7.3)."""

from datetime import date, datetime

import pytest

from examcatch.api import ApiError, parse_all_slots, parse_nearest_slots, schedule_request_body
from examcatch.models import WARSAW, Profile

NAMES = {26: "WORD Warszawa M/E Bemowo", 25: "WORD Warszawa M/E Odlewnicza"}


def practice(date_time: str, center_id: int = 26, places: int = 3) -> dict:
    return {
        "practiceId": "1001",
        "practiceDateTime": date_time,
        "theoryId": None,
        "theoryDateTime": None,
        "examType": "Practice",
        "placeTheoryAmount": 0,
        "placePracticeAmount": places,
        "amount": 229.99,
        "category": "B",
        "organizationId": center_id,
        "organizationName": NAMES[center_id],
        "additionalInfo": None,
        "oskCarEnabled": False,
        "firstAvailable": False,
    }


def theory(date_time: str, center_id: int = 26) -> dict:
    return {
        "practiceId": None,
        "practiceDateTime": None,
        "theoryId": "2002",
        "theoryDateTime": date_time,
        "examType": "Theoretical",
        "placeTheoryAmount": 5,
        "placePracticeAmount": 0,
        "amount": 56.98,
        "category": "B",
        "organizationId": center_id,
        "organizationName": NAMES[center_id],
    }


def test_parse_nearest_slots():
    data = [
        {
            "wordId": 26,
            "wordName": NAMES[26],
            "examCollectionForDay": [theory("2026-10-01T11:40:00"), practice("2026-10-21T07:50:00")],
        },
        {"wordId": 25, "wordName": NAMES[25], "examCollectionForDay": [theory("2026-10-05T14:50:00", 25)]},
    ]

    result = parse_nearest_slots(data)

    assert result[25] is None
    assert result[26] is not None
    assert result[26].start == datetime(2026, 10, 21, 7, 50, tzinfo=WARSAW)
    assert result[26].center_name == NAMES[26]
    assert result[26].places == 3


def test_parse_all_slots_keeps_free_practical_slots_sorted():
    data = {
        "startDatePointerForCalendar": "2026-09-16",
        "examCollectionForDay": [
            {
                "date": "2026-10-22",
                "examCollections": [
                    practice("2026-10-22T14:00:00"),
                    practice("2026-10-22T10:20:00", places=0),
                    theory("2026-10-22T09:00:00"),
                ],
            },
            {"date": "2026-10-21", "examCollections": [practice("2026-10-21T08:40:00", places=7)]},
        ],
    }

    starts = [slot.start for slot in parse_all_slots(data)]

    assert starts == [
        datetime(2026, 10, 21, 8, 40, tzinfo=WARSAW),
        datetime(2026, 10, 22, 14, 0, tzinfo=WARSAW),
    ]


def test_schedule_request_body():
    body = schedule_request_body(Profile(number="123", category="B"), (26,), date(2026, 9, 14))

    assert body == {
        "startDate": "2026-09-14",
        "organizationId": [26],
        "category": 5,
        "profileNumber": "123",
        "profileType": "Pkk",
    }


def test_schedule_request_body_rejects_unknown_category():
    with pytest.raises(ApiError, match="category"):
        schedule_request_body(Profile(number="123", category="X"), (26,), date(2026, 9, 14))
