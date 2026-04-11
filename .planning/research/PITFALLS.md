# Domain Pitfalls: Alert Aggregation and Digest Notifications

**Domain:** Security monitoring tool — digest/summary notification system
**Researched:** 2026-04-11
**Scope:** Adding digest notifications and smart alerting to traefik-sentinel

---

## Critical Pitfalls

Mistakes that cause silent alert loss, duplicate sends, or full rewrites.

---

### Pitfall 1: Digest State Lost on Container Restart

**What goes wrong:** The in-memory digest buffer (accumulated events since last send) is wiped every time Docker restarts the container. On a security tool, this is a silent failure — the operator assumes they will receive a morning digest covering the last 24 hours, but a container restart at any point discards accumulated events without sending.

**Why it happens:** Python dicts and lists are ephemeral. APScheduler's default in-memory job store loses both the buffer and the scheduled next-run time on restart. There is no crash, no error, no signal to the operator. Events simply vanish.

**Consequences:**
- Night-time restarts (OS updates, Docker daemon upgrades) silently drop the overnight accumulation
- The digest arrives empty or not at all, giving false assurance that nothing happened
- If the scheduler also loses its next-run time, the digest may send immediately after restart (at 3am instead of 8am) and then not again for 24 hours

**Prevention:**
- Persist digest state to the existing SQLite database, not memory. A `digest_buffer` table with `event_id`, `added_at`, and `digest_sent_at` (nullable) cleanly survives restarts
- On startup, load unsent events from the table into the active buffer
- On each event added to the digest buffer, write to DB immediately — not at send time
- Use APScheduler with `SQLAlchemyJobStore` pointing at the existing SQLite file, or recompute the next scheduled send from a persisted `last_sent_at` timestamp stored in DB

**Detection (warning sign):** If digest arrives suspiciously empty after a restart, or arrives at an unexpected time, state loss has occurred.

**Phase:** Must be addressed in the initial digest implementation phase, not a later hardening phase. Retrofitting persistence after the fact requires a schema migration.

---

### Pitfall 2: Critical Alerts Swallowed by Severity Threshold

**What goes wrong:** The operator sets `ALERT_MIN_SEVERITY=high` to reduce noise. A SQL injection attempt arrives, its `request_count` is 1 (first hit), so `get_severity_header` computes `critical` from the `THREAT_SEVERITY` map — but a bug or future refactor in the severity escalation logic recategorizes it as `medium`. The alert is silently dropped and never appears in the digest either because the digest cutoff also filters by severity.

**Why it happens:** The current `telegram_alerter.py` has two severity paths: the static `THREAT_SEVERITY` dict and a dynamic escalation based on `request_count`. Any code touching the escalation logic can inadvertently downgrade a known-critical threat type. With a threshold filter layered on top, the drop is invisible.

**Consequences:**
- A real intrusion goes unnoticed for 24 hours until the next digest — or longer if the digest also filtered it
- No log entry, no alert, no digest mention. The operator has no idea

**Prevention:**
- Define severity as a two-layer system: `base_severity` (from threat type, immutable) and `effective_severity` (after escalation). The threshold filter must compare against `base_severity` for known-critical types, not `effective_severity`
- SQL injection and honeypot triggers must bypass any threshold filter entirely — they are never digest candidates regardless of request count
- Add an explicit test: assert that `sql_injection` and `honeypot` events always produce an immediate alert regardless of `ALERT_MIN_SEVERITY` value
- Log every suppressed alert to stdout so Docker logs show the decision: `"Suppressed alert for {ip}: severity=medium below threshold=high"`

**Detection (warning sign):** If a honeypot or SQL injection event appears in the DB (intruder_events table) but no Telegram message was received, alerts are being swallowed.

**Phase:** Must be locked in before the threshold filter is implemented — the invariant (critical types bypass threshold) should be written as code before the filter, not patched after.

---

### Pitfall 3: Scheduler Running Twice in Docker (Duplicate Digests)

**What goes wrong:** APScheduler is started inside FastAPI's lifespan or at module import time. Uvicorn's `--reload` flag (used in development) spawns a watcher process plus a server process. Each process runs the lifespan, starting two independent scheduler instances. Both fire at the scheduled time, sending two identical digest messages.

**Why it happens:** This is a well-documented APScheduler + Uvicorn combination problem. The production deployment uses `docker compose restart` with a single container, but any future change to uvicorn args (or running the app directly with `--reload`) silently doubles the schedulers.

**Consequences in production:** Not currently triggered (single worker, no reload), but fragile. Rebuilding the container with a new `CMD` that adds `--workers 2` for performance silently enables the bug permanently.

**Prevention:**
- Always use `AsyncIOScheduler` inside the FastAPI lifespan context manager (not at module level)
- Add a guard: check an environment variable `SCHEDULER_ENABLED=true` (default true) so it can be disabled when running multiple workers
- Name the scheduled job with an explicit `id` and set `replace_existing=True` — this prevents duplicate job registration if lifespan fires more than once
- In the Dockerfile, keep `CMD` as single-worker; document this constraint in a comment in `docker-compose.yml`

**Detection (warning sign):** Receiving two near-simultaneous digest messages. Or seeing two APScheduler start log lines in `docker logs traefik-dashboard`.

**Phase:** Scheduler instantiation phase — address at the time the scheduler is introduced, not during a later cleanup pass.

---

### Pitfall 4: `asyncio.run()` Called from Inside FastAPI's Running Event Loop

**What goes wrong:** The existing `send_alert_sync()` in `telegram_alerter.py` already has this bug in latent form. It calls `asyncio.run(send_telegram_alert(event))` from `log_watcher.py`'s synchronous `process_line()`. This works today only because `process_line` runs in a thread context where there is no running event loop. The moment a digest scheduler is introduced using `AsyncIOScheduler`, the scheduler runs jobs inside FastAPI's event loop. If the digest sender calls `asyncio.run()` or the synchronous wrapper `send_alert_sync()`, it will raise `RuntimeError: This event loop is already running`.

**Why it happens:** `asyncio.run()` creates a new event loop. It cannot be called when one already exists on the thread — which is always the case inside an `AsyncIOScheduler` job or any `async def` in FastAPI.

**Consequences:** The digest job crashes silently (or with a logged exception that may be easy to miss), the digest is never sent, and the buffer is not cleared. The next job run will try again with a doubled buffer.

**Prevention:**
- The digest sender must be an `async def` function. The `AsyncIOScheduler` job must be scheduled with `add_job(send_digest, 'cron', ...)` where `send_digest` is the async coroutine directly
- Remove the `send_alert_sync` wrapper from any async code paths. Callers in `log_watcher.py` run in a thread, which is fine, but new code (digest, severity check) should use `await send_telegram_alert(...)` directly
- Audit all new notification code: if it runs under `AsyncIOScheduler`, it must use `await`, never `asyncio.run()`

**Detection (warning sign):** `RuntimeError: This event loop is already running` in Docker logs, or digest never arrives despite scheduler firing.

**Phase:** Must be verified at the time the digest sender function is written — not discovered during integration testing.

---

## Moderate Pitfalls

---

### Pitfall 5: Telegram 4096-Character Limit Breaks Digest on Active Days

**What goes wrong:** A busy day produces 200 blocked IPs and 40 attack events. The digest message is constructed as a single string and exceeds Telegram's 4096-character limit. The API returns `400 Bad Request: message is too long`. The digest silently fails to send (or the except clause swallows the error), and the buffer is cleared anyway — the day's summary is lost.

**Why it happens:** Telegram enforces a hard 4096-character limit per message. An unconstrained digest template that lists every blocked IP and every event will reliably exceed this on an internet-facing server.

**Consequences:** No digest received. Operator assumes quiet day. All accumulated data for that window is cleared without delivery confirmation.

**Prevention:**
- Design the digest as a fixed-structure summary, not a per-event list. Count events by type; list only the top N attackers (e.g., top 5 by request count)
- Before sending, measure `len(message)`. If over 3800 characters (leaving headroom for HTML entities), truncate gracefully: `"... and 43 more events. Full details in dashboard."`
- Implement chunked sending as a fallback: split into multiple sequential messages if the summary itself exceeds the limit
- Only clear the digest buffer after receiving HTTP 200 from Telegram — not before

**Detection (warning sign):** No digest received on days with high activity. `400` error in logs.

**Phase:** Digest message formatting phase.

---

### Pitfall 6: Telegram HTML Parse Mode Breaks on Unescaped User Data

**What goes wrong:** The current `telegram_alerter.py` uses `parse_mode=HTML`. Attack details and paths are embedded directly in the message: `<code>{event.get('details', 'N/A')}</code>`. A path like `/search?q=<script>alert(1)</script>` injects a raw `<script>` tag. Telegram's HTML parser either raises `can't parse entities` (400 error) or silently truncates everything after the tag.

**Why it happens:** Traefik logs contain raw request paths from attackers who actively inject HTML and XML characters. The existing code does not escape these before embedding them in HTML-mode Telegram messages.

**Consequences:** Alert or digest fails to send. Worse: silent truncation means the message is delivered but the attacker's details are missing, defeating the purpose of the alert.

**Prevention:**
- Escape all event-derived strings with a helper before embedding in HTML messages:
  ```python
  import html
  safe = html.escape(str(value))
  ```
- Apply this to: `details`, `path`, `ip` (unlikely to contain HTML but be consistent), `host`, `recommendation`
- This is required for both immediate alerts and digest messages

**Detection (warning sign):** Alerts succeed on benign paths but fail or arrive truncated after SQL injection or XSS probe events.

**Phase:** Can be fixed in the existing alerter before the digest is added — small change, high impact.

---

### Pitfall 7: Digest Sent at Wrong Time Due to UTC/Local Timezone Mismatch

**What goes wrong:** The operator sets `DIGEST_SCHEDULE_HOUR=8` expecting a daily digest at 8am local time. The Docker container runs with `TZ` unset (defaults to UTC). The scheduler fires at 8am UTC, which may be 3am or 10am in the operator's timezone. Since the operator is asleep at 3am, the digest is effectively invisible until they check manually.

**Why it happens:** Python's `datetime.utcnow()` (used throughout the codebase) returns UTC with no timezone info. APScheduler's cron trigger, when no timezone is specified, uses the system timezone — which in a Docker container without `TZ` is UTC. The mismatch between wall-clock expectation and UTC firing time is invisible until noticed.

**Consequences:** Digest arrives at the wrong time. Less severe than data loss, but erodes trust in the notification system.

**Prevention:**
- Expose `DIGEST_TIMEZONE` as an environment variable (default `UTC`), document it clearly in `.env.example`
- Pass the timezone to the APScheduler cron trigger explicitly: `CronTrigger(hour=8, timezone=ZoneInfo(DIGEST_TIMEZONE))`
- Use `zoneinfo` (Python 3.9+ stdlib) for IANA timezone names — no extra dependency needed
- Add `TZ=UTC` to `docker-compose.yml` as an explicit default so container timezone is always predictable
- Note: `datetime.utcnow()` is deprecated in Python 3.12+. Replace all occurrences with `datetime.now(timezone.utc)` when touching time-related code in this milestone

**Detection (warning sign):** Digest arrives at an unexpected hour relative to the configured value.

**Phase:** Scheduler configuration phase — set timezone at the time the cron trigger is written.

---

### Pitfall 8: Cooldown State Lost on Restart Causes Alert Flood

**What goes wrong:** The existing per-IP/reason Telegram cooldown (currently implied by the 15-minute comment in PROJECT.md context) is held in memory. After a container restart, the cooldown resets. If a high-volume scanner was being suppressed by the cooldown, the restart causes an immediate burst of alerts for every recent event as each is reprocessed or re-detected.

**Why it happens:** Cooldown state is ephemeral. The restart triggers startup processing (file position reset to end of file avoids replaying history, but any queued events in memory are lost and re-triggered from live traffic).

**Consequences:** After a restart during an active attack, the operator receives a flood of individual alerts rather than the expected cooldown behavior.

**Prevention:**
- Persist cooldown timestamps in the SQLite DB alongside the digest buffer state
- On startup, load cooldown state from DB before processing any new events
- Alternatively: the move to severity-based filtering (only critical events get immediate alerts) naturally reduces restart-flood risk, since routine scanner traffic goes to digest instead of immediate alerts

**Detection (warning sign):** Burst of Telegram messages immediately after a container restart during an active incident.

**Phase:** Alerting refactor phase (when immediate vs. digest routing is implemented).

---

## Minor Pitfalls

---

### Pitfall 9: Empty Digest Sent on Quiet Days

**What goes wrong:** `DIGEST_SEND_EMPTY=false` is not implemented. The digest scheduler fires at 8am but nothing happened overnight. An empty "Daily Security Summary — 0 events" message is sent. On quiet weeks, this becomes noise that trains the operator to ignore digest messages.

**Prevention:**
- Check buffer length before sending. If `len(buffered_events) == 0`, skip the send entirely
- Log `"Digest skipped: no events since last send"` to Docker logs so the operator can verify it ran
- This requirement is already stated in PROJECT.md: "Digest sends only when there is activity to report"

**Phase:** Digest send logic — trivial if-check, implement from the start.

---

### Pitfall 10: Telegram Rate Limit on Rapid Critical Alerts

**What goes wrong:** A DDoS or automated scanner triggers 50 SQL injection detections in 2 seconds. Each generates an immediate critical alert. Telegram enforces 1 message/second per chat. The 50th alert call receives HTTP 429 with a `retry_after` value. The current `send_alert_sync` has no retry logic — it catches the exception and returns `False`, dropping the alert.

**Why it happens:** Telegram's documented limit is 30 messages/second globally and 1 message/second to the same chat. The current implementation fires `httpx.AsyncClient().post()` with a 10-second timeout but no retry on 429.

**Consequences:** Critical alerts silently dropped during the worst incidents — exactly when they matter most.

**Prevention:**
- For immediate alerts, add a simple retry with `retry_after` respect: on 429, sleep the `retry_after` seconds and retry once
- For the digest, there is only one send per window, so 429 is unlikely unless the operator has many bots in the same chat
- The per-IP severity cooldown (once implemented) also naturally prevents the burst

**Phase:** Alerting refactor phase — add retry logic when rewriting the alert send path.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Digest buffer implementation | State lost on restart (Pitfall 1) | Use SQLite table, not memory dict |
| Severity threshold filter | Critical alerts swallowed (Pitfall 2) | sql_injection + honeypot bypass filter always |
| Scheduler introduction | Duplicate schedulers in Docker (Pitfall 3) | Single worker, lifespan init, explicit job ID |
| Digest sender function | asyncio event loop conflict (Pitfall 4) | async def only, no asyncio.run() calls |
| Digest message formatting | 4096-char limit exceeded (Pitfall 5) | Fixed summary structure, truncation with fallback |
| Embedding event data in HTML | Unescaped attacker content (Pitfall 6) | html.escape() on all event fields |
| Cron trigger configuration | Wrong timezone (Pitfall 7) | DIGEST_TIMEZONE env var, explicit ZoneInfo |
| Immediate alert routing | Restart causes flood (Pitfall 8) | Persist cooldown in DB |
| Digest send decision | Empty digest noise (Pitfall 9) | Skip send when buffer is empty |
| High-frequency critical events | Telegram 429 drops critical alerts (Pitfall 10) | Retry once with retry_after |

---

## Sources

- [Telegram Bot API rate limits — python-telegram-bot wiki](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Avoiding-flood-limits) — MEDIUM confidence (wiki, not official Bot API docs)
- [Telegram 4096-character limit — node-telegram-bot-api issue #165](https://github.com/yagop/node-telegram-bot-api/issues/165) — HIGH confidence (documented behavior, reproducible)
- [HTML parse_mode entity truncation — Prometheus Alertmanager issue #2923](https://github.com/prometheus/alertmanager/issues/2923) — HIGH confidence (reproduced in production tools)
- [APScheduler user guide — persistent job stores](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — HIGH confidence (official docs)
- [APScheduler FAQ — duplicate jobs on restart](https://apscheduler.readthedocs.io/en/3.x/faq.html) — HIGH confidence (official docs)
- [APScheduler + FastAPI duplicate scheduler — FastAPI issue #1124](https://github.com/fastapi/fastapi/issues/1124) — HIGH confidence (confirmed in FastAPI project issue tracker)
- [asyncio RuntimeError already running — Python docs](https://docs.python.org/3/library/asyncio-dev.html) — HIGH confidence (official Python docs)
- [utcnow() deprecation — Simon Willison TIL](https://til.simonwillison.net/python/utc-warning-fix) — HIGH confidence (Python 3.12 changelog confirms)
- [Python schedule library timezone handling](https://schedule.readthedocs.io/en/stable/timezones.html) — HIGH confidence (official docs)
