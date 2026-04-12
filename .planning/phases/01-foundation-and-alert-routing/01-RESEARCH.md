# Phase 1: Foundation and Alert Routing - Research

**Researched:** 2026-04-12
**Domain:** Severity-based alert routing + SQLite digest persistence (SQLAlchemy 2.0 on SQLite, watchdog-driven sync hot path)
**Confidence:** HIGH

## Summary

Phase 1 is a refactor, not new-tech research. The existing `THREAT_SEVERITY` map and escalation logic already live in `app/telegram_alerter.py` and work — the phase extracts them into a new `app/alert_router.py`, adds a `DigestEvent` SQLAlchemy model, and gates two call sites in `log_watcher.py` / `auto_blocker.py`. No new dependencies are needed; everything is achievable with the existing Python 3.11 + SQLAlchemy 2.0.25 + SQLite stack.

The meaningful risks are all integration-level, not technology-level: (1) the circular-import potential between `alert_router`, `telegram_alerter`, and `log_watcher`; (2) honoring ALERT-05 backwards compatibility — the default `ALERT_MIN_SEVERITY="high"` must preserve the set of alerts existing deployments receive today minus the now-digested medium ones; (3) SQLite write concurrency between the watchdog thread (log_watcher) and async tasks (auto_blocker) — an issue the codebase already has, but digest writes add a third writer; (4) the codebase has no test suite, so "verification" defaults to ad-hoc scripts unless Phase 1 seeds one.

**Primary recommendation:** Implement `alert_router.py` as a pure-Python leaf module (imports only from `app.config` and `app.database`). Both `telegram_alerter.py` and the two call sites import from it — never the reverse. Do not seed a formal test suite in Phase 1; use a small `scripts/verify_phase1.py` harness that the plan can run to prove the 5 roadmap success criteria. Defer pytest adoption to a later hardening phase.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Routing Architecture:**
- **D-01:** Introduce `app/alert_router.py` owning (a) `THREAT_SEVERITY` map, (b) `get_severity(reason, event) -> str` (preserves existing escalation rule from `telegram_alerter.get_severity_header`), (c) `route_event(event) -> Literal["immediate", "digest"]`. `telegram_alerter.py` becomes a dumb sender that imports severity from `alert_router` but does not decide routing.
- **D-02:** Routing gate applied at existing call sites (NOT inside `send_telegram_alert`):
  - `app/log_watcher.py:134` — replace unconditional `send_alert_sync(event)` with `if route_event(event) == "immediate": send_alert_sync(event) else: persist_to_digest(event, source="intruder", source_id=intruder.id)`.
  - `app/auto_blocker.py:150` and `app/auto_blocker.py:258` — auto-block notifications currently `send_alert(message)` unconditionally. Replace with `persist_to_digest(..., source="auto_block", source_id=blocked_ip.id)`. Per ALERT-04 these never fire immediately.

**Severity Model:**
- **D-03:** Severity rank `{"critical": 3, "high": 2, "medium": 1}`. `route_event` returns `"immediate"` when `rank(severity) >= rank(ALERT_MIN_SEVERITY)`, else `"digest"`. Unknown severities fall back to `"medium"`.
- **D-04:** `ALERT_MIN_SEVERITY` defaults to `"high"`.
- **D-05:** Honeypot intruder event (severity `critical`) ALWAYS routes immediate per ALERT-02. Auto-block notification ALWAYS routes to digest per ALERT-04 — `auto_blocker` skips the router entirely and calls `persist_to_digest` directly.
- **D-06:** Preserve the request-count escalation from `telegram_alerter.get_severity_header` (request_count > 50 → critical, > 20 + medium → high). Move this logic into `alert_router.get_severity` so routing sees the escalated severity.

**Schema:**
- **D-07:** New SQLAlchemy model `DigestEvent` in `app/database.py`, reference-based per DIGEST-02:
  ```python
  class DigestEvent(Base):
      __tablename__ = "digest_events"
      id = Column(Integer, primary_key=True, autoincrement=True)
      timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
      source = Column(String(20), nullable=False)      # "intruder" | "auto_block"
      source_id = Column(Integer, nullable=False)      # logical FK to intruder_events.id or blocked_ips.id
      severity = Column(String(10), nullable=False)    # "critical" | "high" | "medium"
      sent_at = Column(DateTime, nullable=True, index=True)  # NULL = pending
  ```
- **D-08:** `Base.metadata.create_all(engine)` in `init_db()` picks up the new table — no ALTER, no backfill.

**Config Surface:**
- **D-09:** Add `ALERT_MIN_SEVERITY = os.getenv("ALERT_MIN_SEVERITY", "high").lower()` to `app/config.py`. Validate: if not in `{"critical", "high", "medium"}`, fall back to `"high"` and print a warning. **Do not** add `DIGEST_HOUR` / `DIGEST_ENABLED` / `DIGEST_TIMEZONE` — Phase 3.
- **D-10:** Backwards compatibility (ALERT-05): no existing env var renamed or removed.

**Persistence API:**
- **D-11:** `alert_router.persist_to_digest(db: Session, *, source: str, source_id: int, severity: str)`. Called synchronously from `log_watcher.process_line` (already holds `db`) and from `auto_blocker` (opens its own session). Commits inline. No batching.

### Claude's Discretion

- Exact function signatures, module private helpers, import organization, type hint style.
- Whether to expose a `severity_rank()` helper or inline the dict lookup.
- Whether to log the routing decision (probably `print(f"Routed {reason} -> digest")` at debug verbosity).
- Test structure — the repo has no formal test suite; planner decides whether Phase 1 seeds one or uses ad-hoc scripts.

### Deferred Ideas (OUT OF SCOPE)

- `DIGEST_HOUR`, `DIGEST_ENABLED`, `DIGEST_TIMEZONE` env vars — Phase 3.
- Digest message formatting, HTML escaping, 4096-char truncation — Phase 2.
- Aggregation queries across `intruder_events` + `blocked_ips` + `access_logs` — Phase 2.
- Quiet hours, per-reason severity overrides, multi-channel delivery — v2.
- Formal test suite — discretionary.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ALERT-01 | Route intruder events by severity; critical/high immediate, medium to digest | `route_event` in new `alert_router.py` gates `log_watcher.py:134`. Rank map `{critical:3, high:2, medium:1}`, compare against `ALERT_MIN_SEVERITY`. |
| ALERT-02 | Critical (SQL injection, honeypot) ALWAYS immediate | Both already map to `critical` in existing `THREAT_SEVERITY` (telegram_alerter.py:8-14); with default `ALERT_MIN_SEVERITY=high`, rank(3) ≥ rank(2) → immediate. No special casing needed if map is preserved. |
| ALERT-03 | `ALERT_MIN_SEVERITY` env var, default `high` | New line in `app/config.py` following the `os.getenv(..., "default").lower()` pattern already used for `HONEYPOT_INSTANT_BLOCK` (config.py:127). |
| ALERT-04 | Auto-block notifications → digest | `auto_blocker.notify_auto_block` (line 150) and `auto_blocker._send_honeypot_alert` (line 258) replaced with `persist_to_digest(..., source="auto_block", source_id=blocked_ip.id)`. Router skipped entirely. |
| ALERT-05 | Existing `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` continue to work | Default `ALERT_MIN_SEVERITY=high` means critical + high events still fire immediately. No existing config var is renamed. `send_alert_sync` signature unchanged. |
| DIGEST-01 | Digest events persisted immediately on detection | `persist_to_digest` commits inline inside `log_watcher.process_line` (already holds a session) and from `auto_blocker` (opens its own). Write-through, no in-memory buffer. |
| DIGEST-02 | Reference-based: no duplicate event data | `DigestEvent` stores only `(source, source_id)` — details hydrated later by JOIN against `intruder_events` / `blocked_ips`. Phase 2 aggregation queries will do the JOIN. |
| DIGEST-03 | Digest state survives restart | SQLite durability guarantees this; `sent_at=NULL` marks pending. No in-memory state. |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **No stack changes** — Python 3.11 + FastAPI + SQLite + HTMX. `requirements.txt` must not grow in Phase 1.
- **Backwards compatibility** — Existing Telegram config (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) continues to work.
- **No external dependencies** — no new services or databases.
- **English-only** in code and messages. One existing German string (`"⚡ Sofort blockiert!"` at `auto_blocker.py:225, 256`) is in scope only incidentally; Phase 2 owns message formatting, so leave it alone here.
- **Conventions** (from `.planning/codebase/CONVENTIONS.md`): snake_case modules/functions, `ALL_CAPS` constants, PascalCase classes/models, print-based logging (no `logging` module), no custom exceptions, type hints consistent with existing style (`Optional[...]`, `dict[str, ...]`, `Literal[...]`).
- **GSD workflow** — use `/gsd-execute-phase` for implementation; do not edit outside a GSD command.

## Standard Stack

Phase 1 uses only what's already in `requirements.txt`. No additions. `[VERIFIED: requirements.txt reviewed via .planning/codebase/STACK.md]`

### Core (already present, no changes)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.25 | ORM; `Base.metadata.create_all` picks up new model | Already owns all existing tables; `DigestEvent` declared next to siblings. |
| Python stdlib `typing` | 3.11 | `Literal["immediate", "digest"]`, `Literal["critical", "high", "medium"]` | Matches existing type-hint style (CONVENTIONS.md §Type Hints). |
| Python stdlib `os` | 3.11 | `os.getenv("ALERT_MIN_SEVERITY", "high").lower()` | Matches every other config entry in `app/config.py`. |

### Supporting
None. No new libraries, no test framework install in Phase 1 (see Validation note below).

### Alternatives Considered
| Instead of | Could Use | Why Rejected |
|------------|-----------|--------------|
| New `alert_router.py` module | Put routing in `telegram_alerter.py` | CONTEXT D-01 locks the module split; also `auto_blocker.py` needs `persist_to_digest` without pulling in the Telegram sender. |
| Reference-based `DigestEvent` | Denormalize event fields | DIGEST-02 explicitly forbids duplicate storage. Also keeps the table tiny. |
| Raise on invalid `ALERT_MIN_SEVERITY` | Warn + fallback to `"high"` | Matches codebase tolerance patterns — no config var currently raises (e.g., `int(os.getenv(...))` would raise but that's incidental). See "Config Validation Pattern" below. |

## Architecture Patterns

### Module Placement
```
app/
├── config.py              # +ALERT_MIN_SEVERITY (+validation)
├── database.py            # +DigestEvent model
├── alert_router.py        # NEW — severity + routing + persist_to_digest
├── telegram_alerter.py    # -THREAT_SEVERITY, -get_severity_header (move to router), imports from router
├── log_watcher.py         # process_line line 134: gate via route_event
└── auto_blocker.py        # lines 150, 258: replace send_alert(...) with persist_to_digest(...)
```

### Import Dependency Graph (must remain acyclic)

```
config.py  ← (leaf; no app imports)
database.py  ← config.py
alert_router.py  ← config.py, database.py  (leaf w.r.t. alerting)
telegram_alerter.py  ← config.py, alert_router.py  (imports THREAT_SEVERITY, get_severity)
auto_blocker.py  ← database.py, blocklist.py, abuseipdb.py, config.py, alert_router.py (for persist_to_digest)
log_watcher.py  ← config.py, log_parser.py, database.py, intruder_detection.py, telegram_alerter.py, alert_router.py
```

**Rule:** `alert_router.py` MUST NOT import from `telegram_alerter.py`, `log_watcher.py`, or `auto_blocker.py`. It is a pure leaf module in the alerting subgraph.

### Call-Site Mechanics (current → target)

**Site 1: `app/log_watcher.py:134`** — inside `LogFileHandler.process_line`, after the `IntruderEvent` is committed to DB (line 131 flushes `intruder.id`).

```python
# Current (line 133-134):
# Send Telegram alert (without Ollama - on-demand now)
send_alert_sync(event)

# Target:
from app.alert_router import route_event, persist_to_digest
if route_event(event) == "immediate":
    send_alert_sync(event)
else:
    persist_to_digest(db, source="intruder", source_id=intruder.id, severity=get_severity(event["reason"], event))
```

Notes:
- `intruder` is the ORM instance committed on line 131; `intruder.id` is populated by autoincrement after `db.commit()`.
- `db` session is already open and reused for the digest write — single transaction scope is fine (the earlier commit flushed the intruder row).
- Import can be top-level (no side effects, no circular issue since alert_router is a leaf).

**Site 2: `app/auto_blocker.py:150`** — inside async `notify_auto_block(ip, abuse_score, reason, event_count)`.

Current: awaits `send_alert(message)` with a formatted Markdown string.
Target: open a session, look up the `BlockedIP` row just created (passed in or queried by IP+active), call `persist_to_digest(db, source="auto_block", source_id=blocked_ip.id, severity="high")`. The severity label for auto-block notifications is a discretion call — `"high"` matches the visual weight of the current notification and is above the default `ALERT_MIN_SEVERITY` threshold, but since auto_blocker skips the router entirely (D-05), severity here is a label-only field used by Phase 2 aggregation. Recommend `"high"` for consistency.

**Caller refactor:** `process_intruder_event` (line 126) already has the block `result` dict in scope but not the ORM row. Cleanest fix: change the `notify_auto_block` signature to accept `source_id: int` and have `process_intruder_event` pass `result.get("id")` — `blocklist.block_ip` already returns `{"success": True, "id": blocked.id, ...}` per CONVENTIONS.md pattern 5. `[VERIFIED: app/auto_blocker.py:122-126 + TESTING.md §blocklist.py return shape]`

**Site 3: `app/auto_blocker.py:258`** — inside `_send_honeypot_alert`. Same treatment as site 2. The `check_and_block_honeypot` caller has the block `result` (line 216) and can pass `result.get("id")` to a refactored honeypot notification path. In practice, the current code at lines 228-236 is already a best-effort fire-and-forget (see the bare `except: pass`), so replacing it with a synchronous `persist_to_digest` call inside the `if result.get("success")` block is simpler and more reliable.

### Config Validation Pattern

Match `app/config.py` style: no exceptions, permissive fallbacks. Recommend:

```python
_ALERT_MIN_SEVERITY_RAW = os.getenv("ALERT_MIN_SEVERITY", "high").lower()
if _ALERT_MIN_SEVERITY_RAW not in {"critical", "high", "medium"}:
    print(f"Config warning: ALERT_MIN_SEVERITY={_ALERT_MIN_SEVERITY_RAW!r} invalid, falling back to 'high'")
    ALERT_MIN_SEVERITY = "high"
else:
    ALERT_MIN_SEVERITY = _ALERT_MIN_SEVERITY_RAW
```

Rationale: `app/config.py` currently uses print-only warnings nowhere (it has no validation at all for other vars), but the existing migration helper in `database.py:99` uses `print(f"Migration: ...")`. Print-warn-and-default is the lowest-friction pattern consistent with the codebase. Do not raise. `[ASSUMED: user preference for permissive fallback; matches "no custom exceptions" convention]`

### `init_db()` Idempotency

`database.py:72-75`:
```python
def init_db():
    Base.metadata.create_all(engine)
    _migrate_blocked_ips_table()
```

`Base.metadata.create_all(engine)` is idempotent — it issues `CREATE TABLE IF NOT EXISTS` for each mapped class. Adding `DigestEvent` to the same `Base` means existing deployments auto-create the new table on first restart after deploy. No ALTER needed. No call to `_migrate_blocked_ips_table` equivalent needed for digest_events because the table is brand-new. `[CITED: SQLAlchemy 2.0 docs — Base.metadata.create_all uses IF NOT EXISTS by default]`

### Anti-Patterns to Avoid

- **Gate inside `send_telegram_alert`:** Would silently drop messages, harder to debug. CONTEXT D-02 mandates call-site gating.
- **Importing `send_alert_sync` at module top of `alert_router.py`:** Breaks the leaf-module rule and creates circular-import risk. The router never sends; it only decides.
- **Leaving `THREAT_SEVERITY` duplicated in `telegram_alerter.py`:** Creates drift. Move the dict; have telegram_alerter import it from alert_router.
- **Denormalizing event fields into `DigestEvent`:** Violates DIGEST-02.
- **Holding the `db` session across the `send_alert_sync` call:** `send_alert_sync` is synchronous but uses `asyncio.run`/`httpx` — it can block 10+ seconds on network failure. In `log_watcher.process_line` the session is already open for the whole `try:` block (lines 96-153), so this is a pre-existing issue; do not make it worse by adding digest writes after a long network call. Order the call-site code so the digest write happens instead of, not after, the Telegram send.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Severity comparison | Ad-hoc string ordering | Integer rank dict `{"critical": 3, "high": 2, "medium": 1}` and compare | Explicit, testable, matches CONTEXT D-03. |
| Digest table migration | Manual `ALTER TABLE` in an extended `_migrate_*` helper | `Base.metadata.create_all(engine)` | New table, not a schema change. Helper only exists for ALTERs. |
| Severity "escalation" rule | New logic | Copy lines 23-26 of `telegram_alerter.py` into `alert_router.get_severity` verbatim | D-06: preserve behavior. |
| Pending-digest index lookup | Full table scan filter | Rely on the `index=True` on `sent_at` | Already in CONTEXT D-07. |

## Runtime State Inventory

Not a rename/refactor/migration phase in the classic sense (new code + refactor, no data rename). Skipped.

## Common Pitfalls

### Pitfall 1: Circular import between `alert_router` and `telegram_alerter`
**What goes wrong:** `telegram_alerter.py` imports `THREAT_SEVERITY` from `alert_router`; if `alert_router` ever imports `send_alert_sync` (for convenience), Python will deadlock on import.
**Why it happens:** Natural temptation to centralize sending too.
**How to avoid:** `alert_router.py` imports only from `app.config` and `app.database`. Period.
**Warning sign:** `ImportError: cannot import name ... (most likely due to a circular import)` at startup.

### Pitfall 2: `DigestEvent.source_id` orphaned when parent row is deleted
**What goes wrong:** `RETENTION_INTRUDER_EVENTS_DAYS=90` (config.py:131) deletes old intruder rows; digest_events with matching source_id become dangling.
**Why it happens:** No FK constraint (DIGEST-02 keeps the reference logical, not enforced).
**How to avoid:** Not a Phase 1 problem — Phase 2 aggregation queries are the ones that would break on a JOIN with no match. Document it. A retention sweep on `digest_events` where `sent_at IS NOT NULL AND sent_at < NOW() - 7d` (Phase 3) is the right answer.
**Warning sign:** Phase 2 digest messages show "Unknown intruder" rows.

### Pitfall 3: SQLite writer contention
**What goes wrong:** `log_watcher.process_line` runs on the watchdog thread; `auto_blocker.process_intruder_event` runs as an asyncio task on the main loop; both open a `SessionLocal()` and write. Adding `persist_to_digest` from both adds a third write path into the same SQLite file. SQLite allows one writer at a time — a concurrent write raises `sqlite3.OperationalError: database is locked` after a default 5s timeout.
**Why it happens:** Pre-existing concurrency pattern — this phase doesn't create the issue but can exacerbate it under burst load.
**How to avoid:** (1) Inside `log_watcher.process_line`, reuse the already-open `db` session for the digest write — don't open a second. (2) In `auto_blocker`, the existing pattern already opens its own session; persist inline inside the same try/finally block at lines 89-131. (3) Keep digest writes unbatched (CONTEXT D-11) — small fast transactions are less likely to contend than long ones.
**Warning sign:** `OperationalError: database is locked` during burst traffic (visible in `docker logs`).

### Pitfall 4: `send_alert_sync` event-loop hack + new async `persist_to_digest` call site
**What goes wrong:** `send_alert_sync` at `telegram_alerter.py:113-120` has a `try: asyncio.run(...) except RuntimeError: loop.run_until_complete(...)` fallback. If `persist_to_digest` were accidentally made async, `log_watcher.process_line` (sync thread) would need the same hack and likely deadlock.
**Why it happens:** Easy to mistake "persist" for something that should be async.
**How to avoid:** CONTEXT D-11 locks `persist_to_digest` as synchronous. Keep it that way. SQLAlchemy `Session` used here is the sync variant (see `database.py:11` `sessionmaker(bind=engine)` — no `AsyncSession`).

### Pitfall 5: `ALERT-05` backwards-compatibility regression
**What goes wrong:** Existing deployments set only `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`. Today they receive Telegram messages for every intruder event including `suspicious_path` and `rate_limit` (both `medium`). After Phase 1 with default `ALERT_MIN_SEVERITY=high`, those mediums go silent-to-digest — **and there is no digest sender in Phase 1**. The user perceives this as "alerts stopped working."
**Why it happens:** Phase 1 ships only half the pipeline.
**How to avoid:** Accept it — the roadmap knows Phase 2 ships the sender. But the plan must include a release-note / README update so operators understand medium events are now queued. Also: success criterion #4 in the roadmap says "continues to receive **critical** alerts without configuration change" — the requirement is explicitly scoped to critical, not all alerts. No regression per the contract, just per user intuition.
**Warning sign:** Operator reports "I stopped getting alerts" after Phase 1 deploy.

## Code Examples

### Example: `alert_router.py` skeleton (matches CONTEXT decisions + existing conventions)
```python
"""Alert routing: severity computation + immediate/digest gate + digest persistence."""
from datetime import datetime
from typing import Literal
from sqlalchemy.orm import Session
from app.config import ALERT_MIN_SEVERITY
from app.database import DigestEvent


# Severity classification (moved from telegram_alerter.py)
THREAT_SEVERITY: dict[str, str] = {
    "sql_injection": "critical",
    "honeypot": "critical",
    "auth_failures": "high",
    "rate_limit": "medium",
    "suspicious_path": "medium",
}

_SEVERITY_RANK: dict[str, int] = {"critical": 3, "high": 2, "medium": 1}


def get_severity(reason: str, event: dict) -> Literal["critical", "high", "medium"]:
    """Return severity for an intruder event, honoring request-count escalation.

    Preserves the rule previously implemented in telegram_alerter.get_severity_header:
    - request_count > 50 -> escalate to critical
    - request_count > 20 and current severity == medium -> escalate to high
    """
    severity = THREAT_SEVERITY.get(reason, "medium")
    request_count = event.get("request_count", 1) or 1

    if request_count > 50:
        severity = "critical"
    elif request_count > 20 and severity == "medium":
        severity = "high"

    return severity  # type: ignore[return-value]


def route_event(event: dict) -> Literal["immediate", "digest"]:
    """Decide whether an intruder event fires immediately or waits for digest."""
    severity = get_severity(event.get("reason", ""), event)
    threshold_rank = _SEVERITY_RANK.get(ALERT_MIN_SEVERITY, _SEVERITY_RANK["high"])
    event_rank = _SEVERITY_RANK.get(severity, _SEVERITY_RANK["medium"])
    return "immediate" if event_rank >= threshold_rank else "digest"


def persist_to_digest(
    db: Session,
    *,
    source: str,
    source_id: int,
    severity: str,
) -> None:
    """Persist a digest-eligible event reference. Commits inline."""
    entry = DigestEvent(
        timestamp=datetime.utcnow(),
        source=source,
        source_id=source_id,
        severity=severity,
        sent_at=None,
    )
    db.add(entry)
    db.commit()
```

### Example: `database.py` addition (append to existing file)
```python
class DigestEvent(Base):
    __tablename__ = "digest_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source = Column(String(20), nullable=False)       # "intruder" | "auto_block"
    source_id = Column(Integer, nullable=False)       # logical FK to intruder_events.id or blocked_ips.id
    severity = Column(String(10), nullable=False)     # "critical" | "high" | "medium"
    sent_at = Column(DateTime, nullable=True, index=True)  # NULL = pending
```

### Example: `telegram_alerter.py` refactor (remove ownership, import)
```python
# At top, replacing lines 7-14 and 17-33:
from app.alert_router import THREAT_SEVERITY, get_severity

# get_severity_header stays as a message-formatting helper but calls get_severity:
def get_severity_header(reason: str, event: dict) -> str:
    severity = get_severity(reason, event)
    headers = {
        "critical": "🔴🔴🔴 CRITICAL THREAT DETECTED 🔴🔴🔴",
        "high": "🟠🟠 HIGH SEVERITY ALERT 🟠🟠",
        "medium": "🟡 Security Alert",
    }
    return headers.get(severity, headers["medium"])
```

### Example: `log_watcher.py:120-140` gated call site
```python
# Inside the for event in events loop, after db.add(intruder) / db.commit():
from app.alert_router import route_event, persist_to_digest, get_severity  # top-of-file import

if route_event(event) == "immediate":
    send_alert_sync(event)
else:
    persist_to_digest(
        db,
        source="intruder",
        source_id=intruder.id,
        severity=get_severity(event["reason"], event),
    )

# Auto-block scheduling (unchanged):
try:
    self._schedule_auto_block(event)
except Exception as e:
    print(f"Auto-block scheduling failed: {e}")
```

## State of the Art

No external ecosystem shifts apply — this is all internal refactor on a stable stack (FastAPI 0.109, SQLAlchemy 2.0.25, Python 3.11). `[VERIFIED: .planning/codebase/STACK.md]`

**One minor deprecation note for Phase 3 (not Phase 1):** `datetime.utcnow()` is soft-deprecated in Python 3.12+; the codebase uses it extensively (database.py:46, 63; log_watcher.py:122; auto_blocker.py:41, 106, 157; telegram_alerter.py:51). SCHED-05 explicitly mandates `zoneinfo` + timezone-aware `datetime` for scheduling in Phase 3. For Phase 1, stay consistent with the surrounding code — use `datetime.utcnow()` in `DigestEvent.default` and in the `timestamp=datetime.utcnow()` arg inside `persist_to_digest`. A codebase-wide migration is a separate hardening task. `[CITED: Python docs — datetime.utcnow() deprecated in 3.12 in favor of datetime.now(timezone.utc)]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Auto-block digest entries should be labeled `severity="high"` | Call-Site Mechanics §Site 2 | Low — severity is a label consumed by Phase 2 aggregation; can be changed with a single-line migration or a Phase 2 re-classification. User could prefer `"medium"` or a new `"info"` band. |
| A2 | Permissive warn-and-fallback for invalid `ALERT_MIN_SEVERITY` matches user preference | Architecture §Config Validation Pattern | Low — alternative is raise-on-invalid; trivial to flip. Codebase has no precedent either way. |
| A3 | `blocklist.block_ip` returns `{"id": blocked.id, ...}` on success | Call-Site Mechanics §Site 2 | Medium — I inferred from CONVENTIONS.md §Error Handling Pattern 5 and auto_blocker's use of `result.get("success")`. If `id` isn't in the return dict, auto_blocker must query `BlockedIP` by IP+active=1 after the block. Verify at plan time by reading `app/blocklist.py:119-228`. |
| A4 | Skipping a formal test suite is acceptable for Phase 1 | Validation section (below) | Low — CONTEXT explicitly lists test infra as discretionary. If user wants pytest added, it's a clean one-task addition. |

## Open Questions

1. **What `severity` label should auto-block digest entries carry?**
   - What we know: D-05 says auto_blocker bypasses the router; it still writes a `severity` column value.
   - What's unclear: Whether `"high"` (matches today's notification visual weight), `"medium"` (since it's deferred), or a new `"info"` band is right. Phase 2 will use this for aggregation grouping.
   - Recommendation: `"high"` — least semantic drift from current behavior. Revisit in Phase 2 if aggregation wants a different axis.

2. **Should Phase 1 seed a pytest suite, or use an ad-hoc verification script?**
   - What we know: TESTING.md notes zero existing tests. CONTEXT marks this as discretionary. `workflow.nyquist_validation` is `false` in config.json.
   - What's unclear: User appetite for test infrastructure debt.
   - Recommendation: Ship a single `scripts/verify_phase1.py` script that exercises (a) `route_event` with a canned critical/medium event, (b) config-invalid fallback, (c) `init_db()` on a throwaway SQLite file creates `digest_events`, (d) `persist_to_digest` writes and commits. No pytest, no new dependency. Defer formal test adoption.

3. **Auto-block `source_id`: pass through return value or re-query?**
   - What we know: `block_ip` returns a success dict; auto_blocker currently discards it by line 116 except for `result.get("success")`.
   - What's unclear: Whether `id` is in the return dict (see A3 above).
   - Recommendation: Confirm at plan time with a single `Read` of `app/blocklist.py`. If `id` isn't returned, add it there (2-line change) rather than re-querying.

## Environment Availability

No external dependencies introduced. Existing env: Python 3.11, SQLite file at `data/dashboard.db`. Skipped.

## Sources

### Primary (HIGH confidence)
- `/home/aiplatform/development/traefik-sentinel/.planning/phases/01-foundation-and-alert-routing/01-CONTEXT.md` — locked decisions D-01 through D-11.
- `/home/aiplatform/development/traefik-sentinel/.planning/REQUIREMENTS.md` — ALERT-01…05, DIGEST-01…03 verbatim.
- `/home/aiplatform/development/traefik-sentinel/.planning/codebase/{ARCHITECTURE,CONVENTIONS,STACK,TESTING}.md` — codebase intel.
- `/home/aiplatform/development/traefik-sentinel/app/{config,database,telegram_alerter,log_watcher,auto_blocker}.py` — read directly, line numbers cited inline.
- `CLAUDE.md` — project conventions and constraints.

### Secondary (MEDIUM confidence)
- SQLAlchemy 2.0 behavior of `Base.metadata.create_all` (`IF NOT EXISTS` semantics) — standard knowledge, matches observed `init_db()` behavior.

### Tertiary (LOW confidence)
- Python 3.12 `datetime.utcnow()` deprecation note — advisory for Phase 3 only; out of scope here.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; everything verified in requirements.txt via STACK.md.
- Architecture: HIGH — call sites read directly from source; import graph verified acyclic.
- Pitfalls: HIGH — circular import, SQLite concurrency, and ALERT-05 UX regression all grounded in existing code patterns.
- Assumptions: see Assumptions Log above (4 items, all low-to-medium risk).

**Research date:** 2026-04-12
**Valid until:** 2026-05-12 (30 days — stable stack, no fast-moving dependencies)
