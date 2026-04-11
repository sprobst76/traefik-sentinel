# Technology Stack

**Project:** Traefik Sentinel — Smart Notification Milestone
**Researched:** 2026-04-11
**Scope:** Alert aggregation, severity filtering, and daily digest scheduling on top of the existing Python/FastAPI/SQLite stack

---

## Context: What Already Exists

The existing codebase constrains choices significantly (by design):

| Component | Current State |
|-----------|--------------|
| Runtime | Python 3.11 |
| Web framework | FastAPI 0.109.0 with asyncio lifespan |
| HTTP client | httpx 0.26.0 (already used for Telegram calls) |
| Database | SQLite via SQLAlchemy 2.0.25 |
| Telegram | Raw `httpx` POST to Bot API — no PTB dependency |
| Cooldown tracking | In-memory `dict[tuple, datetime]` in `IntruderDetector` |
| Severity mapping | Hardcoded dict in `telegram_alerter.py` (`THREAT_SEVERITY`) |

The PROJECT.md constraint is unambiguous: "No new services or databases required." Every library choice must slot into this existing foundation.

---

## Recommended Stack

### Scheduling: Native asyncio loop, not APScheduler

**Recommendation:** `asyncio.create_task` + `while True` + `await asyncio.sleep()` inside the existing FastAPI `lifespan` context manager.

**Rationale:**

The digest job is a single, simple periodic task: collect stats from SQLite, format a message, POST to Telegram, sleep until next run. This is exactly the use case where APScheduler's overhead is unjustified.

APScheduler 3.x (3.11.2, latest stable as of December 2025) adds a dependency, requires scheduler lifecycle management, and has a known footgun with multi-worker deployments (Gunicorn spawns N workers = N scheduler instances firing the same job N times). The project deploys as a single Docker container with uvicorn in single-worker mode, so the footgun is unlikely to trigger — but the dependency still adds nothing that the native pattern cannot do.

APScheduler 4.x (4.0.0a6, latest as of April 2025) is alpha-only and has a completely redesigned API with breaking changes versus 3.x. Do not use.

The native asyncio pattern is:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    watcher.start()
    digest_task = asyncio.create_task(digest_loop())
    yield
    digest_task.cancel()
    try:
        await digest_task
    except asyncio.CancelledError:
        pass
    watcher.stop()

async def digest_loop():
    """Runs digest at the configured schedule, cancellable on shutdown."""
    while True:
        now = datetime.utcnow()
        next_run = _next_digest_time(now)
        sleep_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(sleep_seconds)
        await send_daily_digest()
```

`_next_digest_time()` is a pure function computing the next wall-clock fire time from a configurable hour/minute env var. No APScheduler needed.

**Confidence:** HIGH — verified against APScheduler PyPI, FastAPI lifespan docs, and multiple production pattern sources.

---

### Digest Time Calculation: Standard library only

**Recommendation:** `datetime` + `timedelta` from the Python standard library.

**Rationale:** Computing "next occurrence of HH:MM UTC" is three lines of arithmetic. There is no need for `croniter`, `pendulum`, or any third-party date library. The project already uses `datetime` throughout.

```python
def _next_digest_time(now: datetime, hour: int, minute: int) -> datetime:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target
```

**Confidence:** HIGH — standard library, no external verification needed.

---

### Alert Aggregation (Digest Buffer): SQLite query, not an in-memory buffer

**Recommendation:** Query the existing `intruder_events` and `blocked_ips` tables at digest send time. Do not maintain a separate in-memory buffer.

**Rationale:**

Two approaches exist for collecting digest data:

| Approach | Pros | Cons |
|----------|------|------|
| In-memory buffer (e.g., `collections.deque`) | Fast, no DB overhead | Lost on restart; duplicates existing DB data; adds complexity |
| Query SQLite at send time | Already-persisted data; survives restarts; zero duplication | One DB query at send time |

The project's SQLite database already stores everything needed for a digest:
- `intruder_events` has `timestamp`, `ip`, `reason`, `request_count`
- `blocked_ips` has `blocked_at`, `auto_blocked`, `active`
- `access_logs` has total request counts

Querying with `WHERE timestamp >= :since` (where `since` = last 24 hours) produces an accurate digest with no buffer maintenance. The "no empty digests" requirement is a simple `if event_count == 0: return` guard.

An in-memory buffer would duplicate the database, lose state on container restart, and require thread-safe access patterns that the DB already handles. The PROJECT.md constraint ("no new services or databases") reinforces the query approach.

**Confidence:** HIGH — based on analysis of existing schema in `database.py` and project constraints.

---

### Severity Filtering: Extend existing `THREAT_SEVERITY` dict

**Recommendation:** Add a configurable `ALERT_MIN_SEVERITY` environment variable. Keep the existing severity dict in `telegram_alerter.py`. Add a filter check before calling `send_telegram_alert`.

**Rationale:**

The existing `THREAT_SEVERITY` dict in `telegram_alerter.py` already maps reason strings to severity levels. The current code sends every event regardless of severity. Adding a threshold check requires:

1. One new env var: `ALERT_MIN_SEVERITY` (values: `medium`, `high`, `critical`, default: `high`)
2. A severity rank helper: `{"medium": 0, "high": 1, "critical": 2}`
3. A guard at the call site: `if severity_rank(event) >= severity_rank(min_threshold): await send_telegram_alert(event)`

No new library. No schema change. The existing `alerted` cooldown dict in `IntruderDetector` already prevents duplicate alerts within 15 minutes — this mechanism is preserved and works alongside the severity filter.

**Confidence:** HIGH — directly derived from reading `intruder_detection.py` and `telegram_alerter.py`.

---

### Telegram HTTP Client: Keep httpx (no python-telegram-bot)

**Recommendation:** Continue using raw `httpx` POST to the Telegram Bot API. Do not add `python-telegram-bot`.

**Rationale:**

`python-telegram-bot` is a full-featured bot framework with its own async event loop, update polling, and 20+ MB of transitive dependencies. The project only needs to POST `sendMessage` — a single HTTP call. Adding PTB to do that is significant overengineering.

The Telegram Bot API rate limit is 30 messages/second and 20 messages/minute for groups. A security dashboard sending at most a few immediate alerts per hour and one daily digest is nowhere near this limit. The PTB `AIORateLimiter` is unnecessary.

The existing `httpx` client pattern in `telegram_alerter.py` handles the rate-limit scenario adequately with a `timeout=10.0` and exception catch. If a 429 is returned, the alert is lost — acceptable given the project is a personal self-hosted tool, not a SLA-critical notification system.

httpx current latest stable: **0.28.1** (December 2024). The project currently pins 0.26.0. Upgrading to 0.28.1 is safe (no breaking changes in 0.27/0.28) but not required for this milestone.

**Confidence:** HIGH — verified against python-telegram-bot docs (v22.0) and httpx PyPI page.

---

### Configuration: Environment variables via existing `config.py`

**Recommendation:** Add three new env vars to the existing `config.py` pattern. No new library (python-dotenv is already present).

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `ALERT_MIN_SEVERITY` | str | `high` | Minimum severity for immediate Telegram alert |
| `DIGEST_HOUR` | int | `8` | UTC hour to send daily digest |
| `DIGEST_MINUTE` | int | `0` | UTC minute to send daily digest |

```python
# In config.py — additions only
ALERT_MIN_SEVERITY = os.getenv("ALERT_MIN_SEVERITY", "high")
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "8"))
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE", "0"))
```

The `DIGEST_HOUR`/`DIGEST_MINUTE` split (rather than a cron string) avoids any dependency on `croniter` for parsing and keeps the interface simple. The typical use case is "send at 8am" — two integers cover this.

**Confidence:** HIGH — consistent with existing config.py pattern verified by reading the file directly.

---

## Alternatives Considered and Rejected

| Category | Recommended | Alternative | Why Rejected |
|----------|-------------|-------------|--------------|
| Scheduling | `asyncio.create_task` loop | APScheduler 3.x | Unnecessary dependency; multi-worker footgun; adds complexity for a single task |
| Scheduling | `asyncio.create_task` loop | APScheduler 4.x | Alpha-only; breaking API changes; unstable |
| Scheduling | `asyncio.create_task` loop | `fastapi-utils` `@repeat_every` | Interval-based only (no wall-clock scheduling); adds a dependency |
| Scheduling | `asyncio.create_task` loop | Celery + Beat | Requires Redis or RabbitMQ; violates "no new services" constraint |
| Digest buffer | SQLite query at send time | `collections.deque` in memory | Lost on restart; duplicates existing DB; adds buffer management complexity |
| Digest buffer | SQLite query at send time | `persist-queue` / DiskCache | Introduces new dependency and new on-disk state alongside existing SQLite DB |
| Telegram client | httpx (existing) | `python-telegram-bot` | Full bot framework; 20+ MB deps; way more than needed for `sendMessage` |
| Date parsing | `datetime` stdlib | `pendulum` / `arrow` | Only computing "next HH:MM"; stdlib is sufficient |
| Date parsing | `datetime` stdlib | `croniter` | Cron string parsing is overkill for a fixed daily time |

---

## No New Dependencies Required

This milestone adds **zero new Python dependencies**. Everything needed is either:

- Already in `requirements.txt` (`httpx`, `sqlalchemy`, `fastapi`)
- In the Python 3.11 standard library (`asyncio`, `datetime`, `collections`)

The existing `requirements.txt` does not need to change for this milestone.

---

## Installation

No new packages to install. Existing dependencies are sufficient:

```bash
# Nothing to add — existing requirements.txt covers all needs
# Optional: upgrade httpx to current stable if desired
# httpx==0.28.1  (currently pinned at 0.26.0, both work)
```

---

## Sources

- APScheduler PyPI (stable 3.11.2, alpha 4.0.0a6): https://pypi.org/project/APScheduler/
- APScheduler 3.x docs (AsyncIOScheduler): https://apscheduler.readthedocs.io/en/3.x/userguide.html
- FastAPI lifespan docs + asyncio.create_task pattern: https://fastapi.tiangolo.com/tutorial/background-tasks/
- APScheduler multi-worker footgun (FastAPI issue #1124): https://github.com/fastapi/fastapi/issues/1124
- python-telegram-bot AIORateLimiter (v22.0): https://docs.python-telegram-bot.org/en/v22.0/telegram.ext.aioratelimiter.html
- httpx PyPI (stable 0.28.1): https://pypi.org/project/httpx/
- APScheduler vs asyncio loop comparison: https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-versus-schedule
- FastAPI background task production patterns: https://betterstack.com/community/guides/scaling-python/background-tasks-in-fastapi/
