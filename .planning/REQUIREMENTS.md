# Requirements: Traefik Sentinel — Smart Notifications

**Defined:** 2026-04-12
**Core Value:** Detect and block malicious traffic automatically while keeping the operator informed without overwhelming them with noise.

## v1 Requirements

### Alert Routing

- [ ] **ALERT-01**: System routes intruder events based on severity — critical and high severity events fire immediate Telegram alerts; medium severity events are collected for the digest
- [ ] **ALERT-02**: Critical threats (SQL injection, honeypot) always bypass any suppression and fire immediately, regardless of threshold configuration
- [ ] **ALERT-03**: Operator can configure the minimum severity threshold for immediate alerts via `ALERT_MIN_SEVERITY` environment variable (default: `high`)
- [ ] **ALERT-04**: Auto-block notifications (honeypot blocks, AbuseIPDB auto-blocks) are collected into the digest instead of sending individual Telegram messages
- [ ] **ALERT-05**: Existing Telegram configuration (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) continues to work without changes

### Digest Persistence

- [ ] **DIGEST-01**: Digest-eligible events are persisted to SQLite immediately on detection so that container restarts do not lose accumulated events
- [ ] **DIGEST-02**: Events already stored in `intruder_events` and `blocked_ips` tables are queried directly for digest aggregation (no duplicate storage)
- [ ] **DIGEST-03**: Digest state survives restarts and resumes aggregation on the next scheduled send

### Digest Content

- [ ] **CONTENT-01**: Daily digest includes count of blocked IPs (honeypot + AbuseIPDB auto-blocks) since last digest
- [ ] **CONTENT-02**: Daily digest includes breakdown of attack types (SQL injection, suspicious path, rate limit, auth brute-force) with counts per type
- [ ] **CONTENT-03**: Daily digest includes top 5-10 most active attacker IPs with country flag and event count
- [ ] **CONTENT-04**: Daily digest includes traffic overview (total requests, unique IPs, error rate, top hosts)
- [ ] **CONTENT-05**: Digest message fits within Telegram's 4096-character limit (truncate long lists with "+N more" summary)
- [ ] **CONTENT-06**: Attacker-supplied data (IPs, paths, user agents) is HTML-escaped in the digest message to prevent injection

### Digest Scheduling

- [ ] **SCHED-01**: Digest is sent once per day at a configurable time via `DIGEST_HOUR` environment variable (default: 08:00 UTC)
- [ ] **SCHED-02**: Digest can be disabled via `DIGEST_ENABLED` environment variable (default: `true`)
- [ ] **SCHED-03**: Digest is skipped silently when no events occurred in the window (no empty digest messages)
- [ ] **SCHED-04**: Scheduler runs as an asyncio task inside the FastAPI lifespan so it shares the existing event loop (no new process/worker)
- [ ] **SCHED-05**: Scheduler uses timezone-aware `datetime` with `zoneinfo` (no deprecated `datetime.utcnow()` for scheduling)

## v2 Requirements

### Advanced Alerting

- **ADV-01**: Quiet hours — suppress non-critical alerts during configured night window
- **ADV-02**: Alert rate limiting — max N immediate alerts per hour to prevent Telegram API throttling during burst attacks
- **ADV-03**: Per-reason severity override via config
- **ADV-04**: Multiple digest frequencies (hourly, 4-hour, daily)
- **ADV-05**: Configurable digest timezone (`DIGEST_TIMEZONE` env var)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Dashboard UI changes | Dashboard works fine, only notifications need fixing |
| Additional detection patterns | Current detection is sufficient |
| Multiple notification channels (Slack, email, etc.) | Telegram is the only channel the operator uses |
| Alert acknowledgement / interactive bot | Out of scope for this milestone — one-way notifications only |
| Per-category mute lists | Too complex for single-operator self-hosting |
| APScheduler | Native asyncio is sufficient; APScheduler 3.x has multi-worker footguns |
| In-memory digest buffer | Container restart would lose state; SQLite is already available |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ALERT-01 | Phase 2 | Pending |
| ALERT-02 | Phase 2 | Pending |
| ALERT-03 | Phase 1 | Pending |
| ALERT-04 | Phase 2 | Pending |
| ALERT-05 | Phase 1 | Pending |
| DIGEST-01 | Phase 3 | Pending |
| DIGEST-02 | Phase 3 | Pending |
| DIGEST-03 | Phase 3 | Pending |
| CONTENT-01 | Phase 4 | Pending |
| CONTENT-02 | Phase 4 | Pending |
| CONTENT-03 | Phase 4 | Pending |
| CONTENT-04 | Phase 4 | Pending |
| CONTENT-05 | Phase 4 | Pending |
| CONTENT-06 | Phase 4 | Pending |
| SCHED-01 | Phase 5 | Pending |
| SCHED-02 | Phase 5 | Pending |
| SCHED-03 | Phase 4 | Pending |
| SCHED-04 | Phase 5 | Pending |
| SCHED-05 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 19 total
- Mapped to phases: 19
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-12*
*Last updated: 2026-04-12 after initial definition*
