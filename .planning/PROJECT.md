# Traefik Sentinel

## What This Is

A lightweight security dashboard for Traefik reverse proxy access logs with real-time intruder detection, automatic IP blocking, AbuseIPDB integration, and Telegram alerting. Built for self-hosters who want to monitor and protect their services without heavy infrastructure.

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
- Telegram notifications for security events — existing (but problematic)
- Log retention and cleanup policies — existing
- Docker deployment — existing

### Active

- [ ] Smart Telegram alerting: only critical threats trigger immediate alerts
- [ ] Daily digest: summary message with blocked IPs count, attack types, top attackers, traffic overview
- [ ] Digest sends only when there is activity to report (no empty digests)
- [ ] Configurable alert severity threshold via environment variable
- [ ] Configurable digest schedule via environment variable

### Out of Scope

- Dashboard UI changes — dashboard works fine, only notifications need fixing
- Additional detection patterns — current detection is sufficient
- Multi-user / auth on dashboard — assumes private network
- Mobile app — web dashboard is sufficient

## Context

- Production deployment at `/srv/ai-lab/traefik-dashboard/` on Docker port 13923
- Currently every intruder event fires a Telegram message with only a 15-minute per-IP/reason cooldown
- On an internet-facing server this creates massive notification noise from routine scanner traffic
- Honeypot blocks and auto-blocks also send individual notifications even though the threat is already handled
- The operator wants to be notified immediately only for genuine critical threats (SQL injection, real attacks)
- Routine scanner activity, honeypot triggers, and auto-blocks should be summarized in a daily digest
- All config via environment variables, no secrets in repo

## Constraints

- **Tech stack**: Python 3.11 + FastAPI + SQLite + HTMX — no changes to stack
- **Deployment**: Docker container, all config via environment variables
- **Backwards compatible**: Existing Telegram config (BOT_TOKEN, CHAT_ID) must continue to work
- **No external dependencies**: No new services or databases required
- **Language**: All code and messages in English

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Immediate alerts only for critical severity | Reduces noise to actionable items only | -- Pending |
| Daily digest instead of per-event alerts for non-critical | Operator wants one summary per day, not hundreds of individual messages | -- Pending |
| Digest via existing Telegram bot | No new notification channels needed | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-11 after initialization*
