"""Notification system for SMS (Twilio) and email alerts."""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .checker import AvailabilityChange
from .config import Settings

logger = logging.getLogger(__name__)


def format_alert_text(changes: list[AvailabilityChange]) -> str:
    """Format changes into a human-readable alert message."""
    if not changes:
        return ""

    lines = [
        "PERMIT ALERT - New river permit openings detected!",
        f"Detected at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S MT')}",
        "",
    ]

    # Group by river
    by_river: dict[str, list[AvailabilityChange]] = {}
    for change in changes:
        by_river.setdefault(change.river_name, []).append(change)

    for river_name, river_changes in by_river.items():
        lines.append(f"--- {river_name} ---")
        for c in river_changes:
            date_obj = datetime.strptime(c.date, "%Y-%m-%d")
            date_fmt = date_obj.strftime("%a %b %d, %Y")
            lines.append(f"  {date_fmt} - {c.remaining} spot(s) available")
        lines.append(f"  Book now: {river_changes[0].booking_url}")
        lines.append("")

    lines.append("Act fast - these go quickly!")
    return "\n".join(lines)


def format_alert_html(changes: list[AvailabilityChange]) -> str:
    """Format changes into an HTML email body."""
    if not changes:
        return ""

    html_parts = [
        "<html><body>",
        "<h2 style='color: #2d7d46;'>Permit Alert - New Openings Detected!</h2>",
        f"<p style='color: #666;'>Detected at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S MT')}</p>",
    ]

    by_river: dict[str, list[AvailabilityChange]] = {}
    for change in changes:
        by_river.setdefault(change.river_name, []).append(change)

    for river_name, river_changes in by_river.items():
        html_parts.append(f"<h3>{river_name}</h3>")
        html_parts.append("<table style='border-collapse: collapse; width: 100%;'>")
        html_parts.append(
            "<tr style='background: #f0f0f0;'>"
            "<th style='padding: 8px; text-align: left;'>Date</th>"
            "<th style='padding: 8px; text-align: left;'>Spots Available</th>"
            "</tr>"
        )
        for c in river_changes:
            date_obj = datetime.strptime(c.date, "%Y-%m-%d")
            date_fmt = date_obj.strftime("%A, %B %d, %Y")
            html_parts.append(
                f"<tr>"
                f"<td style='padding: 8px; border-bottom: 1px solid #ddd;'>{date_fmt}</td>"
                f"<td style='padding: 8px; border-bottom: 1px solid #ddd; "
                f"color: #2d7d46; font-weight: bold;'>{c.remaining} spot(s)</td>"
                f"</tr>"
            )
        html_parts.append("</table>")
        url = river_changes[0].booking_url
        html_parts.append(
            f"<p><a href='{url}' style='display: inline-block; padding: 10px 20px; "
            f"background: #2d7d46; color: white; text-decoration: none; "
            f"border-radius: 5px; margin-top: 10px;'>Book Now on Recreation.gov</a></p>"
        )

    html_parts.append(
        "<p style='color: #cc0000; font-weight: bold;'>"
        "Act fast - cancelled permits go quickly!</p>"
    )
    html_parts.append("</body></html>")

    return "\n".join(html_parts)


class SMSNotifier:
    """Send SMS alerts via Twilio."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token,
            )
        return self._client

    def send(self, changes: list[AvailabilityChange]) -> bool:
        """Send SMS notifications for availability changes."""
        if not self.settings.sms_enabled:
            logger.debug("SMS notifications disabled (no Twilio credentials)")
            return False

        message_body = format_alert_text(changes)
        if not message_body:
            return False

        # Twilio SMS has a 1600 char limit, truncate if needed
        if len(message_body) > 1500:
            # Summarize instead
            count = len(changes)
            rivers = set(c.river_name for c in changes)
            message_body = (
                f"PERMIT ALERT! {count} new opening(s) detected on "
                f"{', '.join(rivers)}! "
                f"Check Recreation.gov NOW to book. "
                f"Dates: {', '.join(c.date for c in changes[:5])}"
            )
            if count > 5:
                message_body += f" (+{count - 5} more)"

        client = self._get_client()
        success = True

        for to_number in self.settings.twilio_to_numbers:
            try:
                msg = client.messages.create(
                    body=message_body,
                    from_=self.settings.twilio_from_number,
                    to=to_number,
                )
                logger.info(f"SMS sent to {to_number} (SID: {msg.sid})")
            except Exception as e:
                logger.error(f"Failed to send SMS to {to_number}: {e}")
                success = False

        return success


class EmailNotifier:
    """Send email alerts via SMTP."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, changes: list[AvailabilityChange]) -> bool:
        """Send email notifications for availability changes."""
        if not self.settings.email_enabled:
            logger.debug("Email notifications disabled (no SMTP credentials)")
            return False

        text_body = format_alert_text(changes)
        html_body = format_alert_html(changes)
        if not text_body:
            return False

        count = len(changes)
        rivers = set(c.river_name for c in changes)
        subject = f"Permit Alert: {count} new opening(s) on {', '.join(rivers)}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.settings.email_from or self.settings.smtp_username
        msg["To"] = ", ".join(self.settings.email_to)

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.settings.smtp_username, self.settings.smtp_password)
                server.sendmail(
                    msg["From"],
                    self.settings.email_to,
                    msg.as_string(),
                )
            logger.info(f"Email sent to {', '.join(self.settings.email_to)}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


class Notifier:
    """Unified notifier that dispatches to all configured channels."""

    def __init__(self, settings: Settings):
        self.sms = SMSNotifier(settings)
        self.email = EmailNotifier(settings)
        self.settings = settings

    def notify(self, changes: list[AvailabilityChange]) -> bool:
        """Send notifications through all enabled channels."""
        if not changes:
            return False

        new_openings = [c for c in changes if c.is_new_opening]
        if not new_openings:
            logger.info("No new openings to notify about")
            return False

        logger.info(f"Sending notifications for {len(new_openings)} new opening(s)...")

        sms_ok = self.sms.send(new_openings)
        email_ok = self.email.send(new_openings)

        if not sms_ok and not email_ok:
            if not self.settings.sms_enabled and not self.settings.email_enabled:
                logger.warning(
                    "No notification channels configured! "
                    "Set up Twilio SMS or SMTP email in .env"
                )
            return False

        return True
