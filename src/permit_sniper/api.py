"""Recreation.gov API client for permit availability."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.recreation.gov"

# Mimic a real browser to avoid bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.recreation.gov/",
    "Origin": "https://www.recreation.gov",
    "Cache-Control": "no-cache",
}


class RecGovClient:
    """Client for querying Recreation.gov permit availability."""

    def __init__(self, jitter_max: int = 30):
        self.jitter_max = jitter_max
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers=HEADERS,
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _jitter(self):
        """Add random delay to avoid detection."""
        if self.jitter_max > 0:
            delay = random.uniform(1, self.jitter_max)
            logger.debug(f"Jitter delay: {delay:.1f}s")
            time.sleep(delay)

    def get_permit_availability(
        self,
        permit_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Fetch permit availability for a date range.

        Args:
            permit_id: Recreation.gov permit ID (e.g., "234623")
            start_date: Start date as YYYY-MM-DD
            end_date: End date as YYYY-MM-DD

        Returns:
            Raw JSON response from the API.
        """
        self._jitter()

        # Try the primary availability endpoint first
        url = f"/api/permits/{permit_id}/availability/month"

        # Recreation.gov expects ISO format with timezone
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        start_iso = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")

        params = {"start_date": start_iso}

        logger.debug(f"Requesting availability: {url} params={params}")

        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"Got response with {len(data)} top-level keys")
            return data
        except httpx.HTTPStatusError as e:
            logger.warning(f"Primary endpoint failed ({e.response.status_code}), trying alternative")
            return self._try_alternative_endpoint(permit_id, start_date, end_date)
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise

    def _try_alternative_endpoint(
        self,
        permit_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """Try alternative API endpoint formats."""
        # Alternative 1: full date range query
        url = f"/api/permits/{permit_id}/availability"
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        params = {
            "start_date": start_dt.strftime("%Y-%m-%dT07:00:00.000Z"),
            "end_date": end_dt.strftime("%Y-%m-%dT00:00:00.000Z"),
            "commercial_acct": "false",
            "is_lottery": "false",
        }

        try:
            time.sleep(2)
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError:
            pass

        # Alternative 2: permitinyo endpoint
        url = f"/api/permitinyo/{permit_id}/availabilityv2"
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "commercial_acct": "false",
        }

        try:
            time.sleep(2)
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"All endpoints failed for permit {permit_id}: {e}")
            raise

    def get_monthly_availability(
        self,
        permit_id: str,
        year: int,
        month: int,
    ) -> dict[str, Any]:
        """Fetch availability for a specific month."""
        start_date = f"{year}-{month:02d}-01"
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"
        return self.get_permit_availability(permit_id, start_date, end_date)

    def get_season_availability(
        self,
        permit_id: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, list[dict]]:
        """Fetch availability across the full control season, month by month.

        Returns a dict mapping date strings to availability info.
        """
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

        all_data: dict[str, Any] = {}
        current = start.replace(day=1)

        while current <= end:
            try:
                month_data = self.get_monthly_availability(
                    permit_id, current.year, current.month
                )
                all_data[f"{current.year}-{current.month:02d}"] = month_data
            except Exception as e:
                logger.error(f"Failed to fetch {current.year}-{current.month:02d}: {e}")

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return all_data


def parse_availability(raw_data: dict[str, Any]) -> dict[str, dict]:
    """Parse raw API response into a clean availability map.

    The actual Recreation.gov response for river permits looks like:
    {
        "payload": {
            "permit_id": "234623",
            "next_available_date": "2026-06-30T00:00:00Z",
            "availability": {
                "377": {
                    "division_id": "377",
                    "date_availability": {
                        "2026-06-01T00:00:00Z": {
                            "total": 7,
                            "remaining": 0,
                            "show_walkup": false,
                            "is_secret_quota": false
                        }, ...
                    }
                }
            }
        }
    }

    Returns:
        Dict mapping date strings (YYYY-MM-DD) to availability info:
        {
            "2026-06-15": {
                "status": "Available",
                "remaining": 2,
                "total": 7,
            }
        }
    """
    availability = {}

    # Primary format: payload -> availability -> division_id -> date_availability
    payload = raw_data.get("payload")
    if isinstance(payload, dict):
        avail_section = payload.get("availability")
        if isinstance(avail_section, dict):
            for div_id, div_data in avail_section.items():
                if not isinstance(div_data, dict):
                    continue
                date_avail = div_data.get("date_availability", {})
                if not isinstance(date_avail, dict):
                    continue
                for date_key, info in date_avail.items():
                    parsed_date = _parse_date_key(date_key)
                    if not parsed_date or not isinstance(info, dict):
                        continue
                    remaining = info.get("remaining", 0)
                    total = info.get("total", 0)
                    status = "Available" if remaining > 0 else "Reserved"

                    # If multiple divisions, sum up availability per date
                    if parsed_date in availability:
                        availability[parsed_date]["remaining"] += remaining
                        availability[parsed_date]["total"] += total
                        if remaining > 0:
                            availability[parsed_date]["status"] = "Available"
                    else:
                        availability[parsed_date] = {
                            "status": status,
                            "remaining": remaining,
                            "total": total,
                        }

    # Fallback: flat date-keyed structure at top level
    if not availability:
        for key, value in raw_data.items():
            parsed_date = _parse_date_key(key)
            if parsed_date and isinstance(value, dict):
                remaining = value.get("remaining", value.get("available", 0))
                total = value.get("total", value.get("capacity", 0))
                status = "Available" if remaining and remaining > 0 else "Reserved"
                availability[parsed_date] = {
                    "status": status,
                    "remaining": remaining,
                    "total": total,
                }

    return availability


def _parse_date_key(key: str) -> str | None:
    """Try to extract a YYYY-MM-DD date from various key formats."""
    if not key or not isinstance(key, str):
        return None

    # Already in YYYY-MM-DD format
    if len(key) == 10 and key[4] == "-" and key[7] == "-":
        return key

    # ISO format: 2026-06-15T00:00:00.000Z or similar
    if "T" in key:
        return key[:10]

    return None
