---
phase: 02-digest-pipeline
verified: 2026-04-12T00:00:00Z
status: human_needed
score: 11/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "End-to-end send against a real Telegram chat"
    expected: "Operator receives a well-formatted HTML digest; emoji/flags render; no parse errors"
    why_human: "Only the Telegram Bot API can confirm HTML parse_mode acceptance of the assembled message with real attacker content"
  - test: "Visual rendering review of preview output on a populated DB"
    expected: "Layout (header, blocked section, breakdown, top attackers, traffic, footer) reads cleanly; spacing acceptable"
    why_human: "Aesthetic / readability judgment is not programmatically verifiable"
---

# Phase 2: Digest Pipeline Verification Report

**Phase Goal:** Accumulated digest events aggregated into a well-formatted Telegram message within Telegram's 4096-char limit; skipped silently when nothing to report.
**Verified:** 2026-04-12
**Status:** human_needed (all automated checks pass; human UAT recommended for visual/Telegram acceptance)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | send_digest() skips silently on empty unsent set (no Telegram call) | VERIFIED | `test_skip_when_empty` passes; app/digest.py:365-372 early-returns before send_alert |
| 2 | send_digest() with N unsent events builds HTML message with blocked count, attack breakdown, top attackers w/ flags, traffic overview | VERIFIED | `test_blocked_count`, `test_attack_breakdown`, `test_top_attackers_ordering`, `test_traffic_window` all pass; _build_* helpers at app/digest.py:69-222 |
| 3 | Attacker-controlled strings (ip, path, user_agent, host, country) are HTML-escaped | VERIFIED | `test_html_escape`, `test_preview_escape` pass; per-value `_esc()` via `html.escape(..., quote=False)` at app/digest.py:48-56; applied at 149-168, 220 |
| 4 | Assembled message ≤ 4000 UTF-16 code units even with 100+ attackers | VERIFIED | `test_truncation` (200 IPs) and `test_preview_utf16_under_limit` (50 IPs) pass; _tg_len uses utf-16-le encoding at app/digest.py:43-45; SAFETY_LIMIT=4000 at :29 |
| 5 | sent_at stamped only after Telegram returns HTTP 200 | VERIFIED | `test_sent_at_only_on_success` both success and failure cases pass; UPDATE at app/digest.py:382-389 is inside the `if telegram_ok:` branch |
| 6 | POST /api/digest/send returns D-17 shape; empty→no_events; success→sent=True | VERIFIED | 3 endpoint tests pass (empty, success, telegram_failure); route at app/main.py:761-765 |
| 7 | GET /api/digest/preview returns same assembly; does not call Telegram; does not stamp sent_at | VERIFIED | `test_preview_read_only` (2 calls + send_alert raises assertion if called) passes; preview_digest at app/digest.py:327-350 has no send_alert / UPDATE / commit |
| 8 | Preview on empty returns {event_count: 0, message: null, utf16_length: 0} | VERIFIED | `test_preview_empty` passes; app/digest.py:341-342 |
| 9 | send_digest is `async def` and uses `await send_alert` (never send_alert_sync) | VERIFIED | grep send_alert_sync = 0; grep "await send_alert(" = 1 at app/digest.py:377 |
| 10 | Two-query hydration (no polymorphic JOIN); per-source id.in_(ids) | VERIFIED | app/digest.py:302-313 — separate queries keyed by `IntruderEvent.id.in_(intruder_ids)` and `BlockedIP.id.in_(block_ids)` |
| 11 | No Phase-3 scope creep (no DIGEST_HOUR / DIGEST_ENABLED / zoneinfo / asyncio.create_task / new env vars) | VERIFIED | grep across app/digest.py returns 0; no changes to app/config.py |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/digest.py` | send_digest/build_message/preview_digest, UTF-16 helper | VERIFIED | 410 lines, all required symbols present and wired |
| `app/main.py` | POST /api/digest/send, GET /api/digest/preview | VERIFIED | Import at line 15; routes at lines 761-765 and 768-772 |
| `tests/test_digest.py` | 8 unit tests CONTENT-01..06, SCHED-03, D-18 | VERIFIED | 8 tests pass |
| `tests/test_digest_endpoint.py` | 3 integration tests, ASGITransport | VERIFIED | 3 tests pass |
| `tests/test_digest_preview.py` | 4 preview tests | VERIFIED | 4 tests pass |
| `tests/conftest.py` | in-memory SQLite fixture + factories | VERIFIED | Fixture present |
| `requirements-dev.txt` | pytest + pytest-asyncio | VERIFIED | Both pinned |
| `pytest.ini` | asyncio_mode=auto | VERIFIED | Loaded by test run |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| app/digest.py | app.telegram_alerter.send_alert | `await send_alert(message, parse_mode="HTML")` | WIRED | app/digest.py:25, :377 |
| app/digest.py | app.geoip.lookup_batch | `await lookup_batch(top_ips)` | WIRED | app/digest.py:24, :141 |
| app/digest.py | digest_events table UPDATE | `synchronize_session=False` | WIRED | app/digest.py:387 (inside telegram_ok branch) |
| app/main.py | app.digest.send_digest | `from app.digest import send_digest, preview_digest` | WIRED | app/main.py:15 |
| app/main.py | app.digest.preview_digest | shared build_message path | WIRED | app/main.py:15, :772 |
| preview_digest | build_message | shared assembly, no Telegram | WIRED | app/digest.py:343 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| send_digest() | rows | `db.query(DigestEvent).filter(sent_at.is_(None))` | Yes (real ORM query) | FLOWING |
| _build_blocked_section | n | `count(distinct BlockedIP.ip) where id in block_ids` | Yes | FLOWING |
| _build_attack_breakdown | rows | `group_by IntruderEvent.reason where id in intruder_ids` | Yes | FLOWING |
| _build_top_attackers | top_rows, flags | IntruderEvent groupby + geoip.lookup_batch | Yes | FLOWING |
| _build_traffic_overview | total/unique/errors/top_hosts | AccessLog between(min_ts,max_ts) | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full pytest suite | `.venv/bin/pytest tests/ -v` | 15 passed in 1.68s | PASS |
| send_alert_sync absent | `grep -c send_alert_sync app/digest.py` | 0 | PASS |
| Phase-3 scope absent | `grep -cE "DIGEST_HOUR\|DIGEST_ENABLED\|asyncio.create_task\|zoneinfo" app/digest.py` | 0 | PASS |
| parse_mode HTML present | `grep -c 'parse_mode="HTML"' app/digest.py` | 1 | PASS |
| UTF-16 measurement present | `grep -c 'utf-16-le' app/digest.py` | 1 | PASS |
| Bulk UPDATE pattern | `grep -c 'synchronize_session=False' app/digest.py` | 1 | PASS |
| Phase 1 files untouched | `git diff --name-only HEAD -- app/telegram_alerter.py app/alert_router.py app/database.py app/geoip.py` | empty | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CONTENT-01 | 02-01 | Blocked IP count in digest | SATISFIED | `_build_blocked_section` + `test_blocked_count` |
| CONTENT-02 | 02-01 | Attack-type breakdown with per-type counts | SATISFIED | `_build_attack_breakdown` + `test_attack_breakdown` |
| CONTENT-03 | 02-01 | Top 5–10 attacker IPs with flag + count | SATISFIED | `_build_top_attackers` + `test_top_attackers_ordering` |
| CONTENT-04 | 02-01 | Traffic overview (total, unique, error rate, top hosts) | SATISFIED | `_build_traffic_overview` + `test_traffic_window` |
| CONTENT-05 | 02-01, 02-02, 02-03 | Fits Telegram 4096 limit with "+N more" | SATISFIED | `_truncate_if_needed` + `test_truncation`, `test_preview_utf16_under_limit` |
| CONTENT-06 | 02-01, 02-03 | HTML-escape attacker data | SATISFIED | `_esc()` per-value + `test_html_escape`, `test_preview_escape` |
| SCHED-03 | 02-01, 02-02 | Skip silently when no events | SATISFIED | early-return no_events + `test_skip_when_empty`, `test_endpoint_empty_returns_no_events` |

No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | None found | — | — |

No TODO/FIXME/placeholders; no stub returns; no send_alert_sync; no empty implementations. `datetime.utcnow()` is used for sent_at stamping — acceptable in Phase 2 (SCHED-05 timezone-aware work is explicitly Phase 3).

### Human Verification Required

1. **End-to-end Telegram send**
   - Test: Seed a handful of real digest_events rows (at least one intruder + one auto_block), ensure `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are configured, then `curl -X POST http://host:13923/api/digest/send`.
   - Expected: Telegram message delivered, parses in HTML mode (bold/italic/code renders), flags visible, no parse errors, attacker content shown escaped.
   - Why human: Only the live Telegram Bot API can confirm HTML parse_mode acceptance.

2. **Preview visual review**
   - Test: `curl http://host:13923/api/digest/preview` against a populated state.
   - Expected: Message body reads cleanly — sections spaced, emojis consistent, truncation "+N more" line appears when expected.
   - Why human: Aesthetic / readability judgment.

### Gaps Summary

No gaps. All 11 must-haves verified, all 7 requirement IDs satisfied, all 15 tests pass, wiring verified at the HTTP and library layer, and no Phase-3 scope creep. Human verification items are UAT polish (live Telegram + visual review), not automated failures.

---

_Verified: 2026-04-12_
_Verifier: Claude (gsd-verifier)_
