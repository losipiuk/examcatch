"""Addresses and constants of the info-kierowca.pl service (see specyfikacja.md, section 6)."""

BASE_URL = "https://info-kierowca.pl"

EXAM_API = "/bknd/exam/api/v1"
NEAREST_SCHEDULE_PATH = f"{EXAM_API}/Schedules/user/MultipleCentersExams"
ALL_SCHEDULE_PATH = f"{EXAM_API}/Schedules/user/OneCenterExam"
RESERVATIONS_PATH = f"{EXAM_API}/Reservations"
PKK_PROFILES_PATH = "/bknd/status/api/v1/pkk/get_profiles_for_reservation"

# Reservation statuses meaning the slot is held for the user until payment.
HELD_RESERVATION_STATUSES = frozenset({"PlaceReserved", "PaymentRequested"})

# Order of the frontend's category enum; the index is the numeric code sent to the API (B = 5).
CATEGORY_CODES = (
    "AM", "A1", "A2", "A", "B1", "B", "C1", "C", "D1", "D",
    "B+E", "C1+E", "C+E", "D1+E", "D+E", "T", "PT",
)
