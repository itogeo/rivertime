/**
 * Permit Sniper — Cloudflare Worker
 *
 * Polls Recreation.gov every 2 minutes for river permit cancellations
 * on the Middle Fork Salmon, Main Salmon, and Selway.
 * Sends SMS (Twilio) and/or email (Resend) alerts when openings appear.
 *
 * State is persisted in KV between runs so only genuine transitions
 * from Reserved → Available trigger alerts.
 */

// ── River configuration ──────────────────────────────────────────────────────

interface RiverConfig {
  key: string;
  permitId: string;
  name: string;
  divisionId: string;
  notifyAfter: string;   // YYYY-MM-DD — ignore dates before this
  seasonEnd: string;      // YYYY-MM-DD — ignore dates after this
  autoBookStart: string | null;
  autoBookEnd: string | null;
}

const RIVERS: Record<string, RiverConfig> = {
  middle_fork: {
    key: "middle_fork",
    permitId: "234623",
    name: "Middle Fork of the Salmon",
    divisionId: "377",
    notifyAfter: "2026-05-13",
    seasonEnd: "2026-09-03",
    autoBookStart: "2026-06-10",
    autoBookEnd: "2026-07-25",
  },
  main_salmon: {
    key: "main_salmon",
    permitId: "234622",
    name: "Main Salmon River",
    divisionId: "376",
    notifyAfter: "2026-06-20",
    seasonEnd: "2026-09-07",
    autoBookStart: null,
    autoBookEnd: null,
  },
  selway: {
    key: "selway",
    permitId: "234624",
    name: "Selway River",
    divisionId: "378",
    notifyAfter: "2026-05-15",
    seasonEnd: "2026-07-31",
    autoBookStart: "2026-05-15",
    autoBookEnd: "2026-07-10",
  },
};

const GLOBAL_NOTIFY_AFTER = "2026-03-13";

// Default season window for API queries
const DEFAULT_DATE_START = "2026-05-28";
const DEFAULT_DATE_END = "2026-09-03";

// ── Types ────────────────────────────────────────────────────────────────────

interface Env {
  STATE: KVNamespace;
  RIVERS: string;
  TWILIO_ACCOUNT_SID?: string;
  TWILIO_AUTH_TOKEN?: string;
  TWILIO_FROM?: string;
  TWILIO_TO?: string;          // comma-separated phone numbers
  RESEND_API_KEY?: string;
  EMAIL_FROM?: string;
  EMAIL_TO?: string;            // comma-separated email addresses
}

interface DateAvailability {
  status: "Available" | "Reserved";
  remaining: number;
  total: number;
}

interface AvailabilityChange {
  riverName: string;
  permitId: string;
  date: string;
  oldStatus: string | null;
  newStatus: string;
  remaining: number;
  total: number;
}

type StateMap = Record<string, DateAvailability>;

// ── Recreation.gov API ───────────────────────────────────────────────────────

const RECGOV_HEADERS: HeadersInit = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  Accept: "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  Referer: "https://www.recreation.gov/",
  Origin: "https://www.recreation.gov",
  "Cache-Control": "no-cache",
};

async function fetchMonthAvailability(
  permitId: string,
  year: number,
  month: number
): Promise<Record<string, DateAvailability>> {
  const startDate = `${year}-${String(month).padStart(2, "0")}-01T00:00:00.000Z`;
  const url = `https://www.recreation.gov/api/permits/${permitId}/availability/month?start_date=${encodeURIComponent(startDate)}`;

  const resp = await fetch(url, { headers: RECGOV_HEADERS });
  if (!resp.ok) {
    console.error(`API ${resp.status} for permit ${permitId} month ${year}-${month}`);
    return {};
  }

  const data: any = await resp.json();
  return parseAvailability(data);
}

function parseAvailability(raw: any): Record<string, DateAvailability> {
  const result: Record<string, DateAvailability> = {};

  const payload = raw?.payload;
  if (!payload?.availability) return result;

  for (const divData of Object.values(payload.availability) as any[]) {
    const dateAvail = divData?.date_availability;
    if (!dateAvail) continue;

    for (const [dateKey, info] of Object.entries(dateAvail) as [string, any][]) {
      const date = parseDateKey(dateKey);
      if (!date) continue;

      const remaining = info.remaining ?? 0;
      const total = info.total ?? 0;
      const status: "Available" | "Reserved" = remaining > 0 ? "Available" : "Reserved";

      if (result[date]) {
        result[date].remaining += remaining;
        result[date].total += total;
        if (remaining > 0) result[date].status = "Available";
      } else {
        result[date] = { status, remaining, total };
      }
    }
  }

  return result;
}

function parseDateKey(key: string): string | null {
  if (!key) return null;
  if (key.length === 10 && key[4] === "-" && key[7] === "-") return key;
  if (key.includes("T")) return key.slice(0, 10);
  return null;
}

async function fetchSeasonAvailability(
  permitId: string,
  startDate: string,
  endDate: string
): Promise<Record<string, DateAvailability>> {
  const start = new Date(startDate + "T00:00:00Z");
  const end = new Date(endDate + "T00:00:00Z");
  const all: Record<string, DateAvailability> = {};

  // Walk month by month from the 1st of the start month
  let current = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), 1));

  while (current <= end) {
    const year = current.getUTCFullYear();
    const month = current.getUTCMonth() + 1;

    // Small random delay (200-800ms) between requests to be polite
    await sleep(200 + Math.random() * 600);

    const monthData = await fetchMonthAvailability(permitId, year, month);
    Object.assign(all, monthData);

    // Advance to next month
    current = new Date(Date.UTC(year, current.getUTCMonth() + 1, 1));
  }

  return all;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ── Change detection ─────────────────────────────────────────────────────────

function detectChanges(
  river: RiverConfig,
  previous: StateMap,
  current: StateMap
): AvailabilityChange[] {
  const changes: AvailabilityChange[] = [];

  for (const [date, curr] of Object.entries(current)) {
    const prev = previous[date];
    const oldStatus = prev?.status ?? null;

    if (curr.status === "Available" && oldStatus !== "Available") {
      // Filter by date windows
      if (date < GLOBAL_NOTIFY_AFTER) continue;
      if (date < river.notifyAfter) continue;
      if (date > river.seasonEnd) continue;

      changes.push({
        riverName: river.name,
        permitId: river.permitId,
        date,
        oldStatus,
        newStatus: curr.status,
        remaining: curr.remaining,
        total: curr.total,
      });
    }
  }

  changes.sort((a, b) => a.date.localeCompare(b.date));
  return changes;
}

// ── Notifications ────────────────────────────────────────────────────────────

function formatSmsText(changes: AvailabilityChange[]): string {
  const rivers = [...new Set(changes.map((c) => c.riverName))];
  const lines = [`PERMIT ALERT! ${changes.length} new opening(s)!`, ""];

  for (const river of rivers) {
    const riverChanges = changes.filter((c) => c.riverName === river);
    lines.push(`${river}:`);
    for (const c of riverChanges) {
      const d = new Date(c.date + "T12:00:00Z");
      const fmt = d.toLocaleDateString("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      });
      lines.push(`  ${fmt} — ${c.remaining} spot(s)`);
    }
    lines.push(`  https://www.recreation.gov/permits/${riverChanges[0].permitId}`);
    lines.push("");
  }

  lines.push("Book NOW — these go fast!");

  const text = lines.join("\n");
  // Twilio SMS limit is 1600 chars
  if (text.length > 1500) {
    return (
      `PERMIT ALERT! ${changes.length} opening(s) on ${rivers.join(", ")}! ` +
      `Dates: ${changes.slice(0, 5).map((c) => c.date).join(", ")}` +
      (changes.length > 5 ? ` (+${changes.length - 5} more)` : "") +
      ` — Check Recreation.gov NOW!`
    );
  }
  return text;
}

function formatEmailHtml(changes: AvailabilityChange[]): string {
  const rivers = [...new Set(changes.map((c) => c.riverName))];

  let html = `<html><body>
    <h2 style="color: #2d7d46;">Permit Alert — New Openings Detected!</h2>
    <p style="color: #666;">Detected at: ${new Date().toISOString()}</p>`;

  for (const river of rivers) {
    const riverChanges = changes.filter((c) => c.riverName === river);
    const permitId = riverChanges[0].permitId;

    html += `<h3>${river}</h3>`;
    html += `<table style="border-collapse: collapse; width: 100%;">`;
    html += `<tr style="background: #f0f0f0;">
      <th style="padding: 8px; text-align: left;">Date</th>
      <th style="padding: 8px; text-align: left;">Spots</th>
    </tr>`;

    for (const c of riverChanges) {
      const d = new Date(c.date + "T12:00:00Z");
      const fmt = d.toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
        timeZone: "UTC",
      });
      html += `<tr>
        <td style="padding: 8px; border-bottom: 1px solid #ddd;">${fmt}</td>
        <td style="padding: 8px; border-bottom: 1px solid #ddd; color: #2d7d46; font-weight: bold;">${c.remaining}</td>
      </tr>`;
    }

    html += `</table>`;
    html += `<p><a href="https://www.recreation.gov/permits/${permitId}"
      style="display: inline-block; padding: 10px 20px; background: #2d7d46;
      color: white; text-decoration: none; border-radius: 5px; margin-top: 10px;">
      Book Now on Recreation.gov</a></p>`;
  }

  html += `<p style="color: #cc0000; font-weight: bold;">Act fast — cancelled permits go quickly!</p>`;
  html += `</body></html>`;
  return html;
}

async function sendTwilioSms(env: Env, changes: AvailabilityChange[]): Promise<boolean> {
  if (!env.TWILIO_ACCOUNT_SID || !env.TWILIO_AUTH_TOKEN || !env.TWILIO_FROM || !env.TWILIO_TO) {
    return false;
  }

  const body = formatSmsText(changes);
  const recipients = env.TWILIO_TO.split(",").map((s) => s.trim()).filter(Boolean);
  const auth = btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`);
  let allOk = true;

  for (const to of recipients) {
    try {
      const resp = await fetch(
        `https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/Messages.json`,
        {
          method: "POST",
          headers: {
            Authorization: `Basic ${auth}`,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({
            From: env.TWILIO_FROM,
            To: to,
            Body: body,
          }),
        }
      );
      if (!resp.ok) {
        console.error(`Twilio SMS to ${to} failed: ${resp.status} ${await resp.text()}`);
        allOk = false;
      } else {
        console.log(`SMS sent to ${to}`);
      }
    } catch (e) {
      console.error(`Twilio SMS error for ${to}:`, e);
      allOk = false;
    }
  }

  return allOk;
}

async function sendResendEmail(env: Env, changes: AvailabilityChange[]): Promise<boolean> {
  if (!env.RESEND_API_KEY || !env.EMAIL_TO) {
    return false;
  }

  const recipients = env.EMAIL_TO.split(",").map((s) => s.trim()).filter(Boolean);
  const from = env.EMAIL_FROM || "Permit Sniper <permits@resend.dev>";
  let allOk = true;

  // Send one email per river+date so the subject is specific
  for (const c of changes) {
    const d = new Date(c.date + "T12:00:00Z");
    const dateFmt = d.toLocaleDateString("en-US", {
      weekday: "short",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
    const subject = `${c.riverName} — ${dateFmt} — ${c.remaining} spot(s) open`;
    const html = formatEmailHtml([c]);
    const text = `PERMIT ALERT: ${c.riverName}\n${dateFmt} — ${c.remaining} spot(s) open\nhttps://www.recreation.gov/permits/${c.permitId}`;

    try {
      const resp = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from,
          to: recipients,
          subject,
          html,
          text,
        }),
      });

      if (!resp.ok) {
        console.error(`Resend email failed for ${c.riverName} ${c.date}: ${resp.status} ${await resp.text()}`);
        allOk = false;
      } else {
        console.log(`Email sent: ${subject}`);
      }
    } catch (e) {
      console.error(`Resend email error for ${c.riverName} ${c.date}:`, e);
      allOk = false;
    }
  }

  return allOk;
}

async function notify(env: Env, changes: AvailabilityChange[]): Promise<void> {
  if (changes.length === 0) return;

  const [smsOk, emailOk] = await Promise.all([
    sendTwilioSms(env, changes),
    sendResendEmail(env, changes),
  ]);

  if (!smsOk && !emailOk) {
    console.warn("No notification channels succeeded — check your secrets");
  }
}

// ── Main check logic ─────────────────────────────────────────────────────────

async function checkPermits(env: Env): Promise<void> {
  const riverKeys = (env.RIVERS || "middle_fork,main_salmon,selway")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  const allChanges: AvailabilityChange[] = [];

  for (const key of riverKeys) {
    const river = RIVERS[key];
    if (!river) {
      console.warn(`Unknown river key: ${key}`);
      continue;
    }

    console.log(`Checking ${river.name}...`);

    try {
      const current = await fetchSeasonAvailability(
        river.permitId,
        DEFAULT_DATE_START,
        DEFAULT_DATE_END
      );

      const dateCount = Object.keys(current).length;
      const availCount = Object.values(current).filter((d) => d.status === "Available").length;
      console.log(`  ${river.name}: ${dateCount} dates fetched, ${availCount} available`);

      // Load previous state from KV
      const stateKey = `permit-state:${river.permitId}`;
      const previousRaw = await env.STATE.get(stateKey);
      const previous: StateMap = previousRaw ? JSON.parse(previousRaw) : {};

      // Detect changes
      const changes = detectChanges(river, previous, current);
      if (changes.length > 0) {
        console.log(`  ${changes.length} NEW OPENING(S):`);
        for (const c of changes) {
          console.log(`    ${c.date} — ${c.remaining} spot(s)`);
        }
        allChanges.push(...changes);
      } else {
        console.log(`  No new openings`);
      }

      // Save current state to KV — only if it actually changed.
      // 99% of runs return identical data; writing every time burns through
      // the 1000/day KV put free tier in ~11 hours.
      const newRaw = JSON.stringify(current);
      if (newRaw !== previousRaw) {
        await env.STATE.put(stateKey, newRaw);
        console.log(`  State changed — wrote ${newRaw.length} bytes to KV`);
      }
    } catch (e) {
      console.error(`Error checking ${river.name}:`, e);
    }
  }

  // Send notifications for all new openings
  if (allChanges.length > 0) {
    console.log(`Sending alerts for ${allChanges.length} total opening(s)...`);
    await notify(env, allChanges);
  } else {
    console.log("No new openings across all rivers");
  }
}

// ── Worker entry point ───────────────────────────────────────────────────────

export default {
  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    console.log(`Cron triggered at ${new Date(event.scheduledTime).toISOString()}`);
    ctx.waitUntil(checkPermits(env));
  },

  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // Manual trigger: GET /check
    if (url.pathname === "/check") {
      ctx.waitUntil(checkPermits(env));
      return new Response("Check started — see worker logs (wrangler tail)\n", {
        status: 202,
      });
    }

    // Status endpoint: GET /status
    if (url.pathname === "/status") {
      const riverKeys = (env.RIVERS || "middle_fork,main_salmon,selway").split(",").map((s) => s.trim());
      const status: Record<string, any> = {};

      for (const key of riverKeys) {
        const river = RIVERS[key];
        if (!river) continue;
        const raw = await env.STATE.get(`permit-state:${river.permitId}`);
        if (raw) {
          const state: StateMap = JSON.parse(raw);
          const available = Object.entries(state)
            .filter(([, v]) => v.status === "Available")
            .filter(([d]) => d >= river.notifyAfter && d <= river.seasonEnd)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([d, v]) => ({ date: d, remaining: v.remaining }));
          status[river.name] = {
            totalDatesTracked: Object.keys(state).length,
            availableInWindow: available,
          };
        } else {
          status[river.name] = { state: "no data yet" };
        }
      }

      return new Response(JSON.stringify(status, null, 2), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response(
      "Permit Sniper Worker\n\nGET /check  — trigger a manual check\nGET /status — view current availability state\n",
      { status: 200 }
    );
  },
};
