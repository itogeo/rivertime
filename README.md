# Permit Sniper

Monitor Recreation.gov for cancelled river permits on Idaho's most coveted rivers:

- **Middle Fork of the Salmon** (Permit ID: 234623)
- **Main Salmon River** (Permit ID: 234622)
- **Selway River** (Permit ID: 234624)

These rivers are managed under the [Four Rivers Lottery](https://www.recreation.gov/permits/234623) system. Permits are extremely competitive - this tool monitors for cancellations and sends you instant SMS/email alerts so you can grab a spot.

## How It Works

1. Polls Recreation.gov's availability API every 5 minutes (configurable)
2. Tracks availability state between checks using a local JSON file
3. Detects when a date transitions from "Reserved" to "Available" (a cancellation)
4. Sends SMS (via Twilio) and/or email alerts with the available dates and a direct booking link

## Quick Start

```bash
# Clone and install
cd permit-sniper
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your notification settings (see Configuration below)

# Run a single check to see current availability
permit-sniper check

# Start continuous monitoring
permit-sniper monitor
```

## Configuration

Copy `.env.example` to `.env` and fill in your settings:

### SMS Notifications (Twilio)

1. Sign up at [twilio.com](https://www.twilio.com/) (free trial includes $15 credit)
2. Get your Account SID, Auth Token, and a phone number
3. Add to `.env`:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1XXXXXXXXXX
TWILIO_TO_NUMBERS=+1XXXXXXXXXX,+1XXXXXXXXXX
```

### Email Notifications (Gmail)

1. Enable [Gmail App Passwords](https://myaccount.google.com/apppasswords) (requires 2FA)
2. Generate an app password
3. Add to `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=you@gmail.com
EMAIL_TO=you@gmail.com,friend@gmail.com
```

### Monitoring Settings

```env
# Check every 5 minutes (recommended: 5-15)
CHECK_INTERVAL_MINUTES=5

# Which rivers to monitor
RIVERS=middle_fork,main_salmon,selway

# Date range (defaults to current year's control season)
DATE_START=2026-05-28
DATE_END=2026-09-03

# Random delay between requests to avoid detection (seconds)
JITTER_MAX_SECONDS=30
```

## Usage

```bash
# Continuous monitoring (runs until you Ctrl+C)
permit-sniper monitor

# Single availability check
permit-sniper check

# Monitor specific rivers only
permit-sniper monitor --rivers middle_fork,selway

# Custom date range
permit-sniper monitor --start-date 2026-06-01 --end-date 2026-08-15

# Faster checks (not recommended - may trigger rate limiting)
permit-sniper monitor --interval 3

# Debug mode (verbose logging)
permit-sniper monitor --log-level DEBUG
```

## Key Dates

| Date | Event |
|------|-------|
| Dec 1 - Jan 31 | Lottery application window |
| ~Feb 14 | Lottery results announced |
| Mar 15 | Deadline for winners to confirm permits |
| **Mar 16 @ 8 AM MT** | **Unclaimed permits released (first-come, first-served)** |
| May 28 - Sep 3 | Control season (permits required) |

**Pro tip**: Start monitoring on March 16 - that's when the biggest batch of cancellations drops. Run the bot with a shorter interval that day.

## Deploy on GitHub Actions (Recommended)

This is the easiest way to run the bot 24/7 without keeping your computer on. GitHub Actions runs the check every 10 minutes for free.

### Setup

1. Push this repo to GitHub (or fork it)

2. Go to your repo on GitHub > **Settings** > **Secrets and variables** > **Actions**

3. Add these **Repository Secrets** (only the ones you want to use):

   **For SMS alerts (Twilio):**
   - `TWILIO_ACCOUNT_SID` - your Twilio Account SID
   - `TWILIO_AUTH_TOKEN` - your Twilio Auth Token
   - `TWILIO_FROM_NUMBER` - your Twilio phone number (e.g., `+1234567890`)
   - `TWILIO_TO_NUMBERS` - comma-separated phone numbers to text (e.g., `+1234567890,+0987654321`)

   **For email alerts (Gmail):**
   - `SMTP_HOST` - `smtp.gmail.com`
   - `SMTP_PORT` - `587`
   - `SMTP_USERNAME` - your Gmail address
   - `SMTP_PASSWORD` - a [Gmail App Password](https://myaccount.google.com/apppasswords) (not your regular password)
   - `EMAIL_FROM` - your Gmail address
   - `EMAIL_TO` - comma-separated emails to notify

4. The workflow runs automatically every 10 minutes. You can also trigger it manually from the **Actions** tab > **Check River Permits** > **Run workflow**.

### How to check if it's working

Go to your repo's **Actions** tab on GitHub. You'll see each run with logs showing what dates are available and whether any cancellations were detected.

## Important Notes

- **This tool only monitors and notifies** - you still need to manually book the permit on Recreation.gov
- Recreation.gov may change their API at any time, which could break this tool
- Be respectful with polling frequency - 5-minute intervals are a good balance
- Cancellations must be made 21+ days before launch date per Forest Service policy
- The tool adds random jitter to requests to avoid looking like a bot

## License

MIT
