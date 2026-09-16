import io
from datetime import datetime

import pytest

from examcatch import notify
from examcatch.config import CallMeBotConfig, EmailConfig, parse_config
from examcatch.models import WARSAW
from examcatch.notify import Attachment, CallMeBotChannel, EmailChannel, Notifier, build_notifier

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

    def send(self, subject: str, message: str, attachments=()) -> None:
        raise RuntimeError("boom")


class RecordingChannel:
    def __init__(self, name: str = "recording") -> None:
        self.name = name
        self.sent: list[tuple[str, str]] = []
        self.attachments: list[Attachment] = []

    def send(self, subject: str, message: str, attachments=()) -> None:
        self.sent.append((subject, message))
        self.attachments.extend(attachments)


def test_failing_channel_does_not_stop_other_channels():
    out = io.StringIO()
    recording = RecordingChannel()
    notifier = Notifier([FailingChannel(), recording], out=out, clock=lambda: datetime(2026, 9, 14, tzinfo=WARSAW))

    notifier.important("Exam reserved", "details")

    assert recording.sent == [("Exam reserved", "details")]
    assert "Sending broken notification failed: boom" in out.getvalue()


def test_important_can_target_channels_and_carry_attachments():
    email, whatsapp = RecordingChannel("e-mail"), RecordingChannel("WhatsApp")
    notifier = Notifier([email, whatsapp], out=io.StringIO())
    qr = Attachment("qr.png", b"png", "image/png")

    notifier.important("Login required", "code", attachments=[qr])
    notifier.important("Logged in", "done", channel_names={"e-mail"})

    assert email.sent == [("Login required", "code"), ("Logged in", "done")]
    assert whatsapp.sent == [("Login required", "code")]
    assert email.attachments == [qr]


class FakeSmtp:
    sent: list = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        pass

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def starttls(self) -> None:
        pass

    def login(self, username: str, password: str) -> None:
        pass

    def send_message(self, message) -> None:
        FakeSmtp.sent.append(message)


def test_email_includes_attachments(monkeypatch):
    FakeSmtp.sent = []
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSmtp)
    config = EmailConfig(
        smtp_host="smtp.example.com", smtp_port=587, starttls=True, username="user", password="secret",
        sender="me@example.com", recipients=("you@example.com",),
    )

    EmailChannel(config).send("Login required", "Scan the code", [Attachment("qr.png", b"\x89PNG", "image/png")])

    message = FakeSmtp.sent[0]
    attachment = next(message.iter_attachments())
    assert message["Subject"] == "ExamCatch: Login required"
    assert attachment.get_filename() == "qr.png"
    assert attachment.get_content_type() == "image/png"
    assert attachment.get_content() == b"\x89PNG"
    assert message.get_body(("plain",)).get_content().strip() == "Scan the code"


def test_messages_go_to_screen_and_log_file():
    out, log = io.StringIO(), io.StringIO()
    notifier = Notifier([], out=out, log=log, clock=lambda: datetime(2026, 9, 15, 10, 0, tzinfo=WARSAW))

    notifier.info("Searching for a slot.")
    notifier.important("Exam reserved", "details")

    expected = "[2026-09-15 10:00:00] Searching for a slot.\n[2026-09-15 10:00:00] *** Exam reserved *** details\n"
    assert out.getvalue() == expected
    assert log.getvalue() == expected


def test_build_notifier_appends_to_log_file(tmp_path):
    log_file = tmp_path / "logs" / "examcatch.log"
    config = parse_config({"centers": [{"id": 25, "name": "WORD"}], "logging": {"file": str(log_file)}})

    for message in ("first run", "second run"):
        notifier = build_notifier(config)
        notifier.info(message)
        notifier.close()

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert [line.split("] ", 1)[1] for line in lines] == ["first run", "second run"]
