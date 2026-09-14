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
from examcatch.notify import Notifier, build_notifier
from examcatch.ratelimit import RateLimiter
from examcatch.reservation import DRY_RUN_BLOCKED_ROUTES, ReservationFlow


def _test_notifications(notifier: Notifier) -> int:
    if not notifier.channels:
        print("No notification channels are configured.", file=sys.stderr)
        return 1
    failed = False
    for channel in notifier.channels:
        try:
            channel.send("Test notification", "This is a test message from ExamCatch.")
            print(f"{channel.name}: sent")
        except Exception as e:  # report every channel's result
            print(f"{channel.name}: failed: {e}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


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
    parser.add_argument(
        "--test-notifications",
        action="store_true",
        help="send a test message through every configured notification channel and exit",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2

    notifier = build_notifier(config)
    if args.test_notifications:
        return _test_notifications(notifier)
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
