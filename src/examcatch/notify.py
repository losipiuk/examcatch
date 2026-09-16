"""Console output and notifications sent by e-mail and WhatsApp via CallMeBot (specyfikacja.md, 2.10)."""

from __future__ import annotations

import re
import smtplib
import sys
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import Protocol, TextIO
from urllib.parse import urlencode
from urllib.request import urlopen

from examcatch.config import CallMeBotConfig, Config, EmailConfig
from examcatch.models import now

SUBJECT_PREFIX = "ExamCatch: "
SEND_TIMEOUT_SECONDS = 30
CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
# Part of CallMeBot's response for an accepted message: "Message queued. You will receive it in a few seconds."
CALLMEBOT_SUCCESS_MARKER = "Message queued"


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    mime_type: str


class Channel(Protocol):
    name: str

    def send(self, subject: str, message: str, attachments: Sequence[Attachment] = ()) -> None: ...


class EmailChannel:
    name = "e-mail"

    def __init__(self, config: EmailConfig):
        self._config = config

    def send(self, subject: str, message: str, attachments: Sequence[Attachment] = ()) -> None:
        config = self._config
        email = EmailMessage()
        email["Subject"] = SUBJECT_PREFIX + subject
        email["From"] = config.sender
        email["To"] = ", ".join(config.recipients)
        email.set_content(message)
        for attachment in attachments:
            maintype, _, subtype = attachment.mime_type.partition("/")
            email.add_attachment(attachment.content, maintype=maintype, subtype=subtype, filename=attachment.filename)
        if config.smtp_port == 465:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=SEND_TIMEOUT_SECONDS)
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=SEND_TIMEOUT_SECONDS)
        with smtp:
            if config.starttls and config.smtp_port != 465:
                smtp.starttls()
            if config.username:
                smtp.login(config.username, config.password or "")
            smtp.send_message(email)


class CallMeBotChannel:
    name = "WhatsApp"

    def __init__(self, config: CallMeBotConfig):
        self._config = config

    def send(self, subject: str, message: str, attachments: Sequence[Attachment] = ()) -> None:
        # CallMeBot sends text only; attachments are not delivered through this channel.
        query = urlencode({
            "phone": self._config.phone,
            "text": f"{SUBJECT_PREFIX}{subject}\n{message}",
            "apikey": self._config.api_key,
        })
        with urlopen(f"{CALLMEBOT_URL}?{query}", timeout=SEND_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
        # CallMeBot answers HTTP 200 for errors too (e.g. an invalid API key); only a queued message is a success.
        if CALLMEBOT_SUCCESS_MARKER not in body:
            text = " ".join(re.sub(r"<[^>]+>", " ", body).split()).replace(self._config.api_key, "<apikey>")
            raise RuntimeError(f"CallMeBot did not queue the message: {text[:200]}")


class Notifier:
    def __init__(
        self,
        channels: Sequence[Channel] = (),
        out: TextIO = sys.stdout,
        clock: Callable[[], datetime] = now,
        log: TextIO | None = None,
    ):
        self._channels = channels
        self._out = out
        self._clock = clock
        self._log = log

    @property
    def channels(self) -> Sequence[Channel]:
        return self._channels

    def info(self, message: str) -> None:
        """Less important information, shown on the screen and written to the log file only."""
        self._print(message)

    def important(
        self,
        subject: str,
        message: str,
        attachments: Sequence[Attachment] = (),
        channel_names: Collection[str] | None = None,
    ) -> None:
        """Shown on the screen and sent through the configured channels (only `channel_names`, when given)."""
        self._print(f"*** {subject} *** {message}")
        for channel in self._channels:
            if channel_names is not None and channel.name not in channel_names:
                continue
            try:
                channel.send(subject, message, attachments)
            except Exception as e:  # a failing channel must not stop the application or the other channels
                self._print(f"Sending {channel.name} notification failed: {e}")

    def close(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def _print(self, message: str) -> None:
        line = f"[{self._clock():%Y-%m-%d %H:%M:%S}] {message}"
        print(line, file=self._out, flush=True)
        if self._log is not None:
            try:
                print(line, file=self._log, flush=True)
            except OSError:
                pass  # a broken log file must not stop the application


def build_notifier(config: Config) -> Notifier:
    channels: list[Channel] = []
    if config.email:
        channels.append(EmailChannel(config.email))
    if config.callmebot:
        channels.append(CallMeBotChannel(config.callmebot))
    log: TextIO | None = None
    if config.logging.file is not None:
        try:
            config.logging.file.parent.mkdir(parents=True, exist_ok=True)
            log = config.logging.file.open("a", encoding="utf-8")
        except OSError as e:
            print(f"Cannot open the log file {config.logging.file}: {e}. Logging to the screen only.", file=sys.stderr)
    return Notifier(channels, log=log)
