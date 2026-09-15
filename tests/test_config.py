import textwrap
from datetime import time, timedelta
from pathlib import Path

import pytest

from examcatch.config import ConfigError, load_config

MINIMAL = """
    centers:
      - id: 26
        name: WORD Warszawa M/E Bemowo
    """


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_defaults(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL))

    assert [(center.id, center.name) for center in config.centers] == [(26, "WORD Warszawa M/E Bemowo")]
    assert config.search.window_days == 14
    assert config.search.start_time_from == time(10, 0)
    assert config.search.start_time_to == time(15, 0)
    assert config.search.min_lead_time == timedelta(hours=6)
    assert config.polling.check_interval == timedelta(seconds=210)
    assert config.polling.release_checks_in_window == 3
    assert config.polling.release_check_grace == timedelta(minutes=1)
    assert config.polling.reservation_reserve == 2
    assert config.polling.detector_reserve == 1
    assert config.payment.hold == timedelta(minutes=30)
    assert config.payment.reminder_interval == timedelta(minutes=5)
    assert config.email is None
    assert config.callmebot is None


def test_overrides_and_unquoted_times(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL + """
    search:
      window_days: 7
      start_time_from: 9:30
      start_time_to: "14:00"
      min_lead_hours: 4.5
    polling:
      check_interval_seconds: 300
      release_checks_in_window: 2
      release_check_grace_minutes: 0
    """))

    assert config.search.window_days == 7
    assert config.search.start_time_from == time(9, 30)
    assert config.search.start_time_to == time(14, 0)
    assert config.search.min_lead_time == timedelta(hours=4, minutes=30)
    assert config.polling.check_interval == timedelta(seconds=300)
    assert config.polling.release_checks_in_window == 2
    assert config.polling.release_check_grace == timedelta(0)


def test_environment_variables_and_literal_values(tmp_path, monkeypatch):
    monkeypatch.setenv("EXAMCATCH_TEST_PASSWORD", "secret")
    monkeypatch.setenv("EXAMCATCH_TEST_PORT", "465")
    config = load_config(write_config(tmp_path, MINIMAL + """
    notifications:
      email:
        smtp_host: smtp.example.com
        smtp_port: "${EXAMCATCH_TEST_PORT}"
        username: user@example.com
        password: "${EXAMCATCH_TEST_PASSWORD}"
        from: user@example.com
        to: me@example.com
      callmebot:
        phone: "+48123456789"
        api_key: hard-coded-key
    """))

    assert config.email is not None
    assert config.email.smtp_port == 465
    assert config.email.password == "secret"
    assert config.email.recipients == ("me@example.com",)
    assert config.callmebot is not None
    assert config.callmebot.api_key == "hard-coded-key"


def test_missing_environment_variable(tmp_path):
    path = write_config(tmp_path, MINIMAL + """
    notifications:
      callmebot:
        phone: "+48123456789"
        api_key: "${EXAMCATCH_TEST_UNSET_VARIABLE}"
    """)

    with pytest.raises(ConfigError, match="EXAMCATCH_TEST_UNSET_VARIABLE"):
        load_config(path)


def test_disabled_channel(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL + """
    notifications:
      callmebot:
        enabled: false
    """))

    assert config.callmebot is None


def test_centers_are_required(tmp_path):
    with pytest.raises(ConfigError, match="centers"):
        load_config(write_config(tmp_path, "search:\n  window_days: 3\n"))


def test_start_time_range_must_be_ordered(tmp_path):
    with pytest.raises(ConfigError, match="start_time_from"):
        load_config(write_config(tmp_path, MINIMAL + """
    search:
      start_time_from: "16:00"
      start_time_to: "15:00"
    """))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")


def test_removed_polling_keys_are_reported(tmp_path):
    with pytest.raises(ConfigError, match="check_interval_seconds"):
        load_config(write_config(tmp_path, MINIMAL + """
    polling:
      detector_interval_minutes: 7
    """))
