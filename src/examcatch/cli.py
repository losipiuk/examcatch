"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from examcatch.api import ServiceApi
from examcatch.app import App
from examcatch.browser import Session, open_browser
from examcatch.config import ConfigError, load_config
from examcatch.console import ConsoleInput
from examcatch.errors import FatalError
from examcatch.notify import build_notifier
from examcatch.ratelimit import RateLimiter
from examcatch.reservation import ReservationFlow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="examcatch",
        description="Watches info-kierowca.pl for practical driving exam slots and reserves one up to the payment step.",
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.yaml"),
        help="path to the YAML configuration file (default: config.yaml)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2

    notifier = build_notifier(config)
    console = ConsoleInput()
    try:
        with open_browser(config.browser) as page:
            limiter = RateLimiter()
            api = ServiceApi(page, limiter)
            session = Session(page, notifier)
            flow = ReservationFlow(page, api, notifier, config.browser.screenshots_dir)
            App(config, session, api, limiter, flow, notifier, console).run()
    except KeyboardInterrupt:
        notifier.info("Stopped.")
    except FatalError as e:
        notifier.important("ExamCatch stopped", str(e))
        return 1
    return 0
