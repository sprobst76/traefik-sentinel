# Roadmap: Traefik Sentinel — Smart Notifications

## Overview

The existing Telegram alerting fires on every detected event, causing alert fatigue on internet-facing servers. This milestone adds a severity routing gate so only critical/high events trigger immediate messages, accumulates lower-severity events in SQLite, and delivers a single structured daily digest. The build follows a strict dependency chain: wiring first (config, schema, routing), then the digest pipeline (collector, sender, content), then the scheduler that ties everything together.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation and Alert Routing** - Extend config, add digest schema, gate immediate alerts by severity
- [ ] **Phase 2: Digest Pipeline** - Collect medium-severity events to SQLite and send structured daily digest via Telegram
- [ ] **Phase 3: Scheduler and Integration** - Wire asyncio digest scheduler into FastAPI lifespan with configurable time and clean shutdown

## Phase Details

### Phase 1: Foundation and Alert Routing
**Goal**: Immediate Telegram alerts fire only for critical and high severity events; existing deployments continue to work unchanged
**Depends on**: Nothing (first phase)
**Requirements**: ALERT-01, ALERT-02, ALERT-03, ALERT-04, ALERT-05, DIGEST-01, DIGEST-02, DIGEST-03
**Success Criteria** (what must be TRUE):
  1. A SQL injection or honeypot event always sends an immediate Telegram message regardless of any threshold setting
  2. A medium-severity event (suspicious path scan, rate limit) produces no immediate Telegram message
  3. Setting `ALERT_MIN_SEVERITY=critical` via environment variable restricts immediate alerts to critical events only
  4. An existing deployment with only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set continues to receive critical alerts without any configuration change
  5. The `digest_events` SQLite table exists and a medium-severity event is written to it immediately on detection, surviving a container restart
**Plans**: 3 plans
- [x] 01-01-PLAN.md — Config (ALERT_MIN_SEVERITY) and schema (DigestEvent model)
- [x] 01-02-PLAN.md — alert_router module + telegram_alerter refactor
- [x] 01-03-PLAN.md — Call-site wiring in log_watcher and auto_blocker

### Phase 2: Digest Pipeline
**Goal**: Accumulated digest events are aggregated into a well-formatted Telegram message that fits within platform limits and skips sending when there is nothing to report
**Depends on**: Phase 1
**Requirements**: CONTENT-01, CONTENT-02, CONTENT-03, CONTENT-04, CONTENT-05, CONTENT-06, SCHED-03
**Success Criteria** (what must be TRUE):
  1. A manually triggered digest sends a Telegram message containing blocked IP count, attack type breakdown, top attacker IPs with country flag, and traffic overview
  2. A digest message never exceeds 4096 characters; long attacker lists are truncated with an "+N more" summary line
  3. Attacker-controlled content (IPs, paths, user agents) in the digest is HTML-escaped and does not break Telegram HTML parse mode
  4. Calling the digest sender when zero events have occurred since the last send produces no Telegram message
**Plans**: 3 plans
- [ ] 02-01-PLAN.md — app/digest.py module: aggregation, HTML-escaped message build, UTF-16 truncation, send_digest entry + test scaffold
- [ ] 02-02-PLAN.md — POST /api/digest/send manual-trigger endpoint
- [ ] 02-03-PLAN.md — GET /api/digest/preview dry-run endpoint for UAT

### Phase 3: Scheduler and Integration
**Goal**: The daily digest sends automatically at a configurable wall-clock time, starts and stops cleanly with the FastAPI application, and uses correct timezone-aware scheduling
**Depends on**: Phase 2
**Requirements**: SCHED-01, SCHED-02, SCHED-04, SCHED-05
**Success Criteria** (what must be TRUE):
  1. The digest fires automatically at the time configured via `DIGEST_HOUR` (default 08:00 UTC) without manual intervention
  2. Setting `DIGEST_ENABLED=false` prevents the digest from sending while leaving immediate alerts unaffected
  3. The application starts and shuts down cleanly with no event loop errors or orphaned asyncio tasks
  4. Scheduling uses timezone-aware `datetime` with `zoneinfo`; no `datetime.utcnow()` calls appear in scheduling code
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation and Alert Routing | 0/3 | Not started | - |
| 2. Digest Pipeline | 0/3 | Not started | - |
| 3. Scheduler and Integration | 0/TBD | Not started | - |
