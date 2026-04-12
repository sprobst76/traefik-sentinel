---
phase: 01-foundation-and-alert-routing
verified: 2026-04-12T00:00:00Z
status: human_needed
score: 12/12 must-haves verified
overrides_applied: 0
---

# Phase 01: Foundation and Alert Routing — Verification Report

**Phase Goal:** Immediate Telegram alerts fire only for critical and high severity events; existing deployments continue to work unchanged.
**Verified:** 2026-04-12
**Status:** human_needed (automated verification all green; live Telegram send path requires human confirmation)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (merged from ROADMAP SC + PLAN frontmatter must_haves)

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | SQL injection or honeypot event always sends immediate Telegram message (SC#1, ALERT-02) | VERIFIED | `THREAT_SEVERITY['sql_injection']='critical'`, `THREAT_SEVERITY['honeypot']='critical'` in `app/alert_router.py:14-20`; criticals pass `route_event` gate under any valid `ALERT_MIN_SEVERITY` (critical=3 >= any threshold rank). `log_watcher.py:136` calls `send_alert_sync(event)` on immediate branch. |
| 2  | Medium-severity event produces no immediate Telegram message (SC#2, ALERT-01) | VERIFIED | `log_watcher.py:136-144` is strict `if/else`; medium events go to `persist_to_digest` only. `rate_limit` and `suspicious_path` map to `medium`; under default `ALERT_MIN_SEVERITY=high`, rank(medium=1) < rank(high=2) → routes "digest". |
| 3  | `ALERT_MIN_SEVERITY=critical` restricts immediate alerts to criticals only (SC#3, ALERT-03) | VERIFIED | `alert_router.route_event` compares `_SEVERITY_RANK[severity] >= _SEVERITY_RANK[ALERT_MIN_SEVERITY]`; with threshold=critical=3, only severity=critical (rank 3) satisfies; auth_failures (high=2) falls to digest. |
| 4  | Existing deployments (only TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) continue to receive critical alerts unchanged (SC#4, ALERT-05) | VERIFIED | `app/config.py:21` defaults `ALERT_MIN_SEVERITY="high"` when env unset. Existing env vars untouched (`grep` confirms TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HONEYPOT_INSTANT_BLOCK unchanged). `send_alert_sync` signature unchanged in `telegram_alerter.py:100`. |
| 5  | `digest_events` table exists and medium event persists immediately, surviving restart (SC#5, DIGEST-01, DIGEST-03) | VERIFIED | `DigestEvent` model in `app/database.py:72-80` with exact schema {id, timestamp, source, source_id, severity, sent_at}. `init_db()` at line 83 calls `Base.metadata.create_all(engine)` — idempotent create. `persist_to_digest` commits inline (`alert_router.py:72`) so survives restart. |
| 6  | ALERT_MIN_SEVERITY env var loaded at startup with default 'high' | VERIFIED | `app/config.py:21-26`. |
| 7  | Invalid ALERT_MIN_SEVERITY falls back to 'high' with warning print | VERIFIED | `app/config.py:22-24` validates against `{"critical","high","medium"}`, prints warning and falls back. No exception raised (matches codebase convention). |
| 8  | Request-count escalation preserved (>50→critical, >20→high for medium) | VERIFIED | `alert_router.get_severity` lines 37-40 contains exact escalation logic; duplicated logic was removed from `telegram_alerter.py` (no `request_count > 50` grep match). |
| 9  | telegram_alerter re-imports THREAT_SEVERITY from alert_router (identity, not redefinition) | VERIFIED | `telegram_alerter.py:9` — `from app.alert_router import THREAT_SEVERITY, get_severity`. No `THREAT_SEVERITY = {...}` assignment remains. |
| 10 | alert_router is a leaf module (no imports from telegram_alerter/log_watcher/auto_blocker) | VERIFIED | `alert_router.py` imports only `datetime`, `typing`, `sqlalchemy.orm`, `app.config`, `app.database`. No sender/watcher/blocker imports. |
| 11 | Auto-block notifications go to digest only; auto_blocker skips the router entirely (ALERT-04, D-05) | VERIFIED | `app/auto_blocker.py`: `send_alert` / `send_alert_sync` — 0 occurrences; `route_event` — 0 occurrences; `persist_to_digest` — 3 occurrences (1 import + 2 call sites). `notify_auto_block` and `_send_honeypot_alert` fully removed. |
| 12 | log_watcher reuses already-open db session for digest write (no second SessionLocal); `intruder.id` populated pre-digest (DIGEST-02) | VERIFIED | `log_watcher.py`: `SessionLocal()` occurs exactly once (line 97); digest write on line 139 reuses `db`. `intruder.id` populated by `db.commit()` on line 132 before `persist_to_digest` on line 139. No FK; Phase 2 will JOIN on (source, source_id). |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `app/config.py` | `ALERT_MIN_SEVERITY` constant with validation | VERIFIED | Lines 18-26; default 'high', lowercased, invalid fallback with warning. |
| `app/database.py` | `DigestEvent` SQLAlchemy model on Base | VERIFIED | Lines 72-80; 6 columns, index on timestamp + sent_at; no FK (per DIGEST-02). |
| `app/alert_router.py` | New leaf module exporting THREAT_SEVERITY, get_severity, route_event, persist_to_digest | VERIFIED | 73 lines; all 4 exports present; synchronous `persist_to_digest` (no `async def`); commits inline. |
| `app/telegram_alerter.py` | Refactored to import from alert_router | VERIFIED | Line 9 imports; local THREAT_SEVERITY dict removed; `get_severity_header` delegates to `alert_router.get_severity`; `send_telegram_alert` line 79 uses `get_severity(reason, event)`. |
| `app/log_watcher.py` | Gated call site using route_event | VERIFIED | Line 12 import; lines 136-144 branching `if/else` on `route_event`. |
| `app/auto_blocker.py` | Both block paths redirect to persist_to_digest | VERIFIED | Line 16 import; lines 130-135 (auto-block) and 209-214 (honeypot) call `persist_to_digest` with `source="auto_block"`, `severity="high"`. Obsolete functions removed. |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `app/alert_router.py` | `app.config.ALERT_MIN_SEVERITY` | module-level import | WIRED (line 9) |
| `app/alert_router.py` | `app.database.DigestEvent` | persist_to_digest writes row | WIRED (line 10 + line 64) |
| `app/telegram_alerter.py` | `app/alert_router.py` | THREAT_SEVERITY + get_severity re-import | WIRED (line 9) |
| `app/log_watcher.py` | `app/alert_router.py` | route_event, persist_to_digest, get_severity | WIRED (line 12, usage lines 136-144) |
| `app/auto_blocker.py` | `app/alert_router.py` | persist_to_digest only (skips router) | WIRED (line 16, usages lines 130, 209) |
| `app/auto_blocker.py` | DigestEvent via `source="auto_block"` using `result["id"]` | 2 call sites | WIRED |

### Data-Flow Trace (Level 4)

| Flow | Source | Status |
| ---- | ------ | ------ |
| Intruder event → route_event → digest | Real data from `analyze_log(parsed)` in `log_watcher.py:120`; writes real `intruder.id` | FLOWING |
| Auto-block → persist_to_digest | Real `result["id"]` from `block_ip()` (confirmed dict shape from `app/blocklist.py:191-228`) | FLOWING |
| Honeypot block → persist_to_digest | Real `result["id"]` from same `block_ip` path | FLOWING |

### Behavioral Spot-Checks

Automated runtime checks could not execute in the sandbox (python3 environment lacks sqlalchemy/pip). All behaviors were verified by static inspection against plan action blocks (which specified exact code). Per Step 7b constraints, marking as SKIPPED — see Human Verification.

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| alert_router imports + routing matrix | `python3 -c "from app.alert_router import ..."` | ModuleNotFoundError: sqlalchemy (host env) | SKIP (no runtime deps in host; runs in Docker image) |
| config default/fallback | `ALERT_MIN_SEVERITY=bogus python3 -c ...` | SKIP | SKIP |
| digest persist round-trip | DB init + insert + query | SKIP | SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| ALERT-01 | 01-02 | Route by severity (crit/high immediate, medium digest) | SATISFIED | Truth #2, #3; `route_event` gate in `log_watcher.py:136`. |
| ALERT-02 | 01-02 | Critical threats always bypass suppression | SATISFIED | Truth #1; crit rank=3 ≥ all thresholds ≤3. |
| ALERT-03 | 01-01 | `ALERT_MIN_SEVERITY` env var (default high) | SATISFIED | `app/config.py:21`. |
| ALERT-04 | 01-03 | Auto-blocks go to digest, not Telegram | SATISFIED | Truth #11; `auto_blocker.py` — 0 send_alert, 2 persist_to_digest calls. |
| ALERT-05 | 01-01 | Existing Telegram config continues unchanged | SATISFIED | Truth #4; default preserves behavior, no env var removed. |
| DIGEST-01 | 01-01, 01-03 | Events persisted to SQLite immediately | SATISFIED | `persist_to_digest` commits inline; called on detection. |
| DIGEST-02 | 01-02, 01-03 | No duplicate storage (only source + source_id) | SATISFIED | `DigestEvent` has no denormalized fields; no ForeignKey; Phase 2 will JOIN. |
| DIGEST-03 | 01-01 | Digest state survives restart | SATISFIED | SQLite commit is durable; `sent_at=None` marks pending rows survive restart. |

No orphaned requirements. No new requirements introduced. All 8 IDs from PLAN frontmatter match REQUIREMENTS.md Phase 1 mapping exactly.

### Anti-Patterns Found

No blockers. Static scan across modified files (`app/config.py`, `app/database.py`, `app/alert_router.py`, `app/telegram_alerter.py`, `app/log_watcher.py`, `app/auto_blocker.py`):

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| (none) | No TODO/FIXME/placeholder/"not implemented" introduced | — | — |
| `app/alert_router.py:35` | `request_count = event.get("request_count", 1) or 1` — `or 1` handles both missing and None | Info | Intentional per plan; matches acceptance test `{'request_count': None}`. |

Constraint checks:
- No new entries in `requirements.txt` (unchanged — 8 deps, same as baseline).
- No custom exception classes introduced.
- No `async def` on `persist_to_digest`.
- No circular imports (alert_router is a leaf; grep-verified).

### Human Verification Required

Automated verification is complete and passing under static inspection + plan conformance. The following items require human confirmation because they depend on live runtime / external services:

1. **Live Telegram send for critical event**
   **Test:** Trigger an SQL injection pattern against a Traefik-proxied host (e.g. `curl "https://<host>/?id=1%27%20UNION%20SELECT%201--"`) while the Sentinel container is running with existing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
   **Expected:** Telegram chat receives a CRITICAL THREAT DETECTED message within a few seconds; no message when triggering `/wp-admin` scan (suspicious_path → digest).
   **Why human:** Requires network, Telegram API, and a running container — cannot be exercised from code-only verification.

2. **Digest row survives container restart**
   **Test:** Trigger a suspicious_path scan, `docker compose restart traefik-dashboard`, then `sqlite3 data/dashboard.db "SELECT * FROM digest_events WHERE sent_at IS NULL;"`.
   **Expected:** Row persists across the restart with `sent_at IS NULL`.
   **Why human:** Requires actual container lifecycle.

3. **Default deployment (no new env vars) still alerts on criticals**
   **Test:** Upgrade existing deployment without setting `ALERT_MIN_SEVERITY`; trigger an SQL injection.
   **Expected:** Telegram message delivered as before.
   **Why human:** Backwards-compat guarantee is user-observable in production.

4. **Host Python sandbox couldn't run the plans' own verify blocks**
   **Test:** Inside the Docker image (has sqlalchemy): run the three `python -c` blocks embedded in `01-01-PLAN.md`, `01-02-PLAN.md`, and `01-03-PLAN.md` `<automated>` sections.
   **Expected:** All print "OK …" messages (routing matrix, persist_to_digest round-trip, identity check).
   **Why human:** Host system has no `pip`/`sqlalchemy`; runnable inside the project container only.

### Gaps Summary

No gaps. All 12 must-haves verified via static inspection against plan specifications. Every code change specified in the three plans' `<action>` blocks appears verbatim in the repository:
- `ALERT_MIN_SEVERITY` block in `app/config.py` (lines 18-26) matches plan 01-01 verbatim.
- `DigestEvent` model in `app/database.py` (lines 72-80) matches plan 01-01 verbatim.
- `app/alert_router.py` matches plan 01-02 verbatim, 73 lines, leaf module.
- `app/telegram_alerter.py` refactor matches plan 01-02 (THREAT_SEVERITY re-imported, duplicated escalation removed).
- `app/log_watcher.py` gating block matches plan 01-03 (lines 134-144).
- `app/auto_blocker.py` changes match plan 01-03 (two `persist_to_digest` call sites with `source="auto_block"`, `severity="high"`; `notify_auto_block` and `_send_honeypot_alert` removed; no `send_alert*` references).

Acceptance focus items all confirmed:
- route_event gate in log_watcher — YES (line 136).
- auto_blocker skips router + always persists to digest — YES (0 route_event, 0 send_alert, 2 persist_to_digest calls).
- DigestEvent model exists — YES.
- ALERT_MIN_SEVERITY config wired — YES (imported by alert_router).
- telegram_alerter re-imports severity from alert_router — YES.
- No new requirements.txt deps — YES (unchanged).
- No custom exceptions — YES.

Status is `human_needed` rather than `passed` solely because (a) runtime smoke tests could not be executed in the host sandbox, and (b) the live Telegram delivery path and container-restart durability are inherently observable only to a human operator.

---

_Verified: 2026-04-12_
_Verifier: Claude (gsd-verifier)_
