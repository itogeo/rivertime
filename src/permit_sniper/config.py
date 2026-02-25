"""Configuration management using pydantic-settings."""

from __future__ import annotations

import datetime
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Recreation.gov permit IDs for the Four Rivers system
RIVER_PERMITS = {
    "middle_fork": {
        "permit_id": "234623",
        "name": "Middle Fork of the Salmon",
        "division_id": "377",
        "notify_after": None,  # Alert for any date
    },
    "main_salmon": {
        "permit_id": "234622",
        "name": "Main Salmon River",
        "division_id": "376",
        "notify_after": "2026-06-16",  # Open/available until Jun 16, only alert after
    },
    "selway": {
        "permit_id": "234624",
        "name": "Selway River",
        "division_id": "378",
        "notify_after": None,  # Alert for any date
    },
}


def _default_season_start() -> str:
    return f"{datetime.date.today().year}-05-28"


def _default_season_end() -> str:
    return f"{datetime.date.today().year}-09-03"


def _split(val: str) -> list:
    """Split a comma-separated string, filtering blanks."""
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Twilio SMS
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_numbers: str = ""  # comma-separated

    # Email SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""  # comma-separated

    # Monitoring
    check_interval_minutes: int = 5
    rivers: str = "middle_fork,main_salmon,selway"  # comma-separated
    date_start: str = ""
    date_end: str = ""

    # Advanced
    jitter_max_seconds: int = 30
    state_db_path: str = "data/state.json"
    log_level: str = "INFO"

    @property
    def twilio_to_list(self) -> list:
        return _split(self.twilio_to_numbers)

    @property
    def email_to_list(self) -> list:
        return _split(self.email_to)

    @property
    def river_list(self) -> list:
        return _split(self.rivers)

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_to_list)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_username and self.smtp_password and self.email_to_list)

    @property
    def effective_date_start(self) -> str:
        return self.date_start or _default_season_start()

    @property
    def effective_date_end(self) -> str:
        return self.date_end or _default_season_end()

    @property
    def state_path(self) -> Path:
        return Path(self.state_db_path)

    def get_river_configs(self) -> list:
        configs = []
        for key in self.river_list:
            if key in RIVER_PERMITS:
                configs.append(RIVER_PERMITS[key])
        return configs
