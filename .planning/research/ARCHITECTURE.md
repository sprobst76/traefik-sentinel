# Architecture Patterns: Alert Aggregation and Digest Systems

**Domain:** Smart alerting layer for event-driven security monitoring pipeline
**Researched:** 2026-04-11
**Confidence:** HIGH — grounded in existing codebase analysis + verified patterns

---

## Current Architecture Baseline

Before describing the target architecture, the relevant existing components are:

### Where Alerts Are Born

`log_watcher.py: LogWatcher.process_line()` is the single choke point where every
security event flows. The current sequence is:

```
watchdog file event
  -> parse_log_line()
  -> check_and_block_honeypot()    [sync, in-process]
  -> AccessLog saved to SQLite
  -> intruder_detection.analyze_log()
  -> IntruderEvent saved to SQLite
  -> send_alert_sync(event)        [Telegram, EVERY event, sync]
  -> _schedule_auto_block(event)   [async task]
```

The problem: `send_alert_sync()` fires for every intruder event with only a 15-minute
per-(IP, reason) cooldown enforced inside `IntruderDetector.alerted`. There is no
severity gate; every medium/low event reaches Telegram immediately.

### Severity Already Exists

`telegram_alerter.py` already defines and computes severity — it just does nothing
useful with it:

```python
THREAT_SEVERITY = {
    "sql_injection": "critical",
    "honeypot": "critical",
    "auth_failures": "high",
    "rate_limit": "medium",
    "suspicious_path": "medium",
}
```

The severity label is used only to style the message header. It is not used as a
routing gate. This is the key leverage point.

### What the Milestone Needs to Add

1. A severity gate that routes events: critical/high -> immediate Telegram; medium -> digest.
2. A digest accumulator that holds medium events until digest time.
3. A scheduled digest sender (daily, configurable).
4. A digest state store (must survive the scheduler interval; in-process loss is acceptable).
5. An `ALERT_MIN_SEVERITY` env var to let operators tune the threshold.
6. A `DIGEST_SCHEDULE` env var (cron expression or hour) for schedule control.

---

## Target Architecture

### Component Map

```
                     ┌─────────────────────────────────┐
                     │        LogWatcher.process_line   │
                     │        (existing, unmodified)    │
                     └──────────────┬──────────────────┘
                                    │ event dict (ip, reason, ...)
                                    ▼
                     ┌─────────────────────────────────┐
                     │         AlertRouter              │  NEW
                     │  - compute_severity(event)       │
                     │  - immediate or digest?          │
                     └──────┬──────────────────┬────────┘
                            │ critical/high     │ medium
                            ▼                   ▼
              ┌─────────────────────┐  ┌────────────────────────┐
              │  TelegramAlerter    │  │   DigestCollector       │  NEW
              │  (existing,        │  │  - append event         │
              │   send immediately)│  │  - stored in SQLite     │
              └─────────────────────┘  └────────────┬───────────┘
                                                    │ on schedule
                                                    ▼
                                       ┌────────────────────────┐
                                       │   DigestSender         │  NEW
                                       │  - query digest rows   │
                                       │  - build summary msg   │
                                       │  - call TelegramAlerter│
                                       │  - mark rows sent      │
                                       └────────────────────────┘
                                                    ^
                                       ┌────────────┴───────────┐
                                       │   DigestScheduler      │  NEW
                                       │  APScheduler           │
                                       │  AsyncIOScheduler      │
                                       │  started in lifespan   │
                                       └────────────────────────┘
```

### Component Boundaries

| Component | File | Responsibility | Talks To |
|-----------|------|---------------|----------|
| `AlertRouter` | `app/alert_router.py` | Compute severity; decide immediate vs. digest | `DigestCollector`, `TelegramAlerter` |
| `DigestCollector` | `app/digest_collector.py` | Accept medium-severity events; persist to SQLite digest table | SQLite `digest_events` table |
| `DigestSender` | `app/digest_sender.py` | Query unsent digest events; build formatted summary; call Telegram; mark sent | `DigestCollector`, `TelegramAlerter` |
| `DigestScheduler` | `app/digest_scheduler.py` | Register cron job with APScheduler; start/stop in lifespan | `DigestSender`, FastAPI lifespan |
| `TelegramAlerter` | `app/telegram_alerter.py` | Send message via Telegram API (existing, unchanged interface) | Telegram API |
| `config.py` | `app/config.py` | Two new env vars: `ALERT_MIN_SEVERITY`, `DIGEST_CRON_HOUR` | All components |

`LogWatcher.process_line` is modified in exactly one line: replace `send_alert_sync(event)` with `alert_router.route(event)`. No other change to the pipeline.

---

## Data Flow

### Immediate Alert Path (critical / high)

```
event dict
  -> AlertRouter.route(event)
  -> compute_severity() returns "critical" or "high"
  -> severity >= ALERT_MIN_SEVERITY threshold
  -> send_alert_sync(event)        [existing code, unchanged]
```

No new I/O on this path. Latency impact: negligible (one dict lookup + comparison).

### Digest Path (medium / below threshold)

```
event dict
  -> AlertRouter.route(event)
  -> compute_severity() returns "medium"
  -> severity < ALERT_MIN_SEVERITY threshold
  -> DigestCollector.collect(event)
  -> INSERT INTO digest_events (ip, reason, details, host, severity, timestamp, sent=False)
```

### Digest Flush (scheduled)

```
DigestScheduler triggers DigestSender.send_digest()
  -> SELECT * FROM digest_events WHERE sent = False
  -> if count == 0: return  (no empty digests)
  -> group by reason, count by ip
  -> build Telegram HTML summary
  -> TelegramAlerter.send_alert(summary_message)
  -> UPDATE digest_events SET sent = True WHERE sent = False
```

---

## Severity Routing Logic

The `AlertRouter` consolidates the severity computation that is currently spread across
`telegram_alerter.py`. A single function determines the route:

```python
def compute_severity(event: dict) -> str:
    """Returns 'critical', 'high', or 'medium'."""
    base = THREAT_SEVERITY.get(event.get("reason", ""), "medium")
    count = event.get("request_count", 1)
    if count > 50:
        return "critical"
    if count > 20 and base == "medium":
        return "high"
    return base

SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1}

def route(event: dict):
    severity = compute_severity(event)
    threshold = SEVERITY_RANK.get(ALERT_MIN_SEVERITY, 2)  # default: "high"
    if SEVERITY_RANK[severity] >= threshold:
        send_alert_sync(event)
    else:
        digest_collector.collect(event)
```

This is the entirety of new routing logic. It uses values already computed in the
existing `THREAT_SEVERITY` dict — no new detection logic required.

---

## Digest State: SQLite vs In-Memory

**Decision: SQLite.**

Rationale:
- The app already uses SQLite for `IntruderEvent` and `BlockedIP` — adding a table is zero infrastructure cost.
- The scheduler interval is up to 24 hours. In-memory state is lost on any container restart or crash. On an internet-facing server, events accumulated over hours must not be lost.
- A `digest_events` table also lets operators query "what is pending" via SQL, which is useful for debugging.
- The digest table is read-mostly at send time; write load is low (one INSERT per medium-severity event, which is far less frequent than log parsing).
- Thread safety: the existing codebase already handles concurrent SQLite access via `SessionLocal()` sessions. The same pattern applies here.

**In-memory would be acceptable only if:** the digest window were very short (minutes), not hours.

### Digest Events Table Schema

```sql
CREATE TABLE digest_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    ip        TEXT NOT NULL,
    reason    TEXT NOT NULL,
    details   TEXT,
    host      TEXT,
    severity  TEXT NOT NULL DEFAULT 'medium',
    sent      INTEGER NOT NULL DEFAULT 0  -- 0=pending, 1=sent
);
```

No new ORM model file is needed — add to `app/database.py` alongside existing models.

---

## Scheduler: APScheduler AsyncIOScheduler

**Decision: APScheduler `AsyncIOScheduler`, started in FastAPI `lifespan`.**

Rationale:
- The app already runs async FastAPI. `AsyncIOScheduler` shares the existing event loop — no new thread or subprocess.
- `lifespan` start/stop gives clean lifecycle management without global state tricks.
- A cron trigger (`hour=DIGEST_CRON_HOUR`) allows the operator to pick the delivery time via env var.
- No new infrastructure — APScheduler is a single pip dependency, no broker, no Redis.
- The digest job is idempotent: if it runs twice (e.g., clock jitter), the second run finds no unsent rows and exits immediately.

**Integration point in `app/main.py` lifespan:**

```python
# Existing lifespan (simplified):
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watcher.start()
    digest_scheduler.start()   # ADD THIS LINE
    yield
    watcher.stop()
    digest_scheduler.stop()    # ADD THIS LINE
```

No other change to `main.py`.

---

## Configuration: New Env Vars

Two additions to `app/config.py`:

| Variable | Default | Effect |
|----------|---------|--------|
| `ALERT_MIN_SEVERITY` | `high` | Minimum severity for immediate Telegram alert. Events below this go to digest. Valid: `critical`, `high`, `medium` |
| `DIGEST_CRON_HOUR` | `7` | UTC hour to send daily digest (0-23). Digest fires once per day at this hour. |

These follow the existing env var pattern and are backwards-compatible: existing deployments with no new vars set will behave as if `ALERT_MIN_SEVERITY=high` (sql_injection and honeypot fire immediately; rate_limit and suspicious_path go to digest).

---

## Build Order (Phase Dependencies)

The components have a strict dependency chain. They must be built in this order:

```
1. config.py additions
        |
        v
2. database.py: digest_events table + DigestEvent ORM model
        |
        v
3. alert_router.py: AlertRouter (compute_severity + route)
   [depends on: config, telegram_alerter (existing)]
        |
        v
4. digest_collector.py: DigestCollector (collect + query pending)
   [depends on: database digest_events table]
        |
        v
5. digest_sender.py: DigestSender (build summary + send + mark sent)
   [depends on: digest_collector, telegram_alerter]
        |
        v
6. digest_scheduler.py: DigestScheduler (APScheduler wrapper + lifespan hooks)
   [depends on: digest_sender, APScheduler install]
        |
        v
7. log_watcher.py: one-line change (send_alert_sync -> alert_router.route)
   [depends on: alert_router]
        |
        v
8. main.py: add scheduler start/stop to lifespan
   [depends on: digest_scheduler]
```

Steps 1-2 are pure data model work. Steps 3-4 can be tested independently without a
running scheduler. Step 5-6 are the integration layer. Step 7-8 are the final wiring.

This order means each step is testable before proceeding to the next.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Modifying telegram_alerter.py for Routing Logic
**What goes wrong:** Adding severity checks inside `send_telegram_alert()` mixes transport with routing logic.
**Why bad:** Makes the alerter aware of policies it should not own; harder to test independently.
**Instead:** `AlertRouter` owns routing policy. `TelegramAlerter` owns only message formatting and HTTP delivery.

### Anti-Pattern 2: In-Memory Digest Buffer
**What goes wrong:** Storing pending digest events in a Python list or dict on `DigestCollector`.
**Why bad:** Docker container restarts (common during updates) silently drop hours of accumulated events. Digest fires empty or misses real events.
**Instead:** Write to `digest_events` SQLite table on every `collect()` call.

### Anti-Pattern 3: BackgroundScheduler (threaded) in Async App
**What goes wrong:** Using APScheduler's `BackgroundScheduler` (thread-based) instead of `AsyncIOScheduler` in a FastAPI app.
**Why bad:** Thread-based scheduler creates a separate thread that shares the SQLite connection pool unpredictably; `asyncio.run()` conflicts inside scheduled jobs.
**Instead:** Use `AsyncIOScheduler` — it runs in the existing event loop, async jobs work naturally.

### Anti-Pattern 4: Sending Digest From LogWatcher Thread
**What goes wrong:** Triggering digest flush when an event comes in (e.g., "if now is past 07:00 and digest not sent today").
**Why bad:** Digest send becomes coupled to event arrival rate — on a quiet night the digest never fires.
**Instead:** Digest is always time-driven by the scheduler, not event-driven.

### Anti-Pattern 5: Empty Digest Messages
**What goes wrong:** Scheduler fires at 07:00 even when there were zero medium-severity events.
**Why bad:** Operator sees "no events" notification as noise — defeats the purpose.
**Instead:** `DigestSender.send_digest()` checks `COUNT(*) WHERE sent=False` first; returns without sending if zero.

---

## Scalability Considerations

This is a single-server, single-container deployment. Scalability concerns are scoped accordingly:

| Concern | At current load (1 server) | Notes |
|---------|---------------------------|-------|
| SQLite write contention | None — low event rate | Acceptable |
| Scheduler duplication | N/A — single container | If ever multi-instance, use distributed lock |
| Digest message size | Telegram limit: 4096 chars | Truncate top-N IPs if > limit |
| Event backlog | Rare — unsent rows accumulate only if Telegram API is down | Auto-recovered on next scheduler run |

The Telegram 4096-character limit on messages is the one real constraint to design for. The `DigestSender` must cap output: "top 10 IPs by event count, with a summary of remaining N IPs omitted."

---

## Sources

- APScheduler `AsyncIOScheduler` + FastAPI lifespan pattern: [nashruddinamin.com (Aug 2024)](https://www.nashruddinamin.com/blog/running-scheduled-jobs-in-fastapi), [APScheduler 3.x docs](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- Severity-based immediate vs. digest routing (three-tier model): [incident.io blog 2025](https://incident.io/blog/alert-fatigue-solutions-for-dev-ops-teams-in-2025-what-works), [Panther Python detection rules](https://docs.panther.com/detections/rules/python)
- SQLite as digest event store: [sqlite.org/whentouse.html](https://sqlite.org/whentouse.html), [sqliteforum.com real-time analytics](https://www.sqliteforum.com/p/real-time-analytics-with-sqlite-streaming-and-aggregated-data-insights)
- Alert aggregation patterns: [magicbell.com notification system design](https://www.magicbell.com/blog/notification-system-design), [suprsend.com design patterns](https://www.suprsend.com/post/top-6-design-patterns-for-building-effective-notification-systems-for-developers)

---

*Architecture analysis: 2026-04-11*
