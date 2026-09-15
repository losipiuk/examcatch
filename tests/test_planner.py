from datetime import datetime, timedelta

from examcatch.config import SearchConfig
from examcatch.criteria import SlotCriteria
from examcatch.models import WARSAW, Slot
from examcatch.planner import NEAREST_CHECK, CheckScheduler, PlannedCheck

NOW = datetime(2026, 9, 14, 8, 0, tzinfo=WARSAW)
CRITERIA = SlotCriteria(SearchConfig(), [25])
INTERVAL = timedelta(minutes=3, seconds=30)


def slot(day: int, hour: int, minute: int = 0, center_id: int = 25) -> Slot:
    return Slot(start=datetime(2026, 9, day, hour, minute, tzinfo=WARSAW), center_id=center_id, center_name="WORD", places=1)


def scheduler(criteria: SlotCriteria = CRITERIA) -> CheckScheduler:
    return CheckScheduler(
        criteria,
        nearest_horizon=timedelta(days=28),
        hold=timedelta(minutes=30),
        release_checks_in_window=3,
        release_check_grace=timedelta(minutes=1),
    )


def test_starts_with_nearest_check():
    assert scheduler().choose(NOW, [25], can_nearest=True, can_full=True) == NEAREST_CHECK


def test_new_nearest_slot_in_window_triggers_full_check():
    subject = scheduler()
    subject.record_nearest({25: slot(15, 7)}, NOW)

    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == PlannedCheck(25)


def test_alternates_endpoints_while_full_checks_are_useful():
    subject = scheduler()
    subject.record_nearest({25: slot(15, 7)}, NOW)
    subject.record_full(25, [], NOW)

    checks = []
    for minute in range(4):
        current = NOW + timedelta(minutes=minute)
        check = subject.choose(current, [25], can_nearest=True, can_full=True)
        checks.append(check)
        if check.is_full:
            subject.record_full(25, [], current)
        else:
            subject.record_nearest({25: slot(15, 7)}, current)

    assert checks == [NEAREST_CHECK, PlannedCheck(25), NEAREST_CHECK, PlannedCheck(25)]


def test_skips_full_checks_when_nearest_slot_is_beyond_window():
    subject = scheduler()
    subject.record_nearest({25: slot(29, 7)}, NOW)

    assert [subject.choose(NOW, [25], can_nearest=True, can_full=True) for _ in range(3)] == [NEAREST_CHECK] * 3


def test_skips_full_checks_without_nearest_slot_when_window_is_within_horizon():
    subject = scheduler()
    subject.record_nearest({25: None}, NOW)

    assert [subject.choose(NOW, [25], can_nearest=True, can_full=True) for _ in range(2)] == [NEAREST_CHECK] * 2


def test_uses_full_checks_without_nearest_slot_when_window_exceeds_horizon():
    subject = scheduler(SlotCriteria(SearchConfig(window_days=45), [25]))
    subject.record_nearest({25: None}, NOW)

    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == NEAREST_CHECK
    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == PlannedCheck(25)


def test_falls_back_to_the_endpoint_with_requests_left():
    subject = scheduler()
    subject.record_nearest({25: slot(15, 7)}, NOW)
    subject.record_full(25, [], NOW)

    assert subject.choose(NOW, [25], can_nearest=False, can_full=True) == PlannedCheck(25)
    assert subject.choose(NOW, [25], can_nearest=True, can_full=False) == NEAREST_CHECK
    assert subject.choose(NOW, [25], can_nearest=False, can_full=False) is None


def test_returns_acceptable_slots():
    subject = scheduler()

    assert subject.record_nearest({25: slot(15, 11)}, NOW) == [slot(15, 11)]
    assert subject.record_full(25, [slot(17, 12), slot(15, 7), slot(16, 11)], NOW) == [slot(16, 11), slot(17, 12)]


def test_monitoring_checks_full_schedule_even_when_nearest_slot_matches():
    subject = scheduler()

    assert subject.record_nearest({25: slot(15, 11)}, NOW, before=slot(25, 11).start) == [slot(15, 11)]
    assert subject.choose(NOW, [25], can_nearest=True, can_full=True, before=slot(25, 11).start) == PlannedCheck(25)


def test_lost_slot_plans_checks_when_a_competitor_hold_may_expire():
    subject = scheduler()
    lost = slot(16, 11)
    subject.record_full(25, [lost], NOW)
    failed_at = NOW + timedelta(minutes=4)

    planned = subject.record_lost_slot(lost, failed_at)

    # The competitor reserved between NOW and failed_at, so their hold expires between NOW + 30 and failed_at + 30.
    assert planned == [
        NOW + timedelta(minutes=30),
        NOW + timedelta(minutes=32),
        failed_at + timedelta(minutes=30),
        failed_at + timedelta(minutes=31),
    ]
    assert subject.next_wakeup(failed_at, INTERVAL) == failed_at + INTERVAL
    assert subject.next_wakeup(NOW + timedelta(minutes=28), INTERVAL) == NOW + timedelta(minutes=30)
    assert subject.choose(NOW + timedelta(minutes=30), [25], can_nearest=True, can_full=True) == PlannedCheck(25)


def test_lost_slot_never_seen_is_checked_at_upper_bound_and_after_grace():
    subject = scheduler()

    assert subject.record_lost_slot(slot(16, 11), NOW) == [NOW + timedelta(minutes=30), NOW + timedelta(minutes=31)]


def test_release_check_uses_nearest_endpoint_when_full_budget_is_used_up():
    subject = scheduler()
    subject.record_lost_slot(slot(16, 11), NOW)

    assert subject.choose(NOW + timedelta(minutes=30), [25], can_nearest=True, can_full=False) == NEAREST_CHECK
