"""Configuration management using pydantic-settings."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import List, Union

from pydantic import field_validator
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
    twilio_to_numbers: List[str] = []

    # Email SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: List[str] = []

    # Monitoring
    check_interval_minutes: int = 5
    rivers: List[str] = ["middle_fork", "main_salmon", "selway"]
    date_start: str = ""
    date_end: str = ""

    # Advanced
    jitter_max_seconds: int = 30
    state_db_path: str = "data/state.json"
    log_level: str = "INFO"

    @field_validator("twilio_to_numbers", "email_to", "rivers", mode="before")
    @classmethod
    def split_comma_list(cls, v: Union[str, List[str], None]) -> List[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_to_numbers)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_username and self.smtp_password and self.email_to)

    @property
    def effective_date_start(self) -> str:
        return self.date_start or _default_season_start()

    @property
    def effective_date_end(self) -> str:
        return self.date_end or _default_season_end()

    @property
    def state_path(self) -> Path:
        return Path(self.state_db_path)

    def get_river_configs(self) -> list[dict]:
        configs = []
        for key in self.rivers:
            if key in RIVER_PERMITS:
                configs.append(RIVER_PERMITS[key])
        return configs
