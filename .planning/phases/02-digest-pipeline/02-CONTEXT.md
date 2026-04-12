# Phase 2: Digest Pipeline - Context

**Gathered:** 2026-04-12
**Mode:** interactive (--chain); user accepted all 5 recommended defaults with "ok"
**Status:** Ready for planning

<domain>
## Phase Boundary

Given the `digest_events` rows Phase 1 writes (reference-based: `source` + `source_id` → join back to `intruder_events` or `blocked_ips`), Phase 2 produces a **manually triggerable** digest sender that assembles a single, well-formatted Telegram message covering: blocked-IP count, attack-type breakdown, top attacker IPs with country flags, and a traffic overview. HTML-escaped, within Telegram's 4096-char limit, skipped silently when nothing to report.

Covers requirements: CONTENT-01, CONTENT-02, CONTENT-03, CONTENT-04, CONTENT-05, CONTENT-06, SCHED-03.

**Out of scope:** automatic scheduling (Phase 3), asyncio lifespan wiring (Phase 3), DIGEST_HOUR/DIGEST_ENABLED/DIGEST_TIMEZONE env vars (Phase 3).

</domain>

<decisions>
## Implementation Decisions

### Message Layout (D-12)

- **D-12:** Section order: header → blocked IPs count → attack-type breakdown → top 10 attacker IPs (with country flag + event count) → traffic overview → footer. Framing is "since last digest" (not "last 24h"). Emoji style matches existing `telegram_alerter.py`:
  - 🛡️ header ("Daily Digest — <date>")
  - 🚫 blocked IPs
  - 🎯 attack breakdown (one line per reason with count)
  - 🌐 top attackers (flag + IP + count)
  - 📊 traffic overview
  - HTML parse mode (`parse_mode: "HTML"`), same as existing alerts

### Digest Window (D-13)

- **D-13:** The digest covers rows where `digest_events.sent_at IS NULL` — gapless, no overlap, no gaps. Each event appears in exactly one digest. Manual re-trigger within the same day produces a second digest only if new events occurred in between; otherwise it's skipped (SCHED-03). Choice of `sent_at IS NULL` window (over a rolling 24h) simplifies logic, avoids double-reporting, and doesn't depend on clock math.

### Content Sources (D-14)

- **D-14:** Aggregation queries (per DIGEST-02 "no duplicate storage") — the digest sender JOINs `digest_events` against:
  - `intruder_events` (when `source="intruder"`): for reason breakdown, attacker IPs, paths
  - `blocked_ips` (when `source="auto_block"`): for blocked IP count, country
  - `access_logs`: for traffic overview (total requests, unique IPs, error rate, top hosts) — windowed by the oldest/newest `digest_events.timestamp` in the current batch
- GeoIP country flags come via existing `app/geoip.py` (batch API, 24h cache).
- Top-N attacker IPs: top 10 by event count, ties broken by most recent timestamp.
- Traffic overview window = `[min(timestamp), max(timestamp)]` of the unsent `digest_events` batch. If no rows, no window → no digest.

### Truncation Policy (D-15)

- **D-15:** When the assembled message exceeds 4096 chars, trim in this order until it fits:
  1. Attacker-IP list: reduce from 10 → 5 → 3, then append `+N more` summary line
  2. Path samples (if included inline in attack breakdown): drop
  3. Attack-type breakdown: keep (never dropped — it's the core signal)
  4. Core counts (blocked IPs, traffic overview): never trimmed
- Truncation uses iterative rebuild, not naive string cut: measure → rebuild with fewer items → re-measure. Max 3 trim passes before accepting whatever fits.

### HTML Escaping (D-16)

- **D-16:** All attacker-controlled fields are escaped via `html.escape()` before insertion into the Telegram message template: `ip`, `path`, `user_agent`, `host`, `country` (country name only — flag emoji is pre-sanitized by geoip). Use `quote=False` since values don't appear inside HTML attributes. Static header/footer text is not escaped (known-safe literals). Per CONTENT-06.

### Manual Trigger (D-17)

- **D-17:** Single new REST endpoint `POST /api/digest/send` in `app/main.py`. No auth (matches existing dashboard pattern; operator firewalls the port). Returns JSON: `{"sent": true/false, "event_count": N, "skipped_reason": "no_events"|null, "telegram_ok": bool}`. Phase 3's scheduler will call the same code path (not the HTTP endpoint) via a direct function import.

### Bookkeeping (D-18)

- **D-18:** `sent_at` update is a **batch UPDATE** executed only after Telegram returns HTTP 200. Sequence:
  1. Query unsent rows (`WHERE sent_at IS NULL`)
  2. If empty → return `skipped_reason: "no_events"`, no Telegram call (SCHED-03)
  3. Build message, hydrate from source tables
  4. POST to Telegram
  5. On 200 OK: `UPDATE digest_events SET sent_at = <now> WHERE id IN (<collected ids>)` inside a single transaction
  6. On non-200 or exception: rows stay unsent; next trigger retries. Log the failure (print) but don't raise.
- No partial / mid-send state. Idempotency: if the Telegram send succeeds but the UPDATE fails (rare), the next trigger will resend — acceptable tradeoff vs. complex two-phase commit.

### New Module Layout (D-19)

- **D-19:** Introduce `app/digest.py` that exposes:
  - `async def send_digest() -> dict` — main entry point; returns the JSON shape above
  - `build_message(db, rows) -> tuple[str, list[int]]` — pure function: assembles HTML, returns (message, row_ids_included)
  - Private helpers for each section (blocked-IP count, attack breakdown, top attackers, traffic overview) — each takes `db` and the windowed rows, returns a formatted string fragment
  - `_truncate_if_needed(...)` — the iterative rebuild loop
- `app/main.py` imports `send_digest` for the `/api/digest/send` route. Phase 3's scheduler will import the same `send_digest` function.

### Config Surface (Phase 2)

- **D-20:** No new env vars in this phase. Digest trigger is manual only. `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` reused from `app/config.py` via `telegram_alerter.send_alert()`.

### Claude's Discretion

- Exact HTML template string (spacing, line breaks, emoji positions within recommended sections) — keep consistent with `telegram_alerter.send_telegram_alert` aesthetics.
- Names of private helper functions.
- Whether to memoize intermediate aggregations within a single send (small data, probably not worth it).
- SQL query style: SQLAlchemy ORM (consistent with codebase) preferred over raw SQL.
- Whether to return the assembled message text in the `/api/digest/send` response for debugging (recommended yes — aids UAT).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project-Level
- `.planning/PROJECT.md` — vision, constraints (no stack changes, backwards compat)
- `.planning/REQUIREMENTS.md` — CONTENT-01…06, SCHED-03 verbatim
- `.planning/ROADMAP.md` §"Phase 2" — goal + 4 success criteria
- `CLAUDE.md` — conventions (snake_case, PEP 8, print logging, no custom exceptions)

### Phase 1 Artifacts (foundation — must stay honored)
- `.planning/phases/01-foundation-and-alert-routing/01-CONTEXT.md` — decisions D-01..D-11
- `.planning/phases/01-foundation-and-alert-routing/01-SUMMARY.md` (per plan) — what was actually built
- `app/database.py:72-80` — `DigestEvent` schema Phase 2 reads
- `app/alert_router.py` — Phase 2 does NOT modify this; it only reads `digest_events`

### Codebase Intel
- `.planning/codebase/ARCHITECTURE.md` — layer boundaries, API endpoint style
- `.planning/codebase/CONVENTIONS.md` — naming, type hints, module patterns
- `.planning/codebase/STACK.md` — FastAPI 0.109, SQLAlchemy 2.0, httpx 0.26, Jinja2 (not used here)

### Files to read
- `app/main.py` — FastAPI routing patterns (e.g., `/api/blocklist` POST for request/response shape reference)
- `app/telegram_alerter.py` — existing HTML message format for style consistency; `send_alert(message, parse_mode)` is the reusable sender
- `app/geoip.py` — country flag lookup signature (`lookup_batch`)
- `app/database.py` — models (`AccessLog`, `IntruderEvent`, `BlockedIP`, `DigestEvent`) and session factory

### Files to create
- `app/digest.py` — new module (aggregation + message assembly + trigger)

### Files to modify
- `app/main.py` — add `POST /api/digest/send` endpoint

No external ADRs/specs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/telegram_alerter.send_alert(message, parse_mode="Markdown")` — generic sender. Call with `parse_mode="HTML"` to match our escaping strategy.
- `app/geoip.lookup_batch(ips: list[str]) -> dict[str, dict]` — returns `{ip: {country, flag, ...}}` with 24h cache and rate limiting.
- `app/database.SessionLocal()` + `DigestEvent`, `IntruderEvent`, `BlockedIP`, `AccessLog` ORM models.
- FastAPI route registration pattern in `app/main.py` — `@app.post("/api/...")` returning dicts.

### Established Patterns
- Async HTTP via `httpx.AsyncClient` (already used by telegram_alerter).
- Session per-request (open/close), no global session.
- Print-based logging.
- API endpoints return plain dicts (auto-serialized by FastAPI).

### Integration Points
- `/api/digest/send` registers in `app/main.py` alongside existing `/api/stats`, `/api/intruders`, `/api/blocklist`.
- Phase 3 will wire `asyncio.create_task(send_digest())` in FastAPI lifespan — `send_digest` must be safe to call from an already-running event loop (already designed as `async def`).

### Patterns to avoid
- Do NOT introduce a second Telegram client — reuse `send_alert`.
- Do NOT store denormalized event data in `digest_events` (DIGEST-02 forbids it — query source tables instead).
- Do NOT add `DIGEST_HOUR` / `DIGEST_ENABLED` — Phase 3 territory.

</code_context>

<specifics>
## Specific Ideas

- HTML header line: `<b>🛡️ Traefik Sentinel Digest</b>\n<i>Since: {since_utc} · Until: {until_utc}</i>` where the window is `[min, max]` of included rows.
- Attack-type breakdown as small table-ish lines: `💉 SQL injection: <b>{n}</b>` — one line per reason that has events. Drop lines with zero count.
- Top attackers: `{flag} <code>{ip}</code> — {country_name} ({count} events)` — monospace IPs matching existing alert style.
- Traffic overview: `📊 Traffic: {total_requests} requests · {unique_ips} unique IPs · {error_rate_pct}% error rate\n🎪 Top hosts: {host1} ({n1}), {host2} ({n2}), {host3} ({n3})`.
- Footer: `<i>{event_count} events in this digest</i>`.
- If `digest_events` has any `sent_at IS NULL` rows but the join hydration loses them (e.g. source row deleted), log a warning and include them as a "⚠ {N} orphaned events" line rather than silently dropping — defensive.

</specifics>

<deferred>
## Deferred Ideas

- Scheduler (`DIGEST_HOUR`, asyncio lifespan, timezone-aware) — Phase 3.
- `DIGEST_ENABLED=false` kill switch — Phase 3 (SCHED-02).
- Rate limiting of the digest endpoint — not needed for internal use.
- Historical / re-send / "digest for yesterday" view — not in requirements.
- Quiet hours, per-reason overrides, multi-channel — v2 (ADV-01..05).
- Authentication on `/api/digest/send` — dashboard is unauthenticated per existing design; operator firewalls the port.
- Message preview / dry-run endpoint — nice-to-have; planner may add if cheap (Claude's Discretion).

</deferred>

---

*Phase: 02-digest-pipeline*
*Context gathered: 2026-04-12 (--chain, interactive; user accepted recommended defaults)*
