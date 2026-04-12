---
status: partial
phase: 01-foundation-and-alert-routing
source: [01-VERIFICATION.md]
started: 2026-04-12T00:00:00Z
updated: 2026-04-12T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live Telegram send for critical event
expected: Triggering `curl "https://<host>/?id=1%27%20UNION%20SELECT%201--"` against a Traefik-proxied host delivers a "CRITICAL THREAT DETECTED" Telegram message within seconds; triggering `/wp-admin` scan produces no immediate Telegram message (routed to digest).
result: [pending]

### 2. Digest row survives container restart
expected: After a suspicious_path scan, `docker compose restart traefik-dashboard`, then `sqlite3 data/dashboard.db "SELECT * FROM digest_events WHERE sent_at IS NULL;"` returns the row with `sent_at IS NULL`.
result: [pending]

### 3. Default deployment (no new env vars) still alerts on criticals
expected: Existing deployment with only `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` set (no `ALERT_MIN_SEVERITY`) still receives Telegram message on SQL injection trigger.
result: [pending]

### 4. Plan `<automated>` verify blocks pass inside the container
expected: Running the three `python -c` blocks from plans 01-01, 01-02, 01-03 inside the Docker image (which has sqlalchemy) prints "OK ..." for routing matrix, persist_to_digest round-trip, and identity check.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
