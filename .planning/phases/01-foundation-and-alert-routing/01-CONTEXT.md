# Phase 1: Foundation and Alert Routing - Context

**Gathered:** 2026-04-12
**Mode:** --auto (Claude selected recommended defaults)
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver the plumbing that lets Phase 2/3 exist: (1) a severity-based routing gate so only critical/high intruder events reach Telegram immediately, (2) a `digest_events` SQLite table that durably records medium-severity and auto-block notifications for later aggregation, (3) a new `ALERT_MIN_SEVERITY` env var with backwards-compatible defaults. Nothing in this phase sends a digest message — that is Phase 2.

Covers requirements: ALERT-01, ALERT-02, ALERT-03, ALERT-04, ALERT-05, DIGEST-01, DIGEST-02, DIGEST-03.

</domain>

<decisions>
## Implementation Decisions

### Routing Architecture

- **D-01:** Introduce a new module `app/alert_router.py` that owns (a) the `THREAT_SEVERITY` map, (b) a `get_severity(reason, event) -> str` function that preserves the existing request-count escalation rule from `telegram_alerter.get_severity_header`, and (c) a `route_event(event) -> Literal["immediate", "digest"]` function. `telegram_alerter.py` becomes a dumb sender — it imports severity from `alert_router` but does not decide routing.
  - _Why:_ Keeps the routing gate in one place, testable in isolation, and lets both `log_watcher` and `auto_blocker` ask the same question. Avoids sprinkling `if severity >= X` checks across call sites.
- **D-02:** The routing gate is applied at existing call sites (not inside `send_telegram_alert`):
  - `app/log_watcher.py:134` — replace unconditional `send_alert_sync(event)` with `if route_event(event) == "immediate": send_alert_sync(event) else: persist_to_digest(event, source="intruder", source_id=intruder.id)`.
  - `app/auto_blocker.py:150` and `app/auto_blocker.py:258` — auto-block notifications currently call `send_alert(message)` unconditionally. Replace with a `persist_to_digest(..., source="auto_block", source_id=blocked_ip.id)` call. Per ALERT-04 these never fire immediately.
  - _Why:_ Call-site gating is explicit and greppable; a gate inside the sender would silently drop messages and be harder to debug.

### Severity Model

- **D-03:** Severity ordering is a fixed integer rank: `{"critical": 3, "high": 2, "medium": 1}`. `route_event` returns `"immediate"` when `rank(severity) >= rank(ALERT_MIN_SEVERITY)`, else `"digest"`. Unknown severities fall back to `"medium"`.
- **D-04:** `ALERT_MIN_SEVERITY` defaults to `"high"`. With the default, critical + high events go immediate, medium goes to digest — matches the roadmap success criteria and keeps existing deployments (ALERT-05) receiving the alerts they already expect minus the noise.
- **D-05:** Honeypot vs. auto-block reconciliation (resolves apparent ALERT-02/ALERT-04 tension):
  - The **intruder detection event** with `reason="honeypot"` is severity `critical` and ALWAYS routes immediate (ALERT-02). This is the event produced by `log_watcher` when a request hits a honeypot path.
  - The **auto-block notification** produced afterward by `auto_blocker.py` (the "IP X was auto-blocked" message) ALWAYS routes to the digest regardless of severity (ALERT-04). Implemented by having `persist_to_digest` accept a `force_digest=True` flag used from `auto_blocker` call sites, OR by having `auto_blocker` call `persist_to_digest` directly and never consult the router. **Choice: the latter — `auto_blocker` skips the router entirely and calls `persist_to_digest` directly**, since its routing is unconditional. Simpler, less clever.
- **D-06:** Preserve the existing request-count escalation from `telegram_alerter.get_severity_header` (request_count > 50 → critical, > 20 + medium → high). Move this logic into `alert_router.get_severity` so routing sees the escalated severity, not the raw `THREAT_SEVERITY` lookup.

### Schema

- **D-07:** New SQLAlchemy model `DigestEvent` in `app/database.py`. **Reference-based, not denormalized** (honors DIGEST-02 "events already stored in intruder_events and blocked_ips are queried directly — no duplicate storage"):
  ```python
  class DigestEvent(Base):
      __tablename__ = "digest_events"
      id = Column(Integer, primary_key=True, autoincrement=True)
      timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
      source = Column(String(20), nullable=False)      # "intruder" | "auto_block"
      source_id = Column(Integer, nullable=False)      # FK-by-convention to intruder_events.id or blocked_ips.id
      severity = Column(String(10), nullable=False)    # "critical" | "high" | "medium"
      sent_at = Column(DateTime, nullable=True, index=True)  # NULL = still pending; set when included in a digest
  ```
  - Phase 2 aggregation queries will JOIN `digest_events` with `intruder_events` / `blocked_ips` to hydrate details. No cross-table FK constraints (SQLite + two source tables); `(source, source_id)` is a logical key.
  - Index `sent_at` so "find unsent events" is O(n_unsent).
  - _Why reference-based:_ DIGEST-02 explicitly forbids duplicate storage. Also keeps the digest table tiny and lets digest queries always see the latest detail state.
- **D-08:** Migration strategy: `DigestEvent` is created by `Base.metadata.create_all(engine)` in the existing `init_db()` — no ALTER needed since it's a brand-new table. No data backfill required (digest is forward-looking).

### Config Surface (Phase 1 only)

- **D-09:** Add to `app/config.py`:
  ```python
  ALERT_MIN_SEVERITY = os.getenv("ALERT_MIN_SEVERITY", "high").lower()
  ```
  Validate at load time: if not in `{"critical", "high", "medium"}`, fall back to `"high"` and print a warning. **Do not** add `DIGEST_HOUR` / `DIGEST_ENABLED` / `DIGEST_TIMEZONE` here — those belong to Phase 3.
- **D-10:** Backwards compatibility (ALERT-05): with only `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` set, the default `ALERT_MIN_SEVERITY=high` means the operator still gets critical + high events immediately. No existing env var is renamed or removed.

### Persistence API

- **D-11:** `alert_router.persist_to_digest(db: Session, *, source: str, source_id: int, severity: str)` is the single write path for digest events. Called synchronously from `log_watcher.process_line` (already holds a `db` session) and `auto_blocker` (opens its own session like other writes there). Commits inline — no batching in Phase 1.

### Claude's Discretion

- Exact function signatures, module private helpers, import organization, type hint style.
- Whether to expose a `severity_rank()` helper or inline the dict lookup.
- Whether to log the routing decision (probably `print(f"Routed {reason} -> digest")` at debug verbosity, matching the codebase's print-based logging convention).
- Test structure (the repo has no formal test suite per `.planning/codebase/TESTING.md`; planner decides whether Phase 1 seeds one or uses ad-hoc scripts).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-Level
- `.planning/PROJECT.md` — project vision, constraints (no stack changes, backwards compat required)
- `.planning/REQUIREMENTS.md` — ALERT-01…05, DIGEST-01…03 in full
- `.planning/ROADMAP.md` §"Phase 1" — goal + 5 success criteria
- `CLAUDE.md` — conventions (snake_case, PEP 8, print-based logging, no custom exception classes)

### Codebase Intel
- `.planning/codebase/ARCHITECTURE.md` — layer boundaries, where routing logic belongs
- `.planning/codebase/CONVENTIONS.md` — naming, type hint, module design patterns
- `.planning/codebase/STACK.md` — SQLAlchemy 2.0.25, aiosqlite, FastAPI 0.109.0

### Files that will be modified
- `app/config.py` — add `ALERT_MIN_SEVERITY`
- `app/database.py` — add `DigestEvent` model
- `app/telegram_alerter.py` — remove `THREAT_SEVERITY` ownership; import from router
- `app/log_watcher.py:134` — gate `send_alert_sync` behind router
- `app/auto_blocker.py:150, 258` — replace `send_alert(message)` with `persist_to_digest(...)`

### Files that will be created
- `app/alert_router.py` — new module (severity map + routing + persistence)

No external ADRs/specs — requirements fully captured in `.planning/REQUIREMENTS.md` + decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `THREAT_SEVERITY` dict and `get_severity_header` escalation logic in `app/telegram_alerter.py:8-33` — move, don't rewrite.
- `_migrate_blocked_ips_table()` pattern in `app/database.py:78-101` — template if any future ALTER is needed (not needed this phase).
- `SessionLocal` + `get_db()` in `app/database.py:11,104` — standard session factory for sync writes.
- `send_alert_sync(event)` wrapper in `app/telegram_alerter.py:113` — keep as-is; still used for the immediate path.

### Established Patterns
- All config flows through `app/config.py` via `os.getenv` with typed defaults (`int(...)`, `.lower() == "true"`). New `ALERT_MIN_SEVERITY` follows suit.
- SQLAlchemy models declared in `app/database.py` alongside `Base`; `init_db()` creates all tables at lifespan start.
- Call sites that need Telegram currently import `send_alert` / `send_alert_sync` inline (`from app.telegram_alerter import ...` inside functions) — e.g. `app/auto_blocker.py:137,219,250`. Continue this pattern; the new `persist_to_digest` import can be module-level since it has no heavy side effects.
- Print-based logging for errors and migrations (no `logging` module configured).
- No custom exceptions — functions return success flags or `None` on failure.

### Integration Points
- `log_watcher.LogFileHandler.process_line` (`app/log_watcher.py:76-153`) — the hot path that must branch on routing.
- `auto_blocker.py` emits two kinds of Telegram messages (lines 150, 258) — both redirect to digest per ALERT-04.
- FastAPI lifespan in `app/main.py:28-34` already calls `init_db()` — new table picked up automatically once the model is declared.

</code_context>

<specifics>
## Specific Ideas

- Call the new module `alert_router.py` (not `severity.py` or `notifier.py`) — it's explicitly about routing.
- Use `typing.Literal["immediate", "digest"]` for the routing return type; `typing.Literal["critical", "high", "medium"]` for severity.
- Keep `persist_to_digest` synchronous — every caller is already inside a sync SQLAlchemy session or a sync wrapper.
- Do NOT introduce `asyncio.Queue` or batching here; Phase 3 adds the scheduler.

</specifics>

<deferred>
## Deferred Ideas

- `DIGEST_HOUR`, `DIGEST_ENABLED`, `DIGEST_TIMEZONE` env vars — Phase 3.
- Digest message formatting, HTML escaping, 4096-char truncation — Phase 2 (CONTENT-01…06).
- Aggregation queries across `intruder_events` + `blocked_ips` + `access_logs` — Phase 2.
- Quiet hours, per-reason severity overrides, multi-channel delivery — v2 (ADV-01…05).
- Formal test suite — discretionary; TESTING.md notes none exists.

</deferred>

---

*Phase: 01-foundation-and-alert-routing*
*Context gathered: 2026-04-12 (--auto)*
