# Phase 1: Foundation and Alert Routing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-12
**Phase:** 01-foundation-and-alert-routing
**Mode:** --auto (recommended defaults, no interactive questions)
**Areas discussed:** Routing architecture, Severity model, Schema, Config surface, Persistence API

---

## Routing Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| New `alert_router.py` module | Centralize severity map + routing + persistence | ✓ |
| Gate inside `telegram_alerter.send_telegram_alert` | Fewer files but hides routing | |
| Inline checks at each call site | No new module but duplicated logic | |

**Selected:** new module. Keeps routing greppable and testable.

## Severity Model

| Option | Description | Selected |
|--------|-------------|----------|
| Integer rank `{critical:3, high:2, medium:1}` with `>=` comparison | Simple, standard | ✓ |
| String ordering with `Enum` | More type-safe but heavier | |

**Selected:** integer rank. Matches codebase's lightweight style (no Enum usage elsewhere).

## Honeypot vs. Auto-block Conflict (ALERT-02 vs ALERT-04)

| Option | Description | Selected |
|--------|-------------|----------|
| `auto_blocker` skips router, always writes to digest | Explicit, no clever flags | ✓ |
| Router with `force_digest=True` flag for auto-blocks | One entry point but flag-driven | |

**Selected:** `auto_blocker` calls `persist_to_digest` directly.

## digest_events Table Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Reference-based (source + source_id + sent_at) | Honors DIGEST-02 "no duplicate storage"; tiny table | ✓ |
| Denormalized copy of event fields | Simpler Phase 2 queries but duplicates data | |

**Selected:** reference-based per DIGEST-02.

## Config Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Only `ALERT_MIN_SEVERITY` in Phase 1 | Matches phase boundary | ✓ |
| Add all digest env vars up front | Premature for Phase 1 goal | |

**Selected:** `ALERT_MIN_SEVERITY` only; defer `DIGEST_*` to Phase 3.

## Claude's Discretion

- Function signatures, private helpers, import order.
- Debug-level print logging of routing decisions.
- Test structure (repo has no formal test suite).

## Deferred Ideas

- `DIGEST_HOUR` / `DIGEST_ENABLED` / `DIGEST_TIMEZONE` — Phase 3.
- Digest formatting, HTML escaping, truncation — Phase 2.
- Quiet hours, rate limiting, per-reason overrides — v2.
- Formal test suite.
