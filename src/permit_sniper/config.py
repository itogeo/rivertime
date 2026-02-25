"""Configuration management using environment variables."""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Recreation.gov permit IDs for the Four Rivers system
RIVER_PERMITS = {
    "middle_fork": {
        "permit_id": "234623",
        "name": "Middle Fork of the Salmon",
        "division_id": "377",
        "notify_after": None,
    },
    "main_salmon": {
        "permit_id": "234622",
        "name": "Main Salmon River",
        "division_id": "376",
        "notify_after": "2026-06-16",
    },
    "selway": {
        "permit_id": "234624",
        "name": "Selway River",
        "division_id": "378",
        "notify_after": None,
    },
}


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    val = os.environ.get(key, "")
    return int(val) if val else default


def _env_list(key: str, default: str = "") -> list:
    val = os.environ.get(key, default)
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


class Settings:
    def __init__(self):
        # Twilio SMS
        self.twilio_account_sid = _env("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = _env("TWILIO_AUTH_TOKEN")
        self.twilio_from_number = _env("TWILIO_FROM_NUMBER")
        self.twilio_to_list = _env_list("TWILIO_TO_NUMBERS")

        # Email SMTP
        self.smtp_host = _env("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = _env_int("SMTP_PORT", 587)
        self.smtp_username = _env("SMTP_USERNAME")
        self.smtp_password = _env("SMTP_PASSWORD")
        self.email_from = _env("EMAIL_FROM")
        self.email_to_list = _env_list("EMAIL_TO")

        # Monitoring
        self.check_interval_minutes = _env_int("CHECK_INTERVAL_MINUTES", 5)
        self.rivers = _env("RIVERS", "middle_fork,main_salmon,selway")
        self.date_start = _env("DATE_START")
        self.date_end = _env("DATE_END")

        # Advanced
        self.jitter_max_seconds = _env_int("JITTER_MAX_SECONDS", 30)
        self.state_db_path = _env("STATE_DB_PATH", "data/state.json")
        self.log_level = _env("LOG_LEVEL", "INFO")

    @property
    def river_list(self) -> list:
        return [x.strip() for x in self.rivers.split(",") if x.strip()]

    @property
    def sms_enabled(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_to_list)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_username and self.smtp_password and self.email_to_list)

    @property
    def effective_date_start(self) -> str:
        return self.date_start or f"{datetime.date.today().year}-05-28"

    @property
    def effective_date_end(self) -> str:
        return self.date_end or f"{datetime.date.today().year}-09-03"

    @property
    def state_path(self) -> Path:
        return Path(self.state_db_path)

    def get_river_configs(self) -> list:
        configs = []
        for key in self.river_list:
            if key in RIVER_PERMITS:
                configs.append(RIVER_PERMITS[key])
        return configs
