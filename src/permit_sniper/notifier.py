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


def format_alert_html(changes: list[AvailabilityChange], booking_results: dict = None) -> str:
    """Format changes into an HTML email body. booking_results maps date -> BookingResult."""
    if not changes:
        return ""

    booking_results = booking_results or {}
    any_in_cart = any(r.success for r in booking_results.values())

    header_color = "#cc0000" if any_in_cart else "#2d7d46"
    header_text = (
        "🚨 PERMIT IN YOUR CART — COMPLETE CHECKOUT NOW!"
        if any_in_cart
        else "Permit Alert - New Openings Detected!"
    )

    html_parts = [
        "<html><body>",
        f"<h2 style='color: {header_color};'>{header_text}</h2>",
        f"<p style='color: #666;'>Detected at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S MT')}</p>",
    ]

    if any_in_cart:
        html_parts.append(
            "<div style='background: #fff3cd; border: 2px solid #cc0000; padding: 15px; "
            "border-radius: 5px; margin: 10px 0;'>"
            "<strong style='color: #cc0000;'>The bot added a permit to your cart. "
            "You have ~15 minutes to complete checkout before it expires!</strong>"
            "</div>"
        )

    by_river: dict[str, list[AvailabilityChange]] = {}
    for change in changes:
        by_river.setdefault(change.river_name, []).append(change)

    for river_name, river_changes in by_river.items():
        html_parts.append(f"<h3>{river_name}</h3>")
        html_parts.append("<table style='border-collapse: collapse; width: 100%;'>")
        html_parts.append(
            "<tr style='background: #f0f0f0;'>"
            "<th style='padding: 8px; text-align: left;'>Date</th>"
            "<th style='padding: 8px; text-align: left;'>Spots</th>"
            "<th style='padding: 8px; text-align: left;'>Bot Status</th>"
            "</tr>"
        )
        for c in river_changes:
            date_obj = datetime.strptime(c.date, "%Y-%m-%d")
            date_fmt = date_obj.strftime("%A, %B %d, %Y")
            result = booking_results.get(c.date)
            if result:
                if result.success:
                    bot_status = "<span style='color: #cc0000; font-weight: bold;'>IN CART ✓</span>"
                else:
                    bot_status = f"<span style='color: #999;'>Not booked: {result.message[:60]}</span>"
            else:
                bot_status = "<span style='color: #999;'>—</span>"
            html_parts.append(
                f"<tr>"
                f"<td style='padding: 8px; border-bottom: 1px solid #ddd;'>{date_fmt}</td>"
                f"<td style='padding: 8px; border-bottom: 1px solid #ddd; "
                f"color: #2d7d46; font-weight: bold;'>{c.remaining}</td>"
                f"<td style='padding: 8px; border-bottom: 1px solid #ddd;'>{bot_status}</td>"
                f"</tr>"
            )
        html_parts.append("</table>")

        # If something is in cart, show checkout URL prominently
        for c in river_changes:
            result = booking_results.get(c.date)
            if result and result.success and result.checkout_url:
                html_parts.append(
                    f"<p><a href='{result.checkout_url}' "
                    f"style='display: inline-block; padding: 14px 28px; "
                    f"background: #cc0000; color: white; text-decoration: none; "
                    f"border-radius: 5px; margin-top: 10px; font-size: 16px; font-weight: bold;'>"
                    f"Complete Checkout NOW →</a></p>"
                )
                break
        else:
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

        for to_number in self.settings.twilio_to_list:
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

    def send(self, changes: list[AvailabilityChange], booking_results: dict = None) -> bool:
        """Send email notifications for availability changes."""
        if not self.settings.email_enabled:
            logger.debug("Email notifications disabled (no SMTP credentials)")
            return False

        booking_results = booking_results or {}
        text_body = format_alert_text(changes)
        html_body = format_alert_html(changes, booking_results=booking_results)
        if not text_body:
            return False

        count = len(changes)
        rivers = set(c.river_name for c in changes)
        any_in_cart = any(r.success for r in booking_results.values())
        subject = (
            f"🚨 PERMIT IN CART — Complete Checkout NOW: {', '.join(rivers)}"
            if any_in_cart
            else f"Permit Alert: {count} new opening(s) on {', '.join(rivers)}"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.settings.email_from or self.settings.smtp_username
        msg["To"] = ", ".join(self.settings.email_to_list)

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
                    self.settings.email_to_list,
                    msg.as_string(),
                )
            logger.info(f"Email sent to {', '.join(self.settings.email_to_list)}")
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

    def notify(self, changes: list[AvailabilityChange], booking_results: dict = None) -> bool:
        """Send notifications through all enabled channels."""
        if not changes:
            return False

        new_openings = [c for c in changes if c.is_new_opening]
        if not new_openings:
            logger.info("No new openings to notify about")
            return False

        logger.info(f"Sending notifications for {len(new_openings)} new opening(s)...")
        booking_results = booking_results or {}

        sms_ok = self.sms.send(new_openings)
        email_ok = self.email.send(new_openings, booking_results=booking_results)

        if not sms_ok and not email_ok:
            if not self.settings.sms_enabled and not self.settings.email_enabled:
                logger.warning(
                    "No notification channels configured! "
                    "Set up Twilio SMS or SMTP email in .env"
                )
            return False

        return True
