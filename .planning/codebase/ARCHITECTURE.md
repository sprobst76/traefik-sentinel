# Architecture

**Analysis Date:** 2026-04-11

## Pattern Overview

**Overall:** Event-driven security monitoring pipeline with real-time log streaming, pattern detection, and automatic threat response.

**Key Characteristics:**
- Real-time Traefik access log processing via file watching
- Multi-stage threat detection pipeline (path scanning, SQL injection, rate limiting, auth brute force)
- Stateful in-memory pattern tracking (request history, auth failures)
- Automatic IP blocking with duration-based logic and AbuseIPDB integration
- Async event dispatch for notifications and external API calls
- Honeypot fast-path with instant blocking

## Layers

**Presentation Layer:**
- Purpose: Dashboard UI for monitoring and manual controls
- Location: `templates/index.html`, `static/style.css`
- Contains: HTML template with HTMX for dynamic updates, status displays, IP tables, live log streaming
- Depends on: FastAPI REST API
- Used by: System administrators and operators

**HTTP API Layer:**
- Purpose: REST endpoints for data retrieval and manual operations
- Location: `app/main.py` (lines 44-804)
- Contains: FastAPI route handlers for stats, intruders, blocklist, AbuseIPDB checks, retention management, live streaming
- Depends on: Database, GeoIP, AbuseIPDB, Telegram services
- Used by: Frontend, external integrations, manual administration

**Application/Domain Logic Layer:**
- Purpose: Core security logic, threat detection, blocking decisions
- Location: `app/intruder_detection.py`, `app/blocklist.py`, `app/auto_blocker.py`, `app/security_advisor.py`, `app/abuseipdb.py`
- Contains: Threat pattern analysis, block duration calculation, abuse score evaluation, auto-blocking heuristics
- Depends on: Database, external threat intelligence (AbuseIPDB)
- Used by: Log watcher, API handlers

**Log Processing Layer:**
- Purpose: Parse and prepare access logs for analysis
- Location: `app/log_parser.py`, `app/log_watcher.py`
- Contains: Traefik JSON/CLF format parsers, file system watching via watchdog, line-by-line event dispatch
- Depends on: File system, Database
- Used by: Main application, pattern detection

**Data Layer:**
- Purpose: Persistence and state management
- Location: `app/database.py`
- Contains: SQLAlchemy ORM models (AccessLog, IntruderEvent, BlockedIP), connection pooling, migrations
- Depends on: SQLite
- Used by: All application logic layers

**External Integration Layer:**
- Purpose: Third-party API interactions
- Location: `app/geoip.py`, `app/abuseipdb.py`, `app/telegram_alerter.py`, `app/auto_reporter.py`
- Contains: GeoIP lookups (ip-api.com), AbuseIPDB reputation checks and reporting, Telegram notifications
- Depends on: httpx (async HTTP client), environment configuration
- Used by: API handlers, auto-blocker, log processor

**Configuration Layer:**
- Purpose: Centralized environment variable and threshold management
- Location: `app/config.py`
- Contains: Detection thresholds, paths, whitelists, API keys, retention policies
- Depends on: Environment
- Used by: All layers

## Data Flow

**Inbound Log Processing:**

1. `log_watcher.LogWatcher` (singleton) watches `TRAEFIK_LOG_PATH` using watchdog
2. On file modification, `_read_new_lines()` reads since last position
3. For each new line:
   - `log_parser.parse_log_line()` converts JSON/CLF to `ParsedLog` dataclass
   - `check_and_block_honeypot()` performs instant blocking if path matches honeypot
   - Log entry persisted to `AccessLog` table
   - `intruder_detection.analyze_log()` runs pattern checks → `IntruderEvent` table if triggered
   - If event detected, `telegram_alerter.send_alert_sync()` dispatches notification
   - If blocking needed, `auto_blocker.process_intruder_event()` scheduled asynchronously
   - All callbacks in `watcher.new_log_callbacks` invoked (for live streaming)

**Threat Detection Pipeline:**

1. `IntruderDetector.analyze(log)` runs four independent checks:
   - `check_suspicious_path()`: Path prefix/filename matching vs `SUSPICIOUS_PATHS`, `SUSPICIOUS_FILES`
   - `check_sql_injection()`: Regex patterns from `SQL_INJECTION_PATTERNS`
   - `check_rate_limit()`: Sliding window request counting per IP
   - `check_auth_failures()`: Count 401/403 responses per IP in time window
2. Each check maintains in-memory state: `request_history` dict and `auth_failures` dict
3. Cooldown logic prevents re-alerting same IP/reason within 15 minutes
4. For each matched check, event dict created and returned

**Auto-Blocking Decision Flow:**

1. `auto_blocker.should_auto_block(ip, reason, event_count)` called for each intruder event
2. Checks AbuseIPDB reputation (cached, configurable cooldown):
   - High priority reasons (SQL injection, suspicious path) always check
   - Multiple events within 24h trigger check
   - Cache TTL: 60 minutes
3. Scoring:
   - Score ≥ 50%: Auto-block
   - Score ≥ 80%: Permanent block
   - Repeat offender (3+ blocks): Permanent
4. If decision is block:
   - `blocklist.block_ip()` writes to `BlockedIP` table and exports to `blocklist.json`
   - `auto_reporter.report_ip_sync()` sends report to AbuseIPDB if configured
   - Notification sent via Telegram

**API Request Flow:**

1. GET `/api/stats/{hours}` → Count/aggregate `AccessLog` entries
2. GET `/api/intruders/{hours}` → Query `IntruderEvent`, group by IP, batch GeoIP lookups
3. GET `/api/stats/ips` → Join `AccessLog`, `IntruderEvent`, `BlockedIP`; calculate risk scores; batch GeoIP
4. GET `/api/stream` → SSE generator subscribes to `watcher.new_log_callbacks`, yields updates
5. POST `/api/blocklist` → Validates IP/CIDR, calls `blocklist.block_ip()`, optionally reports to AbuseIPDB
6. DELETE `/api/blocklist/{ip}` → Deactivates block, exports updated list

**State Management:**

- **In-Memory:** Request history, auth failures per IP, alert cooldown map, GeoIP cache (all in respective modules)
- **Database:** All logs, events, and blocklist entries (durable state)
- **Cache Files:** `blocklist.json`, `blocklist.ipset` (for external firewall sync)
- **GeoIP Cache:** 24-hour TTL, 100-IP batch API for efficiency

## Key Abstractions

**ParsedLog (dataclass):**
- Purpose: Normalized access log representation
- Examples: `app/log_parser.py:9-25`
- Pattern: Immutable dataclass, supports both JSON and CLF formats, stores all Traefik fields

**IntruderEvent (ORM model):**
- Purpose: Security threat detection record
- Examples: `app/database.py:42-55`
- Pattern: SQLAlchemy mapped class with timestamp indexing, stores IP, attack reason, details, recommendation

**BlockedIP (ORM model):**
- Purpose: IP blocklist with smart duration and reporting
- Examples: `app/database.py:57-70`
- Pattern: SQLAlchemy mapped class, supports both single IPs and CIDR ranges, tracks block count, abuse score, auto-block flag

**IntruderDetector (stateful singleton):**
- Purpose: In-memory pattern matching state machine
- Examples: `app/intruder_detection.py:18-201`
- Pattern: Maintains request/auth failure history per IP, alert cooldown map, implements four independent check methods

**Threat Level Calculation:**
- Purpose: Risk scoring for IPs
- Examples: `app/main.py:195-243`
- Pattern: Multi-factor scoring (error rate, intruder events, scanning behavior) → risk_level enum

**Block Duration Logic:**
- Purpose: Context-aware expiration times
- Examples: `app/blocklist.py:74-100`
- Pattern: Reason-based lookup table, override by abuse score, permanent for repeat offenders

## Entry Points

**Application Startup:**
- Location: `app/main.py:28-34` (lifespan context manager)
- Triggers: FastAPI lifecycle event
- Responsibilities: Initialize database, start log watcher, mount static files

**Log Processing:**
- Location: `app/log_watcher.py:76-153` (LogWatcher.process_line)
- Triggers: File modification event detected by watchdog
- Responsibilities: Parse, persist, detect, alert, schedule auto-block

**API Dashboard:**
- Location: `app/main.py:44-47`
- Triggers: GET /
- Responsibilities: Serve HTML template with JavaScript

**Real-Time Streaming:**
- Location: `app/main.py:760-803`
- Triggers: GET /api/stream (Server-Sent Events)
- Responsibilities: Queue log entries, push to connected clients

**Manual IP Blocking:**
- Location: `app/main.py:465-510`
- Triggers: POST /api/blocklist
- Responsibilities: Validate input, block IP, optionally report to AbuseIPDB

## Error Handling

**Strategy:** Fail-safe with logging. External dependency failures do not block core logging/detection.

**Patterns:**
- Log watcher: Try/except around file operations, continues on parse errors
- GeoIP lookups: Async operations with 5-10s timeout, returns empty dict on failure
- AbuseIPDB: Async with timeout, returns None on failure, auto-block skipped if unavailable
- Telegram: Caught exception, continues log processing if notification fails
- Database: Try/finally ensures session close, rollback on error

## Cross-Cutting Concerns

**Logging:** Print statements to stdout (suitable for Docker logs), no structured logging framework

**Validation:** 
- IP/CIDR parsing with `ipaddress` module (strict validation)
- Status code integer bounds checking
- Path length truncation (max 100 chars in some APIs)

**Authentication:** 
- API endpoints are unauthenticated (assumes private network or firewall)
- Telegram and AbuseIPDB use API key environment variables

**Rate Limiting (internal):**
- Honeypot path check is synchronous, instant (no rate limit on checking)
- AbuseIPDB check has 60-minute cache per IP to respect API quota
- GeoIP batch API respects 100-IP limit, 45 req/min rate limit with 0.5s delays

**Concurrency:**
- Log watcher runs in background thread (watchdog Observer)
- API handlers async (FastAPI), share database session factory
- Auto-blocking scheduled as async tasks via `asyncio.create_task()`
- In-memory state structures (request_history, auth_failures) not thread-safe; acceptable because updates are additive and cooldown is forgiving

---

*Architecture analysis: 2026-04-11*
