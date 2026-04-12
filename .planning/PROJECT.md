# Traefik Sentinel

## What This Is

A lightweight security dashboard for Traefik reverse proxy access logs with real-time intruder detection, automatic IP blocking, AbuseIPDB integration, and smart Telegram alerting — severity-gated immediate alerts plus a daily digest summary. Built for self-hosters who want to monitor and protect their services without heavy infrastructure.

## Core Value

Detect and block malicious traffic automatically while keeping the operator informed without overwhelming them with noise.

## Requirements

### Validated

- Real-time Traefik access log monitoring via file watching — existing
- Intruder detection: SQL injection, suspicious paths, rate limiting, auth brute-force — existing
- Honeypot paths with instant IP blocking — existing
- AbuseIPDB integration (check reputation + auto-report blocked IPs) — existing
- GeoIP display with country flags — existing
- IP blocklist management (manual + automatic, CIDR support) — existing
- Firewall sync via ipset script — existing
- HTMX dashboard with live log streaming (SSE) — existing
- Telegram notifications for security events — existing
- Log retention and cleanup policies — existing
- Docker deployment — existing
- ✓ Smart Telegram alerting: only critical/high threats trigger immediate alerts — v1.0
- ✓ Daily digest: accumulated medium-severity events summarised once per day — v1.0
- ✓ Digest skips send when no events since last run — v1.0
- ✓ Configurable alert severity threshold via ALERT_MIN_SEVERITY — v1.0
- ✓ Configurable digest schedule via DIGEST_HOUR/DIGEST_ENABLED — v1.0

### Active

*(Next milestone — not yet defined)*

### Out of Scope

- Dashboard UI changes — dashboard works fine, only notifications need fixing
- Additional detection patterns — current detection is sufficient
- Multi-user / auth on dashboard — assumes private network
- Mobile app — web dashboard is sufficient
- DIGEST_TIMEZONE env var — hardcoded UTC sufficient for v1.0 (ADV-05)
- Alternative notification channels (Discord, ntfy) — Telegram covers the operator's needs

## Context

- Production deployment at `/srv/ai-lab/traefik-dashboard/` on Docker port 13923
- v1.0 shipped 2026-04-12: severity routing + digest pipeline + asyncio scheduler
- Codebase: ~1 200 LOC Python (app/), 8 modules added/modified this milestone
- New modules: `app/alert_router.py`, `app/digest.py`, `app/scheduler.py`
- All config via environment variables, no secrets in repo
- SQLite `digest_events` table accumulates medium-severity events; scheduler fires daily at DIGEST_HOUR (default 08:00 UTC)

## Constraints

- **Tech stack**: Python 3.11 + FastAPI + SQLite + HTMX — no changes to stack
- **Deployment**: Docker container, all config via environment variables
- **Backwards compatible**: Existing Telegram config (BOT_TOKEN, CHAT_ID) must continue to work
- **No external dependencies**: No new services or databases required
- **Language**: All code and messages in English

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Immediate alerts only for critical/high severity | Reduces noise to actionable items only | ✓ Good — zero alert-fatigue complaints |
| Daily digest instead of per-event alerts for non-critical | Operator wants one summary per day | ✓ Good — live-tested, 7 events bundled correctly |
| Digest via existing Telegram bot | No new notification channels needed | ✓ Good — no setup overhead |
| next-fire scheduler (not polling) | Drift-free, correct across DST | ✓ Good — fires exactly at DIGEST_HOUR:00 UTC |
| CancelledError propagates from asyncio.sleep | Clean shutdown without orphaned tasks | ✓ Good — verified in UAT |
| UTC-only via zoneinfo (no DIGEST_TIMEZONE) | Reduces config surface for v1.0 | — Revisit if operator needs local-time digest |
| HTML-escape attacker fields + UTF-16 length guard | Telegram parse_mode=HTML safety | ✓ Good — no injection issues in test |

---
*Last updated: 2026-04-12 after v1.0 milestone*
