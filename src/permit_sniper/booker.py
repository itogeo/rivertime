"""
Playwright-based auto-booker for Recreation.gov permits.
When a cancellation is detected, logs in and adds the permit to cart,
then the notifier fires an urgent "COMPLETE CHECKOUT NOW" email.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime

logger = logging.getLogger(__name__)

RECGOV_BASE = "https://www.recreation.gov"


def _sleep(min_s: float = 0.5, max_s: float = 2.0):
    time.sleep(random.uniform(min_s, max_s))


class BookingResult:
    def __init__(self, success: bool, status: str, message: str, checkout_url: str = ""):
        self.success = success
        self.status = status  # 'in_cart', 'booked', 'failed', 'error'
        self.message = message
        self.checkout_url = checkout_url

    def __repr__(self):
        return f"BookingResult({self.status}: {self.message})"


class PermitBooker:
    def __init__(self, username: str, password: str, headless: bool = True):
        self.username = username
        self.password = password
        self.headless = headless

    def attempt_booking(self, permit_id: str, date_str: str) -> BookingResult:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return BookingResult(
                success=False,
                status="error",
                message="playwright not installed — add it to dependencies",
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/Denver",
            )
            # Mask webdriver signals
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()
            try:
                result = self._run(page, permit_id, date_str)
            except Exception as exc:
                logger.exception(f"Booking error for {date_str}: {exc}")
                result = BookingResult(success=False, status="error", message=str(exc))
            finally:
                browser.close()

        return result

    def _run(self, page, permit_id: str, date_str: str) -> BookingResult:
        # ── 1. Login ──────────────────────────────────────────────────────────
        logger.info("Logging into Recreation.gov...")
        page.goto(f"{RECGOV_BASE}/login", wait_until="networkidle", timeout=30000)
        _sleep(1.0, 2.5)

        email_field = page.locator('input[type="email"], input[name="email"]').first
        email_field.click()
        _sleep(0.3, 0.7)
        email_field.type(self.username, delay=random.randint(60, 140))

        _sleep(0.4, 1.0)
        pw_field = page.locator('input[type="password"]').first
        pw_field.click()
        _sleep(0.3, 0.7)
        pw_field.type(self.password, delay=random.randint(60, 140))

        _sleep(0.6, 1.2)
        page.locator('button[type="submit"]').first.click()

        page.wait_for_url(lambda u: "/login" not in u, timeout=25000)
        _sleep(1.5, 3.0)
        logger.info("Login successful")

        # ── 2. Navigate to the permit availability page ───────────────────────
        permit_url = (
            f"{RECGOV_BASE}/permits/{permit_id}"
            f"/registration/detailed-availability?type=overnight-permit"
        )
        logger.info(f"Loading permit page for {permit_id}...")
        page.goto(permit_url, wait_until="networkidle", timeout=30000)
        _sleep(2.0, 4.0)

        # ── 3. Find and click the target date on the calendar ─────────────────
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # Recreation.gov uses aria-label like "May 13, 2026"
        label = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
        logger.info(f"Searching calendar for: {label}")

        clicked = False
        for attempt in range(10):  # scan up to 10 months forward
            cell = page.locator(f'[aria-label="{label}"]').first
            if cell.count() and cell.is_visible():
                cell.click()
                clicked = True
                _sleep(0.8, 1.8)
                logger.info(f"Clicked date {label}")
                break
            # Advance to next month
            next_btn = page.locator(
                '[aria-label="Next month"], .rdp-nav_button_next, '
                'button[title="Next month"], button:has-text("›")'
            ).first
            if next_btn.count():
                next_btn.click()
                _sleep(0.8, 1.5)
            else:
                logger.warning("No next-month button found")
                break

        if not clicked:
            return BookingResult(
                success=False,
                status="failed",
                message=f"Could not find {date_str} on the calendar (may already be gone)",
            )

        # ── 4. Wait for booking button and click it ───────────────────────────
        _sleep(1.0, 2.5)
        try:
            book_btn = page.locator(
                'button:has-text("Book Now"), button:has-text("Add to Cart"), '
                'button:has-text("Reserve Now"), a:has-text("Book Now")'
            ).first
            book_btn.wait_for(state="visible", timeout=15000)
            _sleep(0.5, 1.0)
            book_btn.click()
            _sleep(2.5, 5.0)
        except Exception:
            return BookingResult(
                success=False,
                status="failed",
                message=(
                    f"No booking button appeared for {date_str} — "
                    "date may have been taken before we could click"
                ),
            )

        current_url = page.url

        # ── 5. Determine outcome ──────────────────────────────────────────────
        if any(kw in current_url for kw in ("cart", "checkout", "booking", "reservation")):
            logger.info(f"SUCCESS — permit in cart: {current_url}")
            return BookingResult(
                success=True,
                status="in_cart",
                message=(
                    f"Permit for {date_str} is IN YOUR CART. "
                    f"You have ~15 minutes to complete checkout!"
                ),
                checkout_url=current_url,
            )

        content = page.content().lower()
        if any(kw in content for kw in ("confirmation", "booked", "reservation confirmed")):
            return BookingResult(
                success=True,
                status="booked",
                message=f"Permit for {date_str} appears BOOKED. Check your email.",
                checkout_url=current_url,
            )

        # Got somewhere unexpected — send URL so user can check manually
        return BookingResult(
            success=False,
            status="unknown",
            message=f"Booking status unclear. Current URL: {current_url}",
            checkout_url=current_url,
        )
