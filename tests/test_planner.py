from datetime import datetime, timedelta

from examcatch.config import SearchConfig
from examcatch.criteria import SlotCriteria
from examcatch.models import WARSAW, Slot
from examcatch.planner import CheckPlanner

NOW = datetime(2026, 9, 14, 8, 0, tzinfo=WARSAW)
CRITERIA = SlotCriteria(SearchConfig(), [26, 25])


def slot(day: int, hour: int, minute: int = 0, center_id: int = 26) -> Slot:
    return Slot(start=datetime(2026, 9, day, hour, minute, tzinfo=WARSAW), center_id=center_id, center_name="WORD", places=1)


def planner(criteria: SlotCriteria = CRITERIA) -> CheckPlanner:
    return CheckPlanner(criteria, timedelta(minutes=15), nearest_horizon=timedelta(days=28))


def test_no_nearest_slot_needs_no_full_check_when_window_is_within_horizon():
    assert planner().decide({26: None}, NOW).full_check_centers == ()


def test_no_nearest_slot_triggers_full_check_when_window_exceeds_horizon():
    subject = planner(SlotCriteria(SearchConfig(window_days=45), [26]))

    assert subject.decide({26: None}, NOW).full_check_centers == (26,)
    subject.record_full_check((26,), NOW)
    assert subject.decide({26: None}, NOW + timedelta(minutes=7)).full_check_centers == ()


def test_matching_nearest_slot_needs_no_full_check_when_searching():
    nearest = slot(15, 11)

    decision = planner().decide({26: nearest, 25: None}, NOW)

    assert decision.matches == (nearest,)
    assert decision.full_check_centers == ()


def test_nearest_slot_beyond_window_needs_no_full_check():
    decision = planner().decide({26: slot(29, 11)}, NOW)

    assert decision.matches == ()
    assert decision.full_check_centers == ()


def test_non_matching_nearest_slot_in_window_triggers_full_check():
    decision = planner().decide({26: slot(15, 7), 25: slot(29, 7, center_id=25)}, NOW)

    assert decision.full_check_centers == (26,)


def test_unchanged_nearest_slot_waits_for_minimum_interval():
    subject = planner()
    subject.decide({26: slot(15, 7)}, NOW)
    subject.record_full_check((26,), NOW)

    assert subject.decide({26: slot(15, 7)}, NOW + timedelta(minutes=7)).full_check_centers == ()
    assert subject.decide({26: slot(15, 7)}, NOW + timedelta(minutes=15)).full_check_centers == (26,)


def test_changed_nearest_slot_triggers_full_check_immediately():
    subject = planner()
    subject.decide({26: slot(15, 7)}, NOW)
    subject.record_full_check((26,), NOW)

    decision = subject.decide({26: slot(15, 7, 50)}, NOW + timedelta(minutes=7))

    assert decision.full_check_centers == (26,)


def test_monitoring_checks_full_schedule_even_when_nearest_slot_matches():
    nearest = slot(15, 11)

    decision = planner().decide({26: nearest}, NOW, before=slot(25, 11).start)

    assert decision.matches == (nearest,)
    assert decision.full_check_centers == (26,)
