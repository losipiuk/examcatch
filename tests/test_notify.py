import io
from datetime import datetime

import pytest

from examcatch import notify
from examcatch.config import CallMeBotConfig
from examcatch.models import WARSAW
from examcatch.notify import CallMeBotChannel, Notifier

CONFIG = CallMeBotConfig(phone="+48123456789", api_key="secret-key")


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def respond_with(monkeypatch: pytest.MonkeyPatch, body: str) -> list[str]:
    requested: list[str] = []

    def fake_urlopen(url: str, timeout: int) -> FakeResponse:
        requested.append(url)
        return FakeResponse(body.encode())

    monkeypatch.setattr(notify, "urlopen", fake_urlopen)
    return requested


def test_callmebot_accepts_queued_message(monkeypatch):
    requested = respond_with(
        monkeypatch,
        "<p>Message to: +48123456789<br>Text to send: hi<br><b>Message queued.</b> You will receive it in a few seconds.",
    )

    CallMeBotChannel(CONFIG).send("Subject", "Body")

    assert len(requested) == 1
    assert "apikey=secret-key" in requested[0]


def test_callmebot_error_page_raises_without_leaking_api_key(monkeypatch):
    respond_with(monkeypatch, "<p><b>APIKey is invalid: secret-key</b></p>")

    with pytest.raises(RuntimeError) as error:
        CallMeBotChannel(CONFIG).send("Subject", "Body")

    assert "APIKey is invalid" in str(error.value)
    assert "secret-key" not in str(error.value)


class FailingChannel:
    name = "broken"

    def send(self, subject: str, message: str) -> None:
        raise RuntimeError("boom")


class RecordingChannel:
    name = "recording"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, message: str) -> None:
        self.sent.append((subject, message))


def test_failing_channel_does_not_stop_other_channels():
    out = io.StringIO()
    recording = RecordingChannel()
    notifier = Notifier([FailingChannel(), recording], out=out, clock=lambda: datetime(2026, 9, 14, tzinfo=WARSAW))

    notifier.important("Exam reserved", "details")

    assert recording.sent == [("Exam reserved", "details")]
    assert "Sending broken notification failed: boom" in out.getvalue()
