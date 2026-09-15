import json

from examcatch.browser import describe_logout_reason


def test_describes_stored_reason():
    reason = json.dumps({"reason": "idle_timeout", "timestamp": "2026-09-15T12:40:45.000Z"})

    assert describe_logout_reason(reason, None) == "idle_timeout at 2026-09-15T12:40:45.000Z"


def test_includes_details():
    reason = json.dumps({"reason": "realtime_unauthorized", "details": "jwt_refresh_401", "timestamp": "T"})

    assert describe_logout_reason(reason, None) == "realtime_unauthorized (jwt_refresh_401) at T"


def test_falls_back_to_latest_event_when_reason_was_consumed():
    events = json.dumps([
        {"reason": "realtime_unknown_error", "timestamp": "T1"},
        {"reason": "idle_timeout", "timestamp": "T2"},
    ])

    assert describe_logout_reason(None, events) == "idle_timeout at T2"


def test_nothing_recorded_or_unreadable():
    assert describe_logout_reason(None, None) is None
    assert describe_logout_reason("not json", "[]") is None
    assert describe_logout_reason(json.dumps({"details": "no reason"}), None) is None
