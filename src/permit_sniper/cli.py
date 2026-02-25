"""CLI interface for Permit Sniper."""

from __future__ import annotations

import argparse
import sys

from .config import Settings
from .runner import run_monitor, run_once, setup_logging


def main():
    parser = argparse.ArgumentParser(
        prog="permit-sniper",
        description="Monitor Recreation.gov for cancelled river permits",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="monitor",
        choices=["monitor", "check", "status"],
        help=(
            "Command to run: "
            "'monitor' (continuous monitoring), "
            "'check' (single check), "
            "'status' (show current availability)"
        ),
    )
    parser.add_argument(
        "--rivers",
        type=str,
        help="Comma-separated rivers to monitor (middle_fork,main_salmon,selway)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Check interval in minutes (default: 5)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD, default: current year May 28)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD, default: current year Sep 3)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()

    # Load settings from .env, then override with CLI args
    settings = Settings()

    if args.rivers:
        settings.rivers = [r.strip() for r in args.rivers.split(",")]
    if args.interval:
        settings.check_interval_minutes = args.interval
    if args.start_date:
        settings.date_start = args.start_date
    if args.end_date:
        settings.date_end = args.end_date
    if args.log_level:
        settings.log_level = args.log_level

    setup_logging(settings.log_level)

    if args.command in ("check", "status"):
        run_once(settings)
    else:
        run_monitor(settings)


if __name__ == "__main__":
    main()
