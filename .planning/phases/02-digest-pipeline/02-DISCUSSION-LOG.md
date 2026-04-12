# Phase 2: Digest Pipeline - Discussion Log

> Audit trail only. Decisions are in CONTEXT.md.

**Date:** 2026-04-12
**Phase:** 02-digest-pipeline
**Mode:** --chain (interactive discussion, then auto plan+execute)
**Areas discussed:** Message layout, Digest window, Truncation policy, Manual trigger, Bookkeeping

User requested explanation in German, then accepted all 5 recommended defaults with "ok".

---

## 1. Message Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Header → blocked → attacks → top IPs (10) → traffic → footer, "since last digest" framing, emoji-rich | Matches existing alerter aesthetics | ✓ |
| Flat list / markdown table | Simpler but less scannable | |

## 2. Digest Window

| Option | Description | Selected |
|--------|-------------|----------|
| `sent_at IS NULL` (gapless) | Each event appears exactly once; empty = zero unsent | ✓ |
| Rolling 24h regardless of sent_at | Simpler clock logic but risks double-reports | |

## 3. Truncation Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Trim IP list first (10→5→3, "+N more"), then paths, never attack breakdown / core counts | Preserves signal | ✓ |
| Naive string truncation at 4096 | Simpler but mangles HTML / drops critical info | |

## 4. Manual Trigger Interface

| Option | Description | Selected |
|--------|-------------|----------|
| REST endpoint `POST /api/digest/send` only | Matches existing API style, no auth (firewall-protected) | ✓ |
| CLI + REST | More surface area to maintain | |

## 5. `sent_at` Bookkeeping

| Option | Description | Selected |
|--------|-------------|----------|
| Batch UPDATE after HTTP 200 only; failures leave rows unsent for retry | Simple and robust | ✓ |
| Per-row update during send | Needlessly complex | |

## Claude's Discretion

- HTML template string wording/spacing
- Private helper function names
- Whether to return the assembled message text in the endpoint response (recommended: yes, for UAT)

## Deferred

- Scheduler (`DIGEST_HOUR`, lifespan task) → Phase 3
- `DIGEST_ENABLED` kill switch → Phase 3
- Auth on endpoint → existing design is unauthenticated
- Dry-run / preview endpoint → optional, planner's call
