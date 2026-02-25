"""Main runner that schedules periodic checks."""

from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime

import schedule
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .checker import PermitChecker
from .config import Settings
from .notifier import Notifier

logger = logging.getLogger(__name__)
console = Console()

_running = True


def _handle_signal(signum, frame):
    global _running
    console.print("\n[yellow]Shutting down gracefully...[/yellow]")
    _running = False


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_banner():
    banner = Text()
    banner.append("PERMIT SNIPER", style="bold green")
    banner.append(" v1.0\n", style="dim")
    banner.append("River permit cancellation monitor for Recreation.gov\n", style="dim")
    banner.append("Middle Fork Salmon | Main Salmon | Selway", style="cyan")
    console.print(Panel(banner, border_style="green"))


def print_availability_table(availability: dict[str, dict[str, dict]]):
    """Print a summary table of current availability."""
    for river_name, dates in availability.items():
        available = {d: info for d, info in sorted(dates.items()) if info["status"] == "Available"}

        if not available:
            console.print(f"  [dim]{river_name}: No available dates[/dim]")
            continue

        table = Table(title=river_name, show_header=True, header_style="bold cyan")
        table.add_column("Date", style="white")
        table.add_column("Day", style="dim")
        table.add_column("Spots", style="green", justify="center")

        for date_str, info in available.items():
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = date_obj.strftime("%A")
                date_fmt = date_obj.strftime("%b %d, %Y")
            except ValueError:
                day_name = ""
                date_fmt = date_str

            table.add_row(
                date_fmt,
                day_name,
                str(info.get("remaining", "?")),
            )

        console.print(table)
        console.print()


def run_check(settings: Settings, checker: PermitChecker, notifier: Notifier):
    """Execute a single check cycle."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"\n[dim]--- Check at {now} ---[/dim]")

    try:
        changes = checker.check_all()

        if changes:
            new_openings = [c for c in changes if c.is_new_opening]
            if new_openings:
                console.print(
                    f"[bold green]Found {len(new_openings)} new opening(s)![/bold green]"
                )
                for c in new_openings:
                    console.print(
                        f"  [green]>> {c.river_name} - {c.date} "
                        f"({c.remaining} spots) - {c.booking_url}[/green]"
                    )
                notifier.notify(changes)
            else:
                console.print("[dim]Changes detected but no new openings[/dim]")
        else:
            console.print("[dim]No changes detected[/dim]")

    except Exception as e:
        logger.error(f"Check failed: {e}")
        console.print(f"[red]Check failed: {e}[/red]")


def run_once(settings: Settings):
    """Run a single check and display results."""
    print_banner()

    console.print("[cyan]Running one-time availability check...[/cyan]\n")

    with PermitChecker(settings) as checker:
        notifier = Notifier(settings)

        # Show current availability
        availability = checker.get_current_availability()
        print_availability_table(availability)

        # Check for changes vs stored state
        changes = checker.check_all()
        if changes:
            new_openings = [c for c in changes if c.is_new_opening]
            if new_openings:
                console.print(
                    f"\n[bold green]Found {len(new_openings)} new opening(s)![/bold green]"
                )
                notifier.notify(changes)
        else:
            console.print("[dim]No changes since last check[/dim]")


def run_monitor(settings: Settings):
    """Run continuous monitoring loop."""
    global _running

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print_banner()

    rivers = ", ".join(r["name"] for r in settings.get_river_configs())
    console.print(f"[cyan]Monitoring:[/cyan] {rivers}")
    console.print(f"[cyan]Season:[/cyan] {settings.effective_date_start} to {settings.effective_date_end}")
    console.print(f"[cyan]Check interval:[/cyan] Every {settings.check_interval_minutes} minutes")

    if settings.sms_enabled:
        console.print(f"[cyan]SMS:[/cyan] Enabled ({len(settings.twilio_to_list)} recipients)")
    else:
        console.print("[yellow]SMS:[/yellow] Disabled (configure Twilio in .env)")

    if settings.email_enabled:
        console.print(f"[cyan]Email:[/cyan] Enabled ({len(settings.email_to_list)} recipients)")
    else:
        console.print("[yellow]Email:[/yellow] Disabled (configure SMTP in .env)")

    console.print()

    with PermitChecker(settings) as checker:
        notifier = Notifier(settings)

        # Run first check immediately
        run_check(settings, checker, notifier)

        # Schedule subsequent checks
        schedule.every(settings.check_interval_minutes).minutes.do(
            run_check, settings, checker, notifier
        )

        next_run = datetime.now()
        while _running:
            schedule.run_pending()
            time.sleep(1)

    console.print("[green]Monitor stopped.[/green]")
