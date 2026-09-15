"""Keeping the computer awake while ExamCatch runs (specyfikacja.md, section 3).

While the system sleeps, checks stop and the service's session expires after 10 minutes of inactivity.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

from examcatch.notify import Notifier

STOP_TIMEOUT_SECONDS = 5


@contextmanager
def prevent_sleep(enabled: bool, notifier: Notifier) -> Iterator[None]:
    """Prevents idle system sleep for the duration of the block using macOS `caffeinate`."""
    process: subprocess.Popen[bytes] | None = None
    if enabled:
        executable = shutil.which("caffeinate")
        if executable is None:
            notifier.info("Cannot prevent system sleep: 'caffeinate' is not available (macOS only). Keep the computer awake.")
        else:
            # -i blocks idle sleep while the display may still turn off; -w also ends it if ExamCatch dies.
            process = subprocess.Popen([executable, "-i", "-w", str(os.getpid())])
            notifier.info("Preventing idle system sleep while ExamCatch runs.")
    try:
        yield
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
