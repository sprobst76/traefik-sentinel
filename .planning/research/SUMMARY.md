# Project Research Summary

**Project:** Traefik Sentinel — Smart Notification Milestone
**Domain:** Security monitoring alert aggregation and digest notifications
**Researched:** 2026-04-11
**Confidence:** HIGH

## Executive Summary

Traefik Sentinel is a self-hosted Traefik access log security dashboard that currently sends a Telegram alert for every detected intruder event, subject only to a 15-minute per-IP/reason cooldown. On an internet-facing server this produces dozens to hundreds of individual messages daily from routine scanner traffic — the classic alert fatigue problem. The milestone is surgical: add a severity routing gate that sends only critical/high events immediately, accumulate medium/low events in SQLite, and deliver a single daily digest. No new services, no new databases, no new Python dependencies beyond one optional addition for scheduling.

The recommended implementation approach follows a strict layered build order: extend `config.py` with three env vars, add a `digest_events` table to the existing SQLite database, introduce a thin `AlertRouter` module that replaces the single `send_alert_sync()` call in `log_watcher.py`, build the `DigestCollector` that writes to SQLite, build the `DigestSender` that formats and sends the aggregated Telegram message, and finally wire the scheduler into the FastAPI lifespan. This order means each component is independently testable before the next is added. The ARCHITECTURE.md research identifies an 8-step build sequence with no circular dependencies.

The primary risk is silent data loss: digest state held in memory is wiped on every container restart. Research across all four files converges on the same mitigation — persist digest events to SQLite immediately on collection, not at send time. Secondary risks are critical alerts being swallowed by a misconfigured severity threshold (sql_injection and honeypot must bypass any threshold check unconditionally) and the asyncio event loop conflict that occurs if the digest sender calls `asyncio.run()` inside an `AsyncIOScheduler` job. All three risks have clear, low-effort preventions that must be addressed in the initial implementation rather than retrofitted.

---

## Key Findings

### Recommended Stack

The existing Python 3.11 / FastAPI / SQLite / httpx stack is fully sufficient. Zero new dependencies are required. The scheduling decision is the one area where research found a meaningful choice: STACK.md recommends a native `asyncio.create_task` + `while True` + `await asyncio.sleep()` loop over APScheduler, citing APScheduler 3.x multi-worker footgun and the alpha status of APScheduler 4.x. ARCHITECTURE.md disagrees and recommends APScheduler `AsyncIOScheduler` for its explicit cron trigger and cleaner lifecycle management.

**Resolved recommendation:** Use the native `asyncio.create_task` loop (STACK.md wins). The project is single-worker, the digest runs once per day at a fixed time, and the `_next_digest_time()` pure function keeps the scheduler logic to four lines. APScheduler is an unnecessary dependency for this use case.

**Core technologies:**
- `asyncio.create_task` + `asyncio.sleep`: digest scheduling — zero dependency, clean lifespan cancellation
- SQLite / SQLAlchemy 2.0: digest event persistence — already in use, survives container restarts
- `httpx` 0.26.0: Telegram delivery — already in use, sufficient for `sendMessage` rate
- `datetime` stdlib: digest time calculation — three-line pure function, no croniter needed
- `html.escape` stdlib: Telegram HTML sanitization — prevents attacker-injected HTML from breaking alerts

### Expected Features

**Must have (table stakes):**
- Severity-gated immediate alerts — stops the alert flood; operators expect this as a baseline
- Configurable severity threshold (`ALERT_MIN_SEVERITY` env var) — different risk tolerances require operator control
- Per-event cooldown / deduplication — existing 15-minute cooldown is table stakes; severity routing extends it
- Daily digest — most-requested feature in self-hosted security tooling; neither Fail2Ban nor CrowdSec free offer it natively
- Digest only when there is activity — empty "all quiet" digests train operators to ignore the digest channel
- Configurable digest schedule (`DIGEST_HOUR` env var) — 08:00 UTC is wrong for operators in non-UTC timezones

**Should have (differentiators):**
- Attack type breakdown in digest — "47 suspicious path scans, 3 SQL injections" transforms a count into signal
- Block count summary in digest — closes the loop: operator knows automated response worked
- Top-N attacker table in digest — attacker IP + country + count + action makes the digest actionable

**Defer (v2+):**
- Escalation for repeat offenders — requires careful threshold tuning to avoid re-introducing noise
- First-seen vs. known-bad distinction in digest — useful cross-reference query; adds complexity, not MVP
- Quiet hours / time-based suppression — research explicitly classifies this as an anti-feature; severity filtering is the correct substitute

### Architecture Approach

The architecture adds a single new decision point — `AlertRouter` — that intercepts the existing `send_alert_sync(event)` call in `log_watcher.py` and routes events to either immediate Telegram delivery or the `DigestCollector`. All other existing components (`TelegramAlerter`, `IntruderDetector`, `AutoBlocker`) are unchanged. The digest persistence uses a new `digest_events` table in the existing SQLite database. Scheduling is handled inside the FastAPI lifespan context manager. The one-line change to `log_watcher.py` is the only modification to existing hot-path code.

**Major components:**
1. `AlertRouter` (`app/alert_router.py`) — computes severity, compares against `ALERT_MIN_SEVERITY`, routes to immediate send or digest collection
2. `DigestCollector` (`app/digest_collector.py`) — accepts medium-severity events, persists each immediately to `digest_events` SQLite table
3. `DigestSender` (`app/digest_sender.py`) — queries unsent digest rows, builds truncation-safe Telegram HTML summary, sends, marks rows sent
4. `DigestScheduler` (inside `app/main.py` lifespan) — `asyncio.create_task` loop computing next wall-clock fire time, cancellable on shutdown
5. `digest_events` table (in `app/database.py`) — `id`, `timestamp`, `ip`, `reason`, `details`, `host`, `severity`, `sent` (0/1)

### Critical Pitfalls

1. **Digest state lost on container restart** — write each event to SQLite `digest_events` immediately on collection; never use an in-memory buffer as the primary store. This must be designed in from the start; retrofitting persistence requires a schema migration.

2. **Critical alerts swallowed by severity threshold** — `sql_injection` and `honeypot` event types must unconditionally bypass `ALERT_MIN_SEVERITY` regardless of request count escalation. Add an explicit test asserting this invariant. Log every suppressed alert to stdout.

3. **`asyncio.run()` called from inside FastAPI's event loop** — the digest sender must be `async def`; the scheduler must `await` it directly. Never call `asyncio.run()` from within an `AsyncIOScheduler` job or any async context. The existing `send_alert_sync()` wrapper is safe only because it runs from `log_watcher.py`'s thread context.

4. **Telegram 4096-character message limit** — digest message must use a fixed summary structure (counts + top-N IPs), measure `len(message)` before sending, truncate gracefully with "and N more events" fallback. Only clear the digest buffer after receiving HTTP 200 from Telegram.

5. **Unescaped attacker content breaks Telegram HTML parse mode** — apply `html.escape()` to all event-derived fields (details, path, host) before embedding in HTML-mode messages. This applies to both immediate alerts and digest. Fix this in the existing alerter as part of the milestone.

---

## Implications for Roadmap

Based on research, the build has a strict dependency chain. Phases should mirror the component build order identified in ARCHITECTURE.md.

### Phase 1: Foundation — Config and Schema
**Rationale:** Config env vars and the database schema are prerequisites for every other component. No code can be tested without them. The ARCHITECTURE.md build order explicitly lists these as steps 1 and 2.
**Delivers:** Three new env vars in `config.py`; `digest_events` table and ORM model in `database.py`; backwards-compatible defaults so existing deployments are unaffected.
**Addresses:** Configurable severity threshold, configurable digest schedule (foundation only)
**Avoids:** Pitfall 1 (state loss) — schema is designed for persistence from day one

### Phase 2: Alert Routing — Severity Gate
**Rationale:** The severity gate is the highest-impact change (stops the alert flood immediately) and is a prerequisite for digest collection. It touches the hot path (`log_watcher.py`) in exactly one line.
**Delivers:** `AlertRouter` module; one-line change to `log_watcher.py`; immediate alerts for critical/high only; medium events discarded (not yet collected)
**Uses:** Existing `THREAT_SEVERITY` dict, new `ALERT_MIN_SEVERITY` config, existing `TelegramAlerter`
**Implements:** AlertRouter component boundary
**Avoids:** Pitfall 2 (critical alerts swallowed) — sql_injection/honeypot bypass written and tested here

### Phase 3: Digest Collection — Persistence Layer
**Rationale:** With routing in place, medium events can now be captured. Building the collector before the sender allows independent testing of the persistence behavior.
**Delivers:** `DigestCollector` module; medium-severity events written to SQLite `digest_events` table on each detection
**Implements:** DigestCollector component; `digest_events` table usage
**Avoids:** Pitfall 1 (state loss) — SQLite write-on-collect, not write-on-send

### Phase 4: Digest Sender — Message Formatting and Delivery
**Rationale:** Once events are being collected, the sender can be built and tested against real accumulated data in the database.
**Delivers:** `DigestSender` module; aggregated Telegram message with attack type breakdown and block count summary; character-limit truncation; empty-digest guard; HTML escaping
**Uses:** `digest_events` table, `intruder_events` table, `blocked_ips` table, `TelegramAlerter`
**Avoids:** Pitfall 4 (asyncio.run conflict) — async def from the start; Pitfall 5 (4096-char limit); Pitfall 6 (HTML escape); Pitfall 9 (empty digest)

### Phase 5: Digest Scheduler — Scheduling and Wiring
**Rationale:** The scheduler is the final integration layer. Building it last means it can immediately invoke a fully tested sender.
**Delivers:** `asyncio.create_task` digest loop in FastAPI lifespan; `_next_digest_time()` pure function; clean shutdown via task cancellation; `DIGEST_HOUR`/`DIGEST_MINUTE` config integration
**Uses:** All previous phases; `asyncio`; `datetime` stdlib; `zoneinfo` for timezone support
**Avoids:** Pitfall 3 (duplicate schedulers) — single task in lifespan; Pitfall 7 (timezone mismatch) — explicit `DIGEST_TIMEZONE` env var with `ZoneInfo`

### Phase Ordering Rationale

- Config and schema must precede all code that uses them (hard dependency).
- Alert routing must precede digest collection — without routing, there is nothing to collect.
- Digest collection must precede digest sender — the sender queries the table the collector fills.
- Digest sender must precede the scheduler — the scheduler calls the sender; a broken sender is better caught before adding scheduling complexity.
- This order means each phase is independently testable via direct function calls before the next phase begins.
- The PITFALLS.md phase-specific warnings map directly onto this order: state loss addressed in Phase 3, asyncio conflict addressed in Phase 4, duplicate scheduler addressed in Phase 5.

### Research Flags

Phases with standard patterns (skip additional research-phase):
- **Phase 1 (Config/Schema):** Fully documented patterns; existing codebase is the reference
- **Phase 2 (Alert Routing):** Straightforward dict lookup + comparison; no novel patterns
- **Phase 3 (Digest Collection):** Standard SQLAlchemy insert pattern; existing database.py is the reference
- **Phase 4 (Digest Sender):** Telegram HTML formatting is well-documented; character limit is a known constraint
- **Phase 5 (Digest Scheduler):** asyncio task pattern is well-documented; stdlib only

No phases require a `/gsd-research-phase` deeper dive. All patterns are grounded in existing codebase analysis and verified official documentation.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations verified against PyPI, official docs, and direct codebase reading. No new dependencies required. |
| Features | HIGH | Grounded in industry alert fatigue research, competitor analysis (Fail2Ban, CrowdSec), and direct PROJECT.md constraint reading. |
| Architecture | HIGH | Component boundaries derived from existing codebase analysis. 8-step build order has no circular dependencies. |
| Pitfalls | HIGH | Most pitfalls sourced from official docs (Python, APScheduler, Telegram Bot API) and confirmed FastAPI issue tracker reports. |

**Overall confidence:** HIGH

### Gaps to Address

- **APScheduler vs. native asyncio choice:** STACK.md and ARCHITECTURE.md disagree. Resolution above (native asyncio) is based on STACK.md reasoning (no new dependency, simpler for single daily task). If implementation reveals the wall-clock scheduling logic is harder than expected, APScheduler `AsyncIOScheduler` is the validated fallback — no new research needed.

- **Cooldown persistence (Pitfall 8):** Research flags that the existing in-memory cooldown dict is lost on restart. The severity routing change (Phase 2) mitigates the worst consequence (medium events go to digest, not immediate alerts), but cooldown persistence for immediate alerts is not fully specified. Treat as a Phase 2 implementation decision: if the alerting refactor is clean, note this as a follow-up item.

- **Telegram rate limiting on critical burst (Pitfall 10):** Research recommends a single retry with `retry_after` respect. This is not in scope for the MVP phases but should be noted as a hardening item for a follow-up milestone. The severity filter significantly reduces burst risk.

---

## Sources

### Primary (HIGH confidence)
- FastAPI lifespan docs — asyncio.create_task scheduling pattern
- APScheduler 3.x official docs — AsyncIOScheduler lifecycle, persistent job stores
- Python 3.11 stdlib docs — asyncio, datetime, zoneinfo, html.escape
- SQLAlchemy 2.0 docs — ORM model patterns (existing codebase reference)
- Telegram Bot API docs — sendMessage, HTML parse mode, 4096-char limit
- httpx PyPI page — stable 0.28.1; 0.26.0 in use is compatible
- FastAPI issue #1124 — confirmed APScheduler duplicate scheduler bug

### Secondary (MEDIUM confidence)
- incident.io blog 2025 — alert fatigue suppression design principles; severity-tier routing model
- APScheduler vs asyncio loop comparison (leapcell.io) — validated recommendation for single-task scheduling
- CrowdSec vs Fail2Ban comparison (LetsHosting) — confirmed neither offers native daily digest in free tier
- magicbell.com notification system design — digest aggregation patterns
- nashruddinamin.com FastAPI + APScheduler pattern (Aug 2024) — AsyncIOScheduler lifespan integration

### Tertiary (LOW confidence)
- python-telegram-bot wiki — rate limit numbers (wiki, not official Telegram docs; treat as approximate)
- node-telegram-bot-api issue #165 — 4096-char limit confirmation (community source, behavior is reproducible)

---

*Research completed: 2026-04-11*
*Ready for roadmap: yes*
