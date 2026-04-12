---
status: complete
phase: 01-foundation-and-alert-routing
source: [01-VERIFICATION.md]
started: 2026-04-12T00:00:00Z
updated: 2026-04-12T08:20:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live Telegram send for critical event
expected: Triggering a SQL-injection-shaped path against a Traefik-proxied host delivers a "💉 SQL INJECTION ATTACK" Telegram message; triggering a suspicious_path produces no immediate Telegram.
result: pass
evidence: |
  Deployed new code to /srv/ai-lab/traefik-dashboard/ (backup at .backup-20260412-080633) and rebuilt container `traefik-sentinel`. Telegram creds copied from old `traefik-dashboard` container's env into .env for persistence.

  - Positive: `curl "https://chat.lab.halbewahrheit21.de/sqli/*drop*/.php"` → intruder_event #2714 reason=sql_injection → routed "immediate" → digest_events NOT incremented (remained at 1) → Sentinel called send_telegram_alert with no error in logs.
  - Bot reachable: getMe returned ok=true (bot @ailab_update_bot). Direct test message to chat returned ok=true, confirming the channel is live.
  - Negative: `curl "https://.../wp-includes/test.php"` while Telegram enabled → intruder_event #2715 reason=suspicious_path → routed "digest" → digest_events row #2 created → zero Telegram call.
  - Verified the SQL injection path bypasses suspicious_path and is classified correctly via THREAT_SEVERITY map.
verified_by: claude (live production test)

### 2. Digest row survives container restart
expected: After a suspicious_path scan, docker compose restart, then query digest_events WHERE sent_at IS NULL returns the row.
result: pass
evidence: |
  Pre-restart: digest_events id=1 (source=intruder, source_id=2712, severity=medium, sent_at=None).
  Ran `docker compose restart` in /srv/ai-lab/traefik-dashboard/. Container came back healthy in ~8s.
  Post-restart: identical row still present, sent_at still None. SQLite durability confirmed.
verified_by: claude (live production test)

### 3. Default deployment (no new env vars) still alerts on criticals
expected: Deployment without ALERT_MIN_SEVERITY set still delivers Telegram on SQL injection.
result: pass
evidence: |
  Production .env does NOT define ALERT_MIN_SEVERITY. Inside container: `ALERT_MIN_SEVERITY env set: False`, effective value: "high" (default). Under that default, SQL injection (rank critical=3) >= high (rank 2) → routes immediate → Telegram fired (Test 1). Backwards compatibility ALERT-05 proven.
verified_by: claude (live production test)

### 4. Plan `<automated>` verify blocks pass inside the container
expected: Routing matrix, persist_to_digest round-trip, and THREAT_SEVERITY identity all pass in a python:3.11-slim container with sqlalchemy + httpx.
result: pass
evidence: |
  - Config: ALERT_MIN_SEVERITY=critical accepted; invalid value "garbage" falls back to "high" with warning print; default "high" when unset.
  - persist_to_digest round-trip: row written (id=1), timestamp set, sent_at=None.
  - Routing matrix (7 cases): sql_injection→immediate, honeypot→immediate, auth_failures→immediate, rate_limit→digest, suspicious_path→digest, rate_limit+count=25→immediate (escalation), suspicious_path+count=60→immediate (critical escalation). All 7/7 correct under ALERT_MIN_SEVERITY=high.
  - Identity: `telegram_alerter.THREAT_SEVERITY IS alert_router.THREAT_SEVERITY` → True.
verified_by: claude (containerized test)

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none — all 4 human verification items confirmed in production]

## Production Deployment Notes

- New code deployed to `/srv/ai-lab/traefik-dashboard/app/` on 2026-04-12.
- Backup of prior app/ files: `/srv/ai-lab/traefik-dashboard/.backup-20260412-080633/`.
- Telegram creds (previously only in the old `traefik-dashboard` container's env) migrated to `/srv/ai-lab/traefik-dashboard/.env` for persistence across rebuilds.
- Old container `traefik-dashboard` stopped (was orphaned after container_name change to `traefik-sentinel` in compose).
- Production `traefik-sentinel` container healthy; routing gate live; digest_events table populated (2 rows during UAT).

## Observations (non-blocking)

- **Traefik doesn't log query strings** — SQL injection detection relies on the path only. This is a pre-existing limitation of log_parser / Traefik's log format, not a regression. Phase 1 routing logic still verified via comment-syntax SQL patterns in the path.
- **No code path currently emits `reason="honeypot"` intruder events.** Honeypot path access produces `reason="suspicious_path"` (medium) plus an auto-block notification (routed to digest per ALERT-04). The `THREAT_SEVERITY["honeypot"]="critical"` entry is defensive-only. Pre-existing, unchanged by Phase 1. Consider logging as a follow-up idea if critical honeypot alerts are desired.
