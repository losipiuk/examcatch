from datetime import date, datetime

from examcatch.config import SearchConfig
from examcatch.criteria import SlotCriteria
from examcatch.models import WARSAW, Slot

NOW = datetime(2026, 9, 14, 8, 0, tzinfo=WARSAW)
CRITERIA = SlotCriteria(SearchConfig(), [26, 25])


def slot(day: int, hour: int, minute: int = 0, center_id: int = 26) -> Slot:
    return Slot(start=datetime(2026, 9, day, hour, minute, tzinfo=WARSAW), center_id=center_id, center_name="WORD", places=1)


def test_accepts_slot_meeting_all_rules():
    assert CRITERIA.matches(slot(15, 10, 20), NOW)


def test_start_time_range_is_inclusive():
    assert CRITERIA.matches(slot(15, 10, 0), NOW)
    assert CRITERIA.matches(slot(15, 15, 0), NOW)
    assert CRITERIA.rejection_reason(slot(15, 9, 30), NOW) == "start time is outside the allowed range"
    assert CRITERIA.rejection_reason(slot(15, 15, 1), NOW) == "start time is outside the allowed range"


def test_minimum_lead_time():
    assert CRITERIA.rejection_reason(slot(14, 13, 59), NOW) == "starts too soon"
    assert CRITERIA.matches(slot(14, 14, 0), NOW)


def test_search_window():
    assert CRITERIA.matches(slot(27, 14), NOW)
    assert CRITERIA.rejection_reason(slot(28, 10), NOW) == "outside the search window"


def test_unconfigured_center():
    assert CRITERIA.rejection_reason(slot(15, 11, center_id=99), NOW) == "exam center is not configured"


def test_only_strictly_earlier_than_reservation():
    reserved = slot(20, 11).start
    assert CRITERIA.rejection_reason(slot(20, 11), NOW, before=reserved) == "not earlier than the current reservation"
    assert CRITERIA.matches(slot(19, 11), NOW, before=reserved)


def test_search_start_date_follows_lead_time():
    assert CRITERIA.search_start_date(NOW) == date(2026, 9, 14)
    assert CRITERIA.search_start_date(NOW.replace(hour=20)) == date(2026, 9, 15)


def test_may_precede_matches():
    assert CRITERIA.may_precede_matches(slot(14, 7), NOW)
    assert not CRITERIA.may_precede_matches(slot(29, 7), NOW)
    assert not CRITERIA.may_precede_matches(slot(20, 7), NOW, before=slot(18, 11).start)
