"""Availability checker with state tracking to detect cancellations."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .api import RecGovClient, parse_availability
from .config import Settings

logger = logging.getLogger(__name__)


class AvailabilityChange:
    """Represents a detected change in permit availability."""

    def __init__(
        self,
        river_name: str,
        permit_id: str,
        date: str,
        old_status: str | None,
        new_status: str,
        remaining: int,
        total: int,
    ):
        self.river_name = river_name
        self.permit_id = permit_id
        self.date = date
        self.old_status = old_status
        self.new_status = new_status
        self.remaining = remaining
        self.total = total
        self.detected_at = datetime.now().isoformat()

    @property
    def is_new_opening(self) -> bool:
        """True if this represents a newly available permit (cancellation)."""
        return (
            self.new_status == "Available"
            and self.old_status in (None, "Reserved", "Not Available", "Not Reservable")
        )

    @property
    def booking_url(self) -> str:
        return f"https://www.recreation.gov/permits/{self.permit_id}"

    def __repr__(self) -> str:
        return (
            f"AvailabilityChange({self.river_name}, {self.date}, "
            f"{self.old_status} -> {self.new_status}, "
            f"{self.remaining}/{self.total} spots)"
        )


class StateTracker:
    """Tracks permit availability state between checks using a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self._state: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._state = json.load(f)
                logger.debug(f"Loaded state from {self.path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state file: {e}")
                self._state = {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._state, f, indent=2)
        logger.debug(f"Saved state to {self.path}")

    def get_previous(self, permit_id: str) -> dict[str, dict]:
        """Get previous availability data for a permit."""
        return self._state.get(permit_id, {})

    def update(self, permit_id: str, availability: dict[str, dict]):
        """Update stored state for a permit."""
        self._state[permit_id] = availability
        self._save()


class PermitChecker:
    """Main checker that polls for availability and detects changes."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = StateTracker(settings.state_path)
        self.client = RecGovClient(jitter_max=settings.jitter_max_seconds)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def check_all(self) -> list[AvailabilityChange]:
        """Check all configured rivers and return any new openings."""
        all_changes: list[AvailabilityChange] = []

        for river in self.settings.get_river_configs():
            try:
                changes = self._check_river(river)
                all_changes.extend(changes)
            except Exception as e:
                logger.error(f"Error checking {river['name']}: {e}")

        return all_changes

    def _check_river(self, river: dict) -> list[AvailabilityChange]:
        """Check a single river for availability changes."""
        permit_id = river["permit_id"]
        river_name = river["name"]
        notify_after = river.get("notify_after")

        logger.info(f"Checking {river_name} (permit {permit_id})...")

        # Fetch current availability month by month across the season
        raw_data = self.client.get_season_availability(
            permit_id,
            self.settings.effective_date_start,
            self.settings.effective_date_end,
        )

        # Parse into clean availability map
        current: dict[str, dict] = {}
        for month_key, month_data in raw_data.items():
            parsed = parse_availability(month_data)
            current.update(parsed)

        if not current:
            logger.warning(f"No availability data returned for {river_name}")
            return []

        # Compare against previous state
        previous = self.state.get_previous(permit_id)
        changes = self._detect_changes(river_name, permit_id, previous, current)

        # Filter out dates before notify_after (e.g., Main Salmon is open until Jun 16)
        if notify_after and changes:
            before = len(changes)
            changes = [c for c in changes if c.date >= notify_after]
            skipped = before - len(changes)
            if skipped:
                logger.info(
                    f"  Skipped {skipped} opening(s) before {notify_after} "
                    f"(permits freely available until then)"
                )

        # Update state
        self.state.update(permit_id, current)

        # Log summary
        available_dates = [d for d, info in current.items() if info["status"] == "Available"]
        logger.info(
            f"  {river_name}: {len(available_dates)} available dates, "
            f"{len(changes)} new openings detected"
        )

        return changes

    def _detect_changes(
        self,
        river_name: str,
        permit_id: str,
        previous: dict[str, dict],
        current: dict[str, dict],
    ) -> list[AvailabilityChange]:
        """Compare two availability snapshots and find new openings."""
        changes: list[AvailabilityChange] = []

        for date_str, curr_info in current.items():
            prev_info = previous.get(date_str)
            old_status = prev_info["status"] if prev_info else None
            new_status = curr_info["status"]

            # We care about dates that became available
            if new_status == "Available" and old_status != "Available":
                change = AvailabilityChange(
                    river_name=river_name,
                    permit_id=permit_id,
                    date=date_str,
                    old_status=old_status,
                    new_status=new_status,
                    remaining=curr_info.get("remaining", 0),
                    total=curr_info.get("total", 0),
                )
                changes.append(change)
                logger.info(f"  NEW OPENING: {river_name} on {date_str} ({change.remaining} spots)")

        # Sort by date
        changes.sort(key=lambda c: c.date)
        return changes

    def get_current_availability(self) -> dict[str, dict[str, dict]]:
        """Get current availability for all rivers (for display/status)."""
        result = {}
        for river in self.settings.get_river_configs():
            permit_id = river["permit_id"]
            river_name = river["name"]

            try:
                raw_data = self.client.get_season_availability(
                    permit_id,
                    self.settings.effective_date_start,
                    self.settings.effective_date_end,
                )
                current: dict[str, dict] = {}
                for month_key, month_data in raw_data.items():
                    parsed = parse_availability(month_data)
                    current.update(parsed)
                result[river_name] = current
            except Exception as e:
                logger.error(f"Error fetching {river_name}: {e}")
                result[river_name] = {}

        return result
