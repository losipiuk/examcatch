from datetime import timedelta

from examcatch.browser import renewal_due

RENEW_AFTER = timedelta(minutes=50)


def test_due_once_renewal_time_has_passed():
    assert not renewal_due(logged_in_at=1000.0, now=1000.0 + 49 * 60, renew_after=RENEW_AFTER)
    assert renewal_due(logged_in_at=1000.0, now=1000.0 + 50 * 60, renew_after=RENEW_AFTER)


def test_never_due_when_disabled_or_login_time_unknown():
    assert not renewal_due(logged_in_at=1000.0, now=1000.0 + 120 * 60, renew_after=None)
    assert not renewal_due(logged_in_at=None, now=1000.0 + 120 * 60, renew_after=RENEW_AFTER)
