# STATUS — permit-sniper (river permit cancellation alerts)

**Last meaningful commit:** 2026-05-21 (worker last modified on Cloudflare) · 18 commits · remote `itogeo/rivertime` (note: folder is `permit-sniper`, repo is `rivertime`)

> **STOPPED 2026-09-22 — the cron trigger was removed. It is not watching anything.**

## What it was for
Watch Recreation.gov for cancellations on three Idaho/Montana river permits — Middle Fork
of the Salmon, Main Salmon, Selway — and alert by email and Twilio SMS the moment a date
opens up. `EMAIL_TO` carries four addresses: Ian, itogeospatial, and two friends.

## Why it was stopped
Cloudflare Workers analytics, 24 h to 2026-09-22:

| | |
|---|---|
| successful invocations | 893, CPU **p50 21 ms** / p99 27 ms |
| **killed (`exceededResources`)** | **525**, CPU pinned at the 10 ms free cap |

It was the sole source of the account-wide "Workers hit the free tier CPU time limit
1,000+ times" emails — no other script on the account had a single error. And the part
that matters more than the billing warning: **one check in three never completed**, so the
alerts were unreliable in a way nobody could see from the outside.

Cause is one line: `crons = ["* * * * *"]` — every minute, 1,440 runs/day, each one
fetching three rivers, JSON-parsing the availability payload and diffing division × date
against KV. Too much work for one free-tier invocation.

## Current state
Worker still deployed on Cloudflare with **zero triggers**, which costs nothing. The
`fetch` handler still answers `/check` manually. KV state (`STATE`, namespace
`790fd0e3…`) is intact. Secrets are still set. Nothing was deleted.

## To bring it back — fix the cost first, don't just re-add the trigger
1. `crons = ["*/5 * * * *"]` — 288 runs/day instead of 1,440. Cancellations do not appear
   and vanish inside 60 seconds, so minute granularity was buying nothing.
2. Split `RIVERS` across runs so each invocation parses **one** payload, not three.
3. Redeploy, then check `workersInvocationsAdaptive` for `exceededResources` before
   trusting it.

## To resume, start here
`worker/wrangler.toml` (the stop is documented in place) and `worker/src/index.ts`.
Three other people were on the alert list and were not told it stopped.
