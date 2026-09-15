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
    return CheckScheduler(criteria, hold=timedelta(minutes=30), release_checks_in_window=3, release_check_grace=timedelta(minutes=1))


def run_checks(subject: CheckScheduler, count: int, nearest: Slot | None, center_ids: tuple[int, ...] = (25,)) -> list[PlannedCheck]:
    checks = []
    for minute in range(count):
        current = NOW + timedelta(minutes=minute)
        check = subject.choose(current, list(center_ids), can_nearest=True, can_full=True)
        checks.append(check)
        if check.is_full:
            subject.record_full(check.center_id, [], current)
        else:
            subject.record_nearest({center_id: nearest for center_id in center_ids}, current)
    return checks


def test_starts_with_nearest_check():
    assert scheduler().choose(NOW, [25], can_nearest=True, can_full=True) == NEAREST_CHECK


def test_new_nearest_slot_in_window_triggers_full_check_as_its_turn():
    assert run_checks(scheduler(), 4, slot(15, 7)) == [NEAREST_CHECK, PlannedCheck(25), NEAREST_CHECK, PlannedCheck(25)]


def test_keeps_alternating_when_nearest_slot_is_beyond_window():
    # Skipping full checks here used to exhaust the nearest-slot limit within half an hour (seen on 2026-09-15).
    assert run_checks(scheduler(), 4, slot(29, 7)) == [NEAREST_CHECK, PlannedCheck(25), NEAREST_CHECK, PlannedCheck(25)]


def test_rotates_full_checks_over_centers():
    subject = scheduler(SlotCriteria(SearchConfig(), [25, 26]))

    checks = run_checks(subject, 4, None, center_ids=(25, 26))

    assert checks == [NEAREST_CHECK, PlannedCheck(25), NEAREST_CHECK, PlannedCheck(26)]


def test_changed_nearest_slot_brings_full_check_forward():
    subject = scheduler()
    subject.record_nearest({25: slot(15, 7)}, NOW)
    subject.record_full(25, [], NOW)
    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == NEAREST_CHECK

    subject.record_nearest({25: slot(15, 7, 50)}, NOW)

    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == PlannedCheck(25)


def test_falls_back_to_the_endpoint_with_requests_left():
    subject = scheduler()

    assert subject.choose(NOW, [25], can_nearest=False, can_full=True) == PlannedCheck(25)
    assert subject.choose(NOW, [25], can_nearest=True, can_full=False) == NEAREST_CHECK
    assert subject.choose(NOW, [25], can_nearest=False, can_full=False) is None


def test_returns_acceptable_slots():
    subject = scheduler()

    assert subject.record_nearest({25: slot(15, 11)}, NOW) == [slot(15, 11)]
    assert subject.record_full(25, [slot(17, 12), slot(15, 7), slot(16, 11)], NOW) == [slot(16, 11), slot(17, 12)]


def test_monitoring_checks_full_schedule_when_nearest_slot_matches():
    subject = scheduler()

    assert subject.record_nearest({25: slot(15, 11)}, NOW, before=slot(25, 11).start) == [slot(15, 11)]
    assert subject.choose(NOW, [25], can_nearest=True, can_full=True) == PlannedCheck(25)


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
