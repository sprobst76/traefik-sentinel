# Codebase Concerns

**Analysis Date:** 2026-04-11

## Tech Debt

**Event Loop Management in Synchronous Context:**
- Issue: Multiple places create/manage asyncio event loops in synchronous context, which is fragile
- Files: `app/log_watcher.py` (lines 58-72), `app/telegram_alerter.py` (lines 113-120), `app/auto_reporter.py` (lines 151-165)
- Impact: Can crash with "RuntimeError: There is no current event loop" in production, especially during reload or high load
- Fix approach: Implement a centralized async task scheduler or use FastAPI's background tasks consistently throughout

**Missing Error Handling in Critical Paths:**
- Issue: Database operations in `log_watcher.py` can fail silently with generic `except Exception: db.rollback()`
- Files: `app/log_watcher.py` (lines 149-150), `app/main.py` (multiple db endpoints)
- Impact: Silent failures mean data loss (lost logs, untracked intruders) without alerting operator
- Fix approach: Log all exceptions to a dedicated error log, distinguish between transient and permanent failures, implement circuit breaker for database

**Naive GeoIP Cache Management:**
- Issue: In-memory cache in `app/geoip.py` grows unbounded; no eviction policy beyond TTL check-on-read
- Files: `app/geoip.py` (lines 11-13, 173-181)
- Impact: Memory leak if millions of unique IPs are queried; old entries aren't evicted until accessed
- Fix approach: Implement LRU cache with max size, run periodic cleanup thread every 5 minutes

**No Connection Pooling for HTTP Calls:**
- Issue: New `httpx.AsyncClient()` created per request in `app/abuseipdb.py`, `app/geoip.py`, `app/telegram_alerter.py`
- Files: `app/abuseipdb.py` (line 49), `app/geoip.py` (line 45, 113), `app/telegram_alerter.py` (line 105)
- Impact: Connection overhead, waste system resources, slower API calls
- Fix approach: Use module-level shared client or context manager

## Known Bugs

**JSON Import Missing in main.py:**
- Issue: `json.dumps()` called on line 788 but `json` module not imported
- Files: `app/main.py` (line 788)
- Impact: Runtime NameError crash when SSE stream sends first data
- Fix approach: Add `import json` at top of file

**Honeypot Alert Message Still in German:**
- Issue: Honeypot block notification contains German text "Sofort blockiert!" despite English-only requirement
- Files: `app/auto_blocker.py` (lines 225, 256)
- Impact: Inconsistent UI/messaging; violates project English-only standard from CLAUDE.md
- Fix approach: Replace with English "Instantly blocked!"

**Missing Field Validation in Log Parser:**
- Issue: `parse_json_log()` uses dict.get() with fallbacks but doesn't validate IP format
- Files: `app/log_parser.py` (line 56-57)
- Impact: Invalid IPs like empty strings or "unknown" get stored in database, causing issues in CIDR checks and GeoIP lookups
- Fix approach: Add `ipaddress` validation before returning ParsedLog

**Database Connection Leaked in Endpoints:**
- Issue: All API endpoints create `SessionLocal()` but some paths don't reach `finally: db.close()`
- Files: `app/main.py` (lines 53-88, 94-118, 124-147, 150-248, 295-375, 429-462, 465-510, 513-522, 525-533, 536-546, 549-582, 587-608, 611-622, 627-690, 693-757)
- Impact: While `finally` blocks exist, early returns or exceptions before `try` could leak connections. Exception in response generation loses connection.
- Fix approach: Use context manager (`with SessionLocal() as db:`) or FastAPI dependency injection

**CIDR Cache Not Invalidated on New Blocks:**
- Issue: `is_ip_blocked_by_cidr()` queries database every time but doesn't cache results; no invalidation mechanism
- Files: `app/blocklist.py` (lines 57-71), `app/auto_blocker.py` (line 102)
- Impact: Repeated CIDR lookups slow down per-log processing; adding new CIDR doesn't invalidate old cache
- Fix approach: Cache CIDR blocks with TTL, invalidate on `write_blocklist_file()`

**Intruder Detection Alert Cooldown Can Be Bypassed:**
- Issue: Alert cooldown tracks `(ip, reason)` tuple but attacker can trigger multiple reasons to evade cooldown
- Files: `app/intruder_detection.py` (lines 24-56)
- Impact: Spam mitigation ineffective; one attacker can flood logs with different alert reasons
- Fix approach: Also track IP-level cooldown (alert once per IP per 5 minutes regardless of reason)

## Security Considerations

**API Has No Authentication:**
- Risk: All endpoints accessible without credentials; anyone with network access can view logs, IPs, blocklists, trigger cleanup
- Files: `app/main.py` (all endpoints)
- Current mitigation: Relies on network isolation (only accessible from trusted network)
- Recommendations: Add Bearer token or API key authentication, at minimum for write endpoints (`/api/blocklist`, `/api/retention/cleanup`, `/api/abuseipdb/report`)

**SQL Injection Detection Patterns Are Incomplete:**
- Risk: Regex patterns only catch obvious injection attempts; advanced obfuscation (unicode, encoding tricks) bypass detection
- Files: `app/config.py` (lines 64-75)
- Current mitigation: Detection is one layer; most web frameworks have built-in protection
- Recommendations: Consider using parameterized queries in proxied applications (Traefik itself is safe), document that this is second-layer detection only

**GeoIP API Rate Limit Not Enforced:**
- Risk: ip-api.com free tier has 45 req/min limit; no backoff implemented, just failures
- Files: `app/geoip.py` (lines 114-156)
- Current mitigation: Caching reduces hits; batch API helps
- Recommendations: Implement exponential backoff on 429 responses, add rate limit queue

**Environment Variables Not Validated:**
- Risk: Missing `TRAEFIK_LOG_PATH`, `TELEGRAM_BOT_TOKEN`, or invalid integers cause silent failures or crashes at runtime
- Files: `app/config.py`, `app/database.py`
- Current mitigation: Default values provided, but some are non-sensible (empty strings)
- Recommendations: Validate all env vars at startup, fail fast with clear error message

**Honeypot Paths Hardcoded:**
- Risk: No way to add custom honeypot paths without code change; false positives block legitimate apps
- Files: `app/config.py` (lines 78-124)
- Current mitigation: Honeypot is opt-in via `HONEYPOT_INSTANT_BLOCK` env var
- Recommendations: Load honeypot paths from database or file, allow dynamic updates via API

**AbuseIPDB API Key Exposed in Logs:**
- Risk: If exception occurs during AbuseIPDB call, key could be logged in stack trace
- Files: `app/abuseipdb.py` (lines 86, 148)
- Current mitigation: `print()` statements don't include full request details
- Recommendations: Never print request headers/params in exceptions; use structured logging with redaction

**Honeypot Block Notifications Unsafe:**
- Risk: Notification message includes full path in plain text; Telegram messages could be intercepted
- Files: `app/auto_blocker.py` (lines 220-225)
- Current mitigation: Uses HTTPS for Telegram API
- Recommendations: Consider not sending full paths in alerts for sensitive honeypot paths

## Performance Bottlenecks

**N+1 Queries in `/api/intruders` Endpoint:**
- Problem: For each intruder group, DNS reverse lookup called, then GeoIP batch called separately
- Files: `app/main.py` (lines 295-375); specifically lines 314, 349-351
- Cause: `resolve_ip()` runs sequentially in loop before batch GeoIP; could be combined
- Improvement path: Collect all IPs first, do batch GeoIP, then batch reverse DNS if needed

**Large Log Files Block File Watcher:**
- Problem: If Traefik log file gets very large (>10GB), reading entire file on startup is slow
- Files: `app/log_watcher.py` (lines 154-165, 20-23)
- Cause: `parse_log_file()` reads entire file; no pagination
- Improvement path: Read only last N MB of log file on startup, track position to resume

**Full Table Scan for CIDR Coverage Check:**
- Problem: Every IP block checks all CIDR ranges against database
- Files: `app/blocklist.py` (lines 57-71)
- Cause: No index on CIDR ranges; SQL query loads all CIDR blocks
- Improvement path: Index on `is_cidr`, cache active CIDR list in memory

**GeoIP Batch Requests Not Rate-Limited:**
- Problem: If 1000 requests come in, 10 batch requests (100 per batch) hit ip-api.com immediately
- Files: `app/geoip.py` (lines 90-161)
- Cause: No queue or throttling; batch API is fast but rate limit is 45 req/min
- Improvement path: Implement token bucket or queue to spread requests over time

**Database Vacuum in Transaction:**
- Problem: Line 745 in `main.py` runs VACUUM outside transaction, but if it fails, exception propagates
- Files: `app/main.py` (lines 740-747)
- Cause: Bare `except: pass` hides potential issues
- Improvement path: Log warnings for VACUUM failures, don't hide them silently

**Intruder Detection Request History Unbounded:**
- Problem: `detector.request_history` dict grows forever if new IPs keep arriving
- Files: `app/intruder_detection.py` (lines 20-21, 33-43)
- Cause: `_clean_old_entries()` only removes old entries within window; doesn't remove entire IP if no recent activity
- Improvement path: Remove IP entries not seen in last 24 hours, cap total dict size

## Fragile Areas

**Log Parser Format Detection:**
- Files: `app/log_parser.py` (lines 140-151)
- Why fragile: Regex pattern match is strict; any malformed JSON causes silent fallback to CLF. Malformed CLF returns None. Combined with validation gaps, unparseable logs silently disappear from database
- Safe modification: Add explicit format detection with fallback error logging, validate parsed output before storing
- Test coverage: No tests for malformed log handling; edge cases like truncated JSON not tested

**Event Loop Bootstrapping:**
- Files: `app/log_watcher.py` (lines 55-74), `app/auto_blocker.py` (lines 77-131)
- Why fragile: Complex logic to detect if loop is running, create if not, schedule task if possible. Different behavior on app startup vs request handling vs background task
- Safe modification: Always use `asyncio.create_task()` from running context; never call `loop.run_until_complete()` from async context
- Test coverage: No tests for event loop edge cases; crashes only on production reload

**Database Migration Logic:**
- Files: `app/database.py` (lines 78-101)
- Why fragile: ALTER TABLE assumes table exists; doesn't handle partial migrations (one column added, next fails). Uses PRAGMA which is SQLite-specific
- Safe modification: Implement proper migration framework (Alembic), test on empty and populated databases
- Test coverage: No migration tests; old deployments might have partial schema

**Blocklist Concurrency:**
- Files: `app/blocklist.py` (lines 289-305)
- Why fragile: `write_blocklist_file()` writes JSON without locking; concurrent requests could corrupt file. No atomic write pattern (write temp, rename)
- Safe modification: Use atomic write with temp file and rename; add file lock context manager
- Test coverage: No concurrent write tests; race condition could happen in production under load

**Honeypot vs Rate Limit False Positives:**
- Files: `app/intruder_detection.py` (lines 78-114), `app/auto_blocker.py` (lines 166-172)
- Why fragile: Honeypot blocks on exact path match; legitimate tools scanning for security could match (e.g., `/wp-admin` for health checks). No allowlist for legitimate scanners
- Safe modification: Add honeypot exemption list (API keys, user agents), log blocked attempts before blocking
- Test coverage: No tests for false positive scenarios; production will reveal issues

## Scaling Limits

**Database Size Growth:**
- Current capacity: SQLite supports files up to ~2TB, but query performance degrades significantly after 100M rows
- Limit: At 100 requests/sec, database grows ~8.6B rows per day (access_logs); hits performance limit in ~11 days
- Scaling path: Implement log rotation/archival, archive old tables to separate files, consider PostgreSQL migration if needs >1 year of history

**GeoIP Cache Memory:**
- Current capacity: In-memory dict with no size limit; assuming 500 bytes per entry (IP + metadata)
- Limit: 1 million unique IPs = ~500MB; 10 million = 5GB (OOM on typical 8GB server)
- Scaling path: Implement LRU eviction (max 100K entries), periodically dump/reload from disk

**Concurrent SSE Connections:**
- Current capacity: Each SSE client creates Queue + callback in watcher; no limit on concurrent clients
- Limit: 1000 concurrent SSE = 1000 queues * 8KB+ = 8MB+ overhead; callback list iteration on every log
- Scaling path: Implement connection pool/limit, broadcast instead of per-client callbacks, websocket instead of SSE

**Intruder Detection Memory:**
- Current capacity: `detector.request_history` stores all requests in window per IP
- Limit: 100K IPs × 1000 requests per window = 100M entries; at 16 bytes per tuple = 1.6GB
- Scaling path: Implement circular buffer per IP, limit history to last 100 requests

**Blocklist File Size:**
- Current capacity: `/app/data/blocklist.json` grows with blocked IPs
- Limit: 10K IPs × 200 bytes = 2MB; 100K IPs = 20MB; `write_blocklist_file()` called on every block
- Scaling path: Only write on batched changes (every 100 blocks), archive old blocklist versions

## Dependencies at Risk

**FastAPI Pinned to 0.109.0 (Old):**
- Risk: Security vulnerabilities, missing features; 0.109.0 released Jan 2024, many critical fixes since
- Impact: New CVEs in dependencies like Starlette not patched
- Migration plan: Upgrade to latest 0.11x with testing; breaking changes unlikely in minor versions

**Watchdog 3.0.0 File System Events Unreliable:**
- Risk: Some systems drop file events under high I/O load; events not guaranteed delivery
- Impact: Log watcher could miss lines if Traefik writes faster than watchdog detects
- Migration plan: Add periodic file re-read fallback (every 30 sec read new lines since last position), consider inotify directly on Linux

**httpx Concurrency Pool Not Configured:**
- Risk: Default httpx pool is small; under high load, requests queue and timeout
- Impact: GeoIP/AbuseIPDB calls slow down during traffic spikes
- Migration plan: Configure connection pool limits explicitly: `httpx.AsyncClient(limits=Limits(max_connections=100))`

**SQLAlchemy 2.0.25 Deprecation Warnings:**
- Risk: 2.0 has breaking changes; code using old patterns will fail in 3.0
- Impact: Future upgrade path blocked if not using new API patterns
- Migration plan: Review code for deprecated patterns (e.g., `db.query()` → `db.execute()` with select)

## Missing Critical Features

**No Log Rotation/Cleanup Automation:**
- Problem: Dashboard database grows unbounded; retention cleanup is manual API call only
- Blocks: Can't run long-term without manual intervention; no scheduled cleanup
- Fix: Add APScheduler or systemd timer to call `/api/retention/cleanup` daily

**No Alerting for Database Errors:**
- Problem: Database failures silently drop logs; no notification to operator
- Blocks: Operator won't know logs aren't being collected; false sense of security
- Fix: Add circuit breaker + alert on consecutive database failures

**No Rate Limit on API Endpoints:**
- Problem: Anyone can spam `/api/blocklist`, `/api/abuseipdb/report` causing resource exhaustion
- Blocks: No protection against DoS; auto-reporter could be weaponized to spam AbuseIPDB
- Fix: Implement rate limiting per IP/source

**No Configuration Validation at Startup:**
- Problem: Invalid env vars (bad IP, missing path) don't fail fast
- Blocks: Operator discovers issues after deployment in logs
- Fix: Add explicit validation step in `config.py`, fail with clear error message on startup

**No Health Check Endpoint:**
- Problem: No way to know if dashboard is up (distinct from "responding to requests")
- Blocks: Docker health checks impossible; orchestration can't auto-restart failed container
- Fix: Add `/api/health` endpoint checking database connectivity, log file accessibility

**No Backup/Export of Rules:**
- Problem: If database corrupts, all custom blocklist entries lost
- Blocks: No disaster recovery mechanism
- Fix: Add endpoint to export blocklist + intruder rules, implement periodic backup

## Test Coverage Gaps

**No Unit Tests at All:**
- What's not tested: Every module; no pytest or similar
- Files: All Python files; most critical: `app/blocklist.py`, `app/intruder_detection.py`, `app/log_parser.py`
- Risk: Regressions on every change; edge cases not caught until production
- Priority: **High** - Add test suite for parser, detection, blocklist logic (unit tests), then API endpoints (integration tests)

**No Tests for Malformed Input:**
- What's not tested: What happens with invalid JSON in log, invalid IPs, missing fields, truncated requests
- Files: `app/log_parser.py` (parse_json_log, parse_clf_log, parse_log_line)
- Risk: Edge cases cause crashes or silent data loss
- Priority: **High**

**No Tests for Concurrent Operations:**
- What's not tested: Multiple requests blocking same IP, blocklist writes during reads, event loop edge cases
- Files: `app/blocklist.py`, `app/log_watcher.py`, `app/main.py` API handlers
- Risk: Race conditions, data corruption, only appears under load
- Priority: **High**

**No Integration Tests for External APIs:**
- What's not tested: AbuseIPDB failures, GeoIP rate limiting, Telegram failures, partial network outages
- Files: `app/abuseipdb.py`, `app/geoip.py`, `app/telegram_alerter.py`
- Risk: Cascading failures on API outages; unknown behavior
- Priority: **Medium** - Add tests with mocked responses, test graceful degradation

**No End-to-End Tests:**
- What's not tested: Full pipeline from log line → detection → block → notification
- Files: All
- Risk: Features silently break together (e.g., blocklist written but notification fails)
- Priority: **Medium** - Add basic e2e tests with docker-compose

---

*Concerns audit: 2026-04-11*
