import io
import os

from examcatch import sleep
from examcatch.notify import Notifier


class FakeProcess:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> int:
        return 0


def notifier() -> tuple[Notifier, io.StringIO]:
    out = io.StringIO()
    return Notifier(out=out), out


def test_runs_caffeinate_for_the_block_and_stops_it(monkeypatch):
    started: list[FakeProcess] = []
    monkeypatch.setattr(sleep.shutil, "which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(sleep.subprocess, "Popen", lambda args: started.append(FakeProcess(args)) or started[-1])
    subject, out = notifier()

    with sleep.prevent_sleep(True, subject):
        assert [process.args for process in started] == [["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]]
        assert not started[0].terminated

    assert started[0].terminated
    assert "Preventing idle system sleep" in out.getvalue()


def test_missing_caffeinate_only_warns(monkeypatch):
    monkeypatch.setattr(sleep.shutil, "which", lambda name: None)
    monkeypatch.setattr(sleep.subprocess, "Popen", lambda args: (_ for _ in ()).throw(AssertionError("must not run")))
    subject, out = notifier()

    with sleep.prevent_sleep(True, subject):
        pass

    assert "Cannot prevent system sleep" in out.getvalue()


def test_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(sleep.shutil, "which", lambda name: (_ for _ in ()).throw(AssertionError("must not look up")))
    subject, out = notifier()

    with sleep.prevent_sleep(False, subject):
        pass

    assert out.getvalue() == ""
