"""Non-blocking reading of commands typed into the terminal."""

from __future__ import annotations

import queue
import sys
import threading


class ConsoleInput:
    """Reads stdin lines on a daemon thread, so the browser loop can poll for them without blocking."""

    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, name="console-input", daemon=True).start()

    def poll(self) -> str | None:
        try:
            return self._lines.get_nowait()
        except queue.Empty:
            return None

    def drain(self) -> None:
        while self.poll() is not None:
            pass

    def _read(self) -> None:
        for line in sys.stdin:
            self._lines.put(line.strip())
