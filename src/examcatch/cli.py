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
from examcatch.reservation import DRY_RUN_BLOCKED_ROUTES, ReservationFlow


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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log in, fill in the reservation form for the nearest slot up to the summary step and stop "
        "without submitting anything",
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
        blocked_routes = DRY_RUN_BLOCKED_ROUTES if args.dry_run else ()
        with open_browser(config.browser, blocked_routes, lambda url: notifier.info(f"Blocked request: {url}")) as page:
            limiter = RateLimiter()
            api = ServiceApi(page, limiter)
            session = Session(page, notifier, config.browser.screenshots_dir)
            flow = ReservationFlow(page, api, notifier, config.browser.screenshots_dir)
            app = App(config, session, api, limiter, flow, notifier, console)
            if args.dry_run:
                app.dry_run()
            else:
                app.run()
    except KeyboardInterrupt:
        notifier.info("Stopped.")
    except FatalError as e:
        notifier.important("ExamCatch stopped", str(e))
        return 1
    return 0
