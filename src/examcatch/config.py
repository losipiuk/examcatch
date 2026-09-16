"""Loading and validation of the YAML configuration file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Any

import yaml

ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_REQUIRED = object()


class ConfigError(Exception):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class Center:
    id: int
    name: str


@dataclass(frozen=True)
class SearchConfig:
    window_days: int = 14
    start_time_from: time = time(10, 0)
    start_time_to: time = time(15, 0)
    min_lead_time: timedelta = timedelta(hours=6)


@dataclass(frozen=True)
class PollingConfig:
    # Checks alternate between two endpoints with 10 requests per hour each, minus the reserves below.
    check_interval: timedelta = timedelta(seconds=210)
    reservation_reserve: int = 2
    detector_reserve: int = 1
    # Extra checks when a lost slot's competitor hold may expire: spread over the possible window, plus one after it.
    release_checks_in_window: int = 3
    release_check_grace: timedelta = timedelta(minutes=1)


@dataclass(frozen=True)
class PaymentConfig:
    hold: timedelta = timedelta(minutes=30)
    reminder_interval: timedelta = timedelta(minutes=5)


@dataclass(frozen=True)
class BrowserConfig:
    profile_dir: Path = Path(".examcatch/profile")
    screenshots_dir: Path = Path(".examcatch/screenshots")


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    starttls: bool
    username: str | None
    password: str | None
    sender: str
    recipients: tuple[str, ...]


@dataclass(frozen=True)
class CallMeBotConfig:
    phone: str
    api_key: str


@dataclass(frozen=True)
class SessionConfig:
    # Renew the portal session this long after login; None disables it. Off by default: the service requests
    # ForceAuthn="true", so every login needs a fresh QR scan and renewal only ends the session early.
    renew_after: timedelta | None = None


@dataclass(frozen=True)
class SystemConfig:
    # Keep the computer from idle sleep while running (macOS caffeinate); sleep stops checks and ends the session.
    prevent_sleep: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    # Every message shown on the screen is also appended to this file; None disables the file.
    file: Path | None = Path(".examcatch/examcatch.log")


@dataclass(frozen=True)
class Config:
    centers: tuple[Center, ...]
    search: SearchConfig
    polling: PollingConfig
    payment: PaymentConfig
    browser: BrowserConfig
    email: EmailConfig | None
    callmebot: CallMeBotConfig | None
    logging: LoggingConfig
    system: SystemConfig
    session: SessionConfig


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path}: file not found") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: invalid YAML: {e}") from e
    return parse_config(substitute_env(raw))


def substitute_env(value: Any, path: str = "config") -> Any:
    """Replaces ${NAME} references in string values with environment variables."""
    if isinstance(value, dict):
        return {key: substitute_env(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [substitute_env(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"{path}: environment variable {name} is not set")
            return os.environ[name]

        return ENV_REFERENCE.sub(replace, value)
    return value


def parse_config(raw: Any) -> Config:
    root = _mapping(raw, "config")

    centers_raw = root.get("centers")
    if not isinstance(centers_raw, list) or not centers_raw:
        raise ConfigError("centers: at least one exam center is required")
    centers = tuple(_parse_center(item, f"centers[{index}]") for index, item in enumerate(centers_raw))

    notifications = _mapping(root.get("notifications"), "notifications")
    return Config(
        centers=centers,
        search=_parse_search(_mapping(root.get("search"), "search")),
        polling=_parse_polling(_mapping(root.get("polling"), "polling")),
        payment=_parse_payment(_mapping(root.get("payment"), "payment")),
        browser=_parse_browser(_mapping(root.get("browser"), "browser")),
        email=_parse_email(notifications.get("email"), "notifications.email"),
        callmebot=_parse_callmebot(notifications.get("callmebot"), "notifications.callmebot"),
        logging=_parse_logging(_mapping(root.get("logging"), "logging")),
        system=SystemConfig(
            prevent_sleep=_as_bool(
                _get(_mapping(root.get("system"), "system"), "prevent_sleep", "system", SystemConfig().prevent_sleep),
                "system.prevent_sleep",
            ),
        ),
        session=_parse_session(_mapping(root.get("session"), "session")),
    )


def _parse_center(raw: Any, path: str) -> Center:
    data = _mapping(raw, path)
    return Center(
        id=_as_int(_get(data, "id", path), f"{path}.id", minimum=1),
        name=_as_str(_get(data, "name", path), f"{path}.name"),
    )


def _parse_search(data: dict[str, Any]) -> SearchConfig:
    defaults = SearchConfig()
    start_from = _as_time(_get(data, "start_time_from", "search", defaults.start_time_from), "search.start_time_from")
    start_to = _as_time(_get(data, "start_time_to", "search", defaults.start_time_to), "search.start_time_to")
    if start_from > start_to:
        raise ConfigError("search: start_time_from must not be later than start_time_to")
    lead_hours = _as_float(
        _get(data, "min_lead_hours", "search", defaults.min_lead_time.total_seconds() / 3600),
        "search.min_lead_hours",
    )
    return SearchConfig(
        window_days=_as_int(_get(data, "window_days", "search", defaults.window_days), "search.window_days", minimum=1),
        start_time_from=start_from,
        start_time_to=start_to,
        min_lead_time=timedelta(hours=lead_hours),
    )


def _parse_polling(data: dict[str, Any]) -> PollingConfig:
    defaults = PollingConfig()
    removed_keys = {
        "detector_interval_minutes": "polling.check_interval_seconds",
        "full_check_min_interval_minutes": "polling.check_interval_seconds",
        "release_check_delays_minutes": "polling.release_checks_in_window and polling.release_check_grace_minutes",
    }
    for removed, replacement in removed_keys.items():
        if removed in data:
            raise ConfigError(f"polling.{removed}: no longer supported, use {replacement}")
    return PollingConfig(
        check_interval=timedelta(seconds=_as_int(
            _get(data, "check_interval_seconds", "polling", int(defaults.check_interval.total_seconds())),
            "polling.check_interval_seconds",
            minimum=30,
        )),
        release_checks_in_window=_as_int(
            _get(data, "release_checks_in_window", "polling", defaults.release_checks_in_window),
            "polling.release_checks_in_window",
            minimum=1,
        ),
        release_check_grace=_minutes(
            data, "release_check_grace_minutes", "polling", defaults.release_check_grace, minimum=0
        ),
        reservation_reserve=_as_int(
            _get(data, "reservation_reserve_requests", "polling", defaults.reservation_reserve),
            "polling.reservation_reserve_requests",
        ),
        detector_reserve=_as_int(
            _get(data, "detector_reserve_requests", "polling", defaults.detector_reserve),
            "polling.detector_reserve_requests",
        ),
    )


def _parse_payment(data: dict[str, Any]) -> PaymentConfig:
    defaults = PaymentConfig()
    return PaymentConfig(
        hold=_minutes(data, "hold_minutes", "payment", defaults.hold, minimum=1),
        reminder_interval=_minutes(data, "reminder_interval_minutes", "payment", defaults.reminder_interval, minimum=1),
    )


def _parse_browser(data: dict[str, Any]) -> BrowserConfig:
    defaults = BrowserConfig()
    return BrowserConfig(
        profile_dir=Path(_as_str(_get(data, "profile_dir", "browser", str(defaults.profile_dir)), "browser.profile_dir")),
        screenshots_dir=Path(
            _as_str(_get(data, "screenshots_dir", "browser", str(defaults.screenshots_dir)), "browser.screenshots_dir")
        ),
    )


def _parse_session(data: dict[str, Any]) -> SessionConfig:
    default = SessionConfig().renew_after
    default_minutes = int(default.total_seconds() // 60) if default else 0
    minutes = _as_int(_get(data, "renew_after_minutes", "session", default_minutes), "session.renew_after_minutes")
    return SessionConfig(renew_after=timedelta(minutes=minutes) if minutes > 0 else None)


def _parse_logging(data: dict[str, Any]) -> LoggingConfig:
    if not _as_bool(_get(data, "enabled", "logging", True), "logging.enabled"):
        return LoggingConfig(file=None)
    default_file = str(LoggingConfig().file)
    return LoggingConfig(file=Path(_as_str(_get(data, "file", "logging", default_file), "logging.file")))


def _parse_email(raw: Any, path: str) -> EmailConfig | None:
    if raw is None:
        return None
    data = _mapping(raw, path)
    if not _as_bool(_get(data, "enabled", path, True), f"{path}.enabled"):
        return None
    recipients_raw = _get(data, "to", path)
    recipients = recipients_raw if isinstance(recipients_raw, list) else [recipients_raw]
    username = _get(data, "username", path, None)
    password = _get(data, "password", path, None)
    return EmailConfig(
        smtp_host=_as_str(_get(data, "smtp_host", path), f"{path}.smtp_host"),
        smtp_port=_as_int(_get(data, "smtp_port", path, 587), f"{path}.smtp_port", minimum=1),
        starttls=_as_bool(_get(data, "starttls", path, True), f"{path}.starttls"),
        username=None if username is None else _as_str(username, f"{path}.username"),
        password=None if password is None else _as_str(password, f"{path}.password"),
        sender=_as_str(_get(data, "from", path), f"{path}.from"),
        recipients=tuple(_as_str(item, f"{path}.to") for item in recipients),
    )


def _parse_callmebot(raw: Any, path: str) -> CallMeBotConfig | None:
    if raw is None:
        return None
    data = _mapping(raw, path)
    if not _as_bool(_get(data, "enabled", path, True), f"{path}.enabled"):
        return None
    return CallMeBotConfig(
        phone=_as_str(_get(data, "phone", path), f"{path}.phone"),
        api_key=_as_str(_get(data, "api_key", path), f"{path}.api_key"),
    )


def _mapping(raw: Any, path: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: must be a mapping")
    return raw


def _get(data: dict[str, Any], key: str, path: str, default: Any = _REQUIRED) -> Any:
    value = data.get(key)
    if value is None:
        if default is _REQUIRED:
            raise ConfigError(f"{path}.{key}: value is required")
        return default
    return value


def _minutes(data: dict[str, Any], key: str, path: str, default: timedelta, minimum: int) -> timedelta:
    value = _get(data, key, path, int(default.total_seconds() // 60))
    return timedelta(minutes=_as_int(value, f"{path}.{key}", minimum=minimum))


def _as_str(value: Any, path: str) -> str:
    if isinstance(value, (dict, list)):
        raise ConfigError(f"{path}: must be a string")
    text = str(value).strip()
    if not text:
        raise ConfigError(f"{path}: must not be empty")
    return text


def _as_int(value: Any, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{path}: must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: must be an integer") from None
    if number < minimum:
        raise ConfigError(f"{path}: must be at least {minimum}")
    return number


def _as_float(value: Any, path: str) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{path}: must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{path}: must be a number") from None
    if number < 0:
        raise ConfigError(f"{path}: must not be negative")
    return number


def _as_bool(value: Any, path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "0"):
        return False
    raise ConfigError(f"{path}: must be true or false")


def _as_time(value: Any, path: str) -> time:
    if isinstance(value, time):
        return value
    # YAML 1.1 parses unquoted 10:30 as the sexagesimal integer 630 (minutes).
    if isinstance(value, int) and not isinstance(value, bool):
        hours, minutes = divmod(value, 60)
    else:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value).strip())
        if not match:
            raise ConfigError(f"{path}: must be a time in HH:MM format")
        hours, minutes = int(match.group(1)), int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ConfigError(f"{path}: must be a time in HH:MM format")
    return time(hours, minutes)
