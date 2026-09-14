"""Addresses and constants of the info-kierowca.pl service (see specyfikacja.md, section 6)."""

from datetime import timedelta

BASE_URL = "https://info-kierowca.pl"

EXAM_API = "/bknd/exam/api/v1"
NEAREST_SCHEDULE_PATH = f"{EXAM_API}/Schedules/user/MultipleCentersExams"
ALL_SCHEDULE_PATH = f"{EXAM_API}/Schedules/user/OneCenterExam"
RESERVATIONS_PATH = f"{EXAM_API}/Reservations"
PKK_PROFILES_PATH = "/bknd/status/api/v1/pkk/get_profiles_for_reservation"

# The nearest-slot endpoint requires exactly this many centers ("Exactly 5 exam centers must be provided").
NEAREST_SCHEDULE_CENTER_COUNT = 5
# The nearest-slot endpoint does not see slots far ahead: on 2026-09-14 it showed a slot 29 days ahead but not
# one 35 days ahead that the full schedule listed. Conservative lower bound of its horizon:
NEAREST_SCHEDULE_HORIZON = timedelta(days=28)
# Existing center ids used to pad nearest-slot requests; their results are dropped.
FILLER_CENTER_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)

# Reservation statuses meaning the slot is held for the user until payment.
HELD_RESERVATION_STATUSES = frozenset({"PlaceReserved", "PaymentRequested"})

# Order of the frontend's category enum; the index is the numeric code sent to the API (B = 5).
CATEGORY_CODES = (
    "AM", "A1", "A2", "A", "B1", "B", "C1", "C", "D1", "D",
    "B+E", "C1+E", "C+E", "D1+E", "D+E", "T", "PT",
)
