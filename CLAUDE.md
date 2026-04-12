# Traefik Sentinel - Project Documentation

## Overview

Traefik Sentinel is a lightweight security dashboard for Traefik access logs with real-time intruder detection, automatic IP blocking, and AbuseIPDB integration.

**Repository:** https://github.com/sprobst76/traefik-sentinel
**License:** AGPL-3.0
**Language:** English (UI and all messages)

## Tech Stack

- **Backend:** Python 3.11 + FastAPI
- **Frontend:** HTML + HTMX (no build step)
- **Database:** SQLite
- **Log Watching:** Watchdog
- **GeoIP:** ip-api.com (free, no API key)

## Project Structure

```
traefik-sentinel/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI routes + API endpoints
│   ├── config.py            # Configuration from env vars
│   ├── database.py          # SQLite models (SQLAlchemy)
│   ├── log_parser.py        # Traefik JSON log parser
│   ├── log_watcher.py       # File watcher (watchdog)
│   ├── intruder_detection.py # Attack pattern detection
│   ├── security_advisor.py  # Static recommendations
│   ├── ollama_advisor.py    # AI recommendations (optional)
│   ├── telegram_alerter.py  # Telegram notifications
│   ├── abuseipdb.py         # AbuseIPDB integration
│   ├── auto_reporter.py     # Auto-report blocked IPs
│   ├── auto_blocker.py      # Honeypot instant blocking
│   ├── blocklist.py         # IP blocking logic
│   ├── geoip.py             # GeoIP lookups + flags
│   └── retention.py         # Log cleanup
├── templates/
│   └── index.html           # Dashboard (HTMX)
├── static/
│   └── style.css
├── scripts/
│   └── sync-blocklist-ipset.sh  # Firewall sync script
├── data/                    # SQLite DB (gitignored)
├── screenshots/             # UI screenshots
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

## Key Features

1. **Real-time Log Monitoring** - SSE endpoint for live updates
2. **Intruder Detection:**
   - Rate limit violations
   - SQL injection attempts
   - Suspicious path scanning
   - Auth brute-force attacks
3. **Honeypot Paths** - Instant blocking for known malicious paths
4. **AbuseIPDB Integration:**
   - Check IP reputation
   - Auto-report blocked IPs
5. **GeoIP Display** - Country flags for all IPs
6. **Telegram Alerts** - Severity-based notifications
7. **IP Blocklist** - Manual + automatic, CIDR support
8. **Firewall Sync** - ipset integration script

## Configuration

All config via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `TRAEFIK_LOG_DIR` | `/var/log/traefik` | Log directory |
| `PORT` | `13923` | Dashboard port |
| `TELEGRAM_BOT_TOKEN` | - | Telegram bot token |
| `TELEGRAM_CHAT_ID` | - | Telegram chat ID |
| `ABUSEIPDB_API_KEY` | - | AbuseIPDB API key |
| `ABUSEIPDB_AUTO_REPORT` | `true` | Auto-report blocked IPs |
| `HONEYPOT_INSTANT_BLOCK` | `true` | Instant block honeypots |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stats` | GET | Overall statistics |
| `/api/stats/ips` | GET | Top IPs with risk assessment |
| `/api/stats/hosts` | GET | Requests per host |
| `/api/intruders` | GET | Intruder events |
| `/api/blocklist` | GET/POST | Blocklist management |
| `/api/blocklist/{ip}` | DELETE | Unblock IP |
| `/api/blocklist/export` | GET | Export blocklist (plain text) |
| `/api/abuseipdb/check/{ip}` | GET | Check IP reputation |
| `/api/stream` | GET | SSE live log stream |

## Deployment

### Production (this server)
- **Location:** `/srv/ai-lab/traefik-dashboard/`
- **Container:** `traefik-dashboard`
- **Port:** 13923
- **Logs:** `/srv/ai-lab/logs/traefik/access.log`

### Commands
```bash
# Restart
cd /srv/ai-lab/traefik-dashboard && docker compose restart

# View logs
docker logs -f traefik-dashboard

# Rebuild
docker compose up -d --build
```

## Recent Changes (2024-02)

1. **English Translation** - Complete UI and backend translation
2. **Enhanced Telegram Alerts** - Severity levels (critical/high/medium)
3. **GeoIP Integration** - Country flags via ip-api.com
4. **Auto-Report** - Automatic AbuseIPDB reporting on block
5. **GitHub Release** - Public repo with screenshots

## Database

SQLite at `data/dashboard.db`:
- `access_logs` - All parsed log entries
- `intruder_events` - Detected attacks with recommendations
- `blocked_ips` - Blocklist with expiry

Note: Old German recommendations remain in DB until new events generate English ones.

## Development Notes

- Screenshots in README are German (note added)
- No secrets in repo - all via env vars
- `.env` is gitignored
- Default paths changed to generic `/var/log/traefik/`

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Traefik Sentinel**

A lightweight security dashboard for Traefik reverse proxy access logs with real-time intruder detection, automatic IP blocking, AbuseIPDB integration, and Telegram alerting. Built for self-hosters who want to monitor and protect their services without heavy infrastructure.

**Core Value:** Detect and block malicious traffic automatically while keeping the operator informed without overwhelming them with noise.

### Constraints

- **Tech stack**: Python 3.11 + FastAPI + SQLite + HTMX — no changes to stack
- **Deployment**: Docker container, all config via environment variables
- **Backwards compatible**: Existing Telegram config (BOT_TOKEN, CHAT_ID) must continue to work
- **No external dependencies**: No new services or databases required
- **Language**: All code and messages in English
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.11 - Backend REST API and log processing
- HTML - Dashboard templates (templates/index.html)
- CSS - Frontend styling (static/style.css)
- JavaScript - HTMX for dynamic UI without build step
## Runtime
- Python 3.11 (slim Docker image)
- pip
- Lockfile: `requirements.txt`
## Frameworks
- FastAPI 0.109.0 - REST API framework
- Uvicorn[standard] 0.27.0 - ASGI server
- Jinja2 3.1.3 - HTML template rendering
- HTMX - No-build dynamic UI enhancements
- SQLAlchemy 2.0.25 - ORM for database operations
- aiosqlite 0.19.0 - Async SQLite support
- Watchdog 3.0.0 - Monitor Traefik log files for changes
- httpx 0.26.0 - Async HTTP client for external APIs
- python-dotenv 1.0.0 - Load environment variables from .env
## Key Dependencies
- FastAPI 0.109.0 - Core web framework for REST API
- SQLAlchemy 2.0.25 - Database ORM and query building
- Watchdog 3.0.0 - Log file monitoring for real-time updates
- httpx 0.26.0 - Async HTTP calls to external services (AbuseIPDB, Telegram, GeoIP)
- Uvicorn 0.27.0 - Production-grade ASGI server
- aiosqlite 0.19.0 - Async database access
## Configuration
- Managed via environment variables in `.env` file
- Configuration loaded via `python-dotenv`
- All critical configs can be overridden at runtime
- `TRAEFIK_LOG_DIR` - Path to Traefik access logs
- `PORT` - Dashboard port (default: 13923)
- `TELEGRAM_BOT_TOKEN` - Telegram notification bot
- `TELEGRAM_CHAT_ID` - Telegram destination chat
- `ABUSEIPDB_API_KEY` - AbuseIPDB API credentials
- `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS` - Detection thresholds
- `AUTH_FAILURE_THRESHOLD`, `AUTH_FAILURE_WINDOW_SECONDS` - Brute-force thresholds
- `HONEYPOT_INSTANT_BLOCK` - Auto-block honeypot access
- `RETENTION_ACCESS_LOGS_DAYS`, `RETENTION_INTRUDER_EVENTS_DAYS`, `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` - Data cleanup policies
- `Dockerfile` - Multi-stage Python 3.11 container
- `docker-compose.yml` - Volume mounts for logs and database
## Platform Requirements
- Python 3.11+
- pip for dependency management
- Access to Traefik log file (watch mode)
- Docker and Docker Compose
- Read-only access to Traefik access log file: `/var/log/traefik/access.log`
- Optional: Telegram bot token (from @BotFather)
- Optional: AbuseIPDB API key (free tier available at abuseipdb.com)
- Optional: External GeoIP service (ip-api.com, free tier)
## Database
- Location: `data/dashboard.db` (in container at `/app/data/dashboard.db`)
- No external database server required
- Persistent volume mount: `./data:/app/data`
- `access_logs` - Parsed Traefik log entries
- `intruder_events` - Detected attack events
- `blocked_ips` - IP blocklist with expiry and CIDR support
## Containerization
- Base image: `python:3.11-slim`
- Exposed port: 13923
- Restart policy: `unless-stopped`
- Health check: HTTP GET to `/api/stats`
- `./data:/app/data` - SQLite database persistence
- `${TRAEFIK_LOG_DIR}:/logs:ro` - Read-only access to Traefik logs
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Lowercase with underscores: `log_parser.py`, `intruder_detection.py`, `telegram_alerter.py`
- Module names match their primary responsibility
- Constants in ALL_CAPS in config files
- Lowercase with underscores: `resolve_ip()`, `_read_new_lines()`, `check_suspicious_path()`
- Private/internal functions prefixed with underscore: `_is_whitelisted()`, `_should_alert()`, `_clean_old_entries()`
- Async functions follow same naming convention: `send_telegram_alert()`, `lookup_batch()`
- Verb-first naming for actions: `check_*`, `parse_*`, `block_*`, `analyze_*`
- Lowercase with underscores: `request_history`, `auth_failures`, `alert_cooldown`
- Single-letter variables only in loops: `for r in results:`, `for b in blocks:`
- Caching variables: `_ip_cache`, `_geoip_cache`, `_batch_queue`
- PascalCase: `IntruderDetector`, `LogFileHandler`, `LogWatcher`
- SQLAlchemy models use descriptive names: `AccessLog`, `IntruderEvent`, `BlockedIP`
- ALL_CAPS in modules: `RATE_LIMIT_REQUESTS`, `HONEYPOT_PATHS`, `THREAT_SEVERITY`
- Grouped with related constants in config or module top
- Dictionary constants for configuration: `CATEGORIES`, `RECOMMENDATIONS`, `THREAT_SEVERITY`, `BLOCK_DURATIONS`
## Code Style
- No explicit formatter/linter configured (review requirements.txt)
- Standard Python style observed: 4-space indentation
- Line length varies (no strict limit observed)
- Two blank lines between top-level definitions
- Imports organized but no strict grouping enforced
- Standard library imports first (asyncio, os, json, re, datetime, etc.)
- Third-party frameworks (fastapi, sqlalchemy, httpx, watchdog)
- Local app imports: `from app.config import`, `from app.database import`
- Path aliases not used; relative imports within `app/` module
- No .eslintrc, .flake8, .black, or pylint config files present
- Code generally follows PEP 8 conventions by observation
- No pre-commit hooks or formatting automation detected
## Error Handling
- No custom exception classes defined
- Uses built-in exceptions: `ValueError`, `FileNotFoundError`, `json.JSONDecodeError`
- No exception chaining or nested custom error types
## Logging
- Error logs: `print(f"Error reading log file: {e}")`
- Migration logs: `print(f"Migration: Added column {col_name}")`
- Event logs: `print(f"GeoIP lookup failed for {ip}: {e}")`
- External API failures: GeoIP lookups, Telegram sends, AbuseIPDB checks
- File operations: Log reading errors, file not found
- Database migration issues
- Auto-blocking decisions (optional, via notifications instead)
## Comments
- Complex detection logic with multiple conditions
- Non-obvious algorithmic choices (rate limit windows, caching TTLs)
- Module-level docstrings explaining purpose
- Minimal docstrings on functions
- Module docstrings common: `"""GeoIP lookup module using ip-api.com..."""` (geoip.py:1-3)
- Function docstrings present but brief: `"""Reverse DNS lookup for IP address. Cached."""` (main.py:19)
- Type hints used: `def lookup_batch(ips: list[str]) -> dict[str, dict]:`
## Function Design
- Detection checks: `check_suspicious_path()` (20 lines)
- Parsing: `parse_json_log()` (40 lines, but data extraction)
- Complex analysis: `get_top_ips()` (80 lines, but endpoint with query building)
- Explicit parameters preferred
- Database operations pass `db: Session`
- Optional parameters with defaults: `send_alert(message: str, parse_mode: str = "Markdown")`
- Type hints consistently used: `def block_ip(db: Session, ip: str, reason: str = None, ...) -> dict:`
- Consistent return types: functions return either Dict, Optional[Dict], or None
- API endpoints return Dict for JSON serialization
- Parsing functions return dataclass instances or None: `Optional[ParsedLog]`
- Database operations return success indicators: `{"success": True, ...}`
## Module Design
- All public functions exported at module level
- Global detector instance pattern: `detector = IntruderDetector()` at module level (intruder_detection.py:195)
- Wrapper functions for async: `def send_alert_sync(event: dict)` (telegram_alerter.py:113)
- Not used; each module imported directly
- Example: `from app.log_parser import parse_log_line` not `from app import parse_log_line`
- `config.py`: All configuration and constants
- `database.py`: SQLAlchemy models and session management
- `log_parser.py`: JSON/CLF log parsing
- `intruder_detection.py`: Attack pattern detection (class-based detector)
- `blocklist.py`: IP blocking logic and CIDR management
- `telegram_alerter.py`: Telegram notification sending
- `geoip.py`: GeoIP lookups with caching
- `abuseipdb.py`: AbuseIPDB API integration
- `security_advisor.py`: Static recommendation strings
- `log_watcher.py`: File watching and event processing
- `auto_blocker.py`: Decision logic for automatic IP blocks
- `main.py`: FastAPI routes and REST endpoints
## Type Hints
- Function parameters: `def check_ip(ip: str) -> Optional[dict]:`
- Dataclass fields: `@dataclass class ParsedLog: timestamp: datetime`
- Type unions: `list[str]`, `dict[str, dict]`, `tuple[bool, Optional[...]]`
- SQLAlchemy Column types: `Column(String(45), Integer, DateTime)`
## Caching Patterns
- `_geoip_cache: dict[str, tuple[datetime, dict]]` (geoip.py:12)
- `_ip_cache: dict[str, tuple[datetime, dict]]` (abuseipdb.py:13)
- `_abuse_check_cache: dict[str, tuple[datetime, dict]]` (auto_blocker.py:19)
## Dataclasses
## Decorators
- `@lru_cache(maxsize=1000)`: DNS lookup caching (main.py:17)
- `@asynccontextmanager`: FastAPI lifespan management (main.py:27)
- `@app.get()`, `@app.post()`, `@app.delete()`: FastAPI route decorators
- SQLAlchemy table metadata: `__tablename__`, `__table_args__`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Real-time Traefik access log processing via file watching
- Multi-stage threat detection pipeline (path scanning, SQL injection, rate limiting, auth brute force)
- Stateful in-memory pattern tracking (request history, auth failures)
- Automatic IP blocking with duration-based logic and AbuseIPDB integration
- Async event dispatch for notifications and external API calls
- Honeypot fast-path with instant blocking
## Layers
- Purpose: Dashboard UI for monitoring and manual controls
- Location: `templates/index.html`, `static/style.css`
- Contains: HTML template with HTMX for dynamic updates, status displays, IP tables, live log streaming
- Depends on: FastAPI REST API
- Used by: System administrators and operators
- Purpose: REST endpoints for data retrieval and manual operations
- Location: `app/main.py` (lines 44-804)
- Contains: FastAPI route handlers for stats, intruders, blocklist, AbuseIPDB checks, retention management, live streaming
- Depends on: Database, GeoIP, AbuseIPDB, Telegram services
- Used by: Frontend, external integrations, manual administration
- Purpose: Core security logic, threat detection, blocking decisions
- Location: `app/intruder_detection.py`, `app/blocklist.py`, `app/auto_blocker.py`, `app/security_advisor.py`, `app/abuseipdb.py`
- Contains: Threat pattern analysis, block duration calculation, abuse score evaluation, auto-blocking heuristics
- Depends on: Database, external threat intelligence (AbuseIPDB)
- Used by: Log watcher, API handlers
- Purpose: Parse and prepare access logs for analysis
- Location: `app/log_parser.py`, `app/log_watcher.py`
- Contains: Traefik JSON/CLF format parsers, file system watching via watchdog, line-by-line event dispatch
- Depends on: File system, Database
- Used by: Main application, pattern detection
- Purpose: Persistence and state management
- Location: `app/database.py`
- Contains: SQLAlchemy ORM models (AccessLog, IntruderEvent, BlockedIP), connection pooling, migrations
- Depends on: SQLite
- Used by: All application logic layers
- Purpose: Third-party API interactions
- Location: `app/geoip.py`, `app/abuseipdb.py`, `app/telegram_alerter.py`, `app/auto_reporter.py`
- Contains: GeoIP lookups (ip-api.com), AbuseIPDB reputation checks and reporting, Telegram notifications
- Depends on: httpx (async HTTP client), environment configuration
- Used by: API handlers, auto-blocker, log processor
- Purpose: Centralized environment variable and threshold management
- Location: `app/config.py`
- Contains: Detection thresholds, paths, whitelists, API keys, retention policies
- Depends on: Environment
- Used by: All layers
## Data Flow
- **In-Memory:** Request history, auth failures per IP, alert cooldown map, GeoIP cache (all in respective modules)
- **Database:** All logs, events, and blocklist entries (durable state)
- **Cache Files:** `blocklist.json`, `blocklist.ipset` (for external firewall sync)
- **GeoIP Cache:** 24-hour TTL, 100-IP batch API for efficiency
## Key Abstractions
- Purpose: Normalized access log representation
- Examples: `app/log_parser.py:9-25`
- Pattern: Immutable dataclass, supports both JSON and CLF formats, stores all Traefik fields
- Purpose: Security threat detection record
- Examples: `app/database.py:42-55`
- Pattern: SQLAlchemy mapped class with timestamp indexing, stores IP, attack reason, details, recommendation
- Purpose: IP blocklist with smart duration and reporting
- Examples: `app/database.py:57-70`
- Pattern: SQLAlchemy mapped class, supports both single IPs and CIDR ranges, tracks block count, abuse score, auto-block flag
- Purpose: In-memory pattern matching state machine
- Examples: `app/intruder_detection.py:18-201`
- Pattern: Maintains request/auth failure history per IP, alert cooldown map, implements four independent check methods
- Purpose: Risk scoring for IPs
- Examples: `app/main.py:195-243`
- Pattern: Multi-factor scoring (error rate, intruder events, scanning behavior) → risk_level enum
- Purpose: Context-aware expiration times
- Examples: `app/blocklist.py:74-100`
- Pattern: Reason-based lookup table, override by abuse score, permanent for repeat offenders
## Entry Points
- Location: `app/main.py:28-34` (lifespan context manager)
- Triggers: FastAPI lifecycle event
- Responsibilities: Initialize database, start log watcher, mount static files
- Location: `app/log_watcher.py:76-153` (LogWatcher.process_line)
- Triggers: File modification event detected by watchdog
- Responsibilities: Parse, persist, detect, alert, schedule auto-block
- Location: `app/main.py:44-47`
- Triggers: GET /
- Responsibilities: Serve HTML template with JavaScript
- Location: `app/main.py:760-803`
- Triggers: GET /api/stream (Server-Sent Events)
- Responsibilities: Queue log entries, push to connected clients
- Location: `app/main.py:465-510`
- Triggers: POST /api/blocklist
- Responsibilities: Validate input, block IP, optionally report to AbuseIPDB
## Error Handling
- Log watcher: Try/except around file operations, continues on parse errors
- GeoIP lookups: Async operations with 5-10s timeout, returns empty dict on failure
- AbuseIPDB: Async with timeout, returns None on failure, auto-block skipped if unavailable
- Telegram: Caught exception, continues log processing if notification fails
- Database: Try/finally ensures session close, rollback on error
## Cross-Cutting Concerns
- IP/CIDR parsing with `ipaddress` module (strict validation)
- Status code integer bounds checking
- Path length truncation (max 100 chars in some APIs)
- API endpoints are unauthenticated (assumes private network or firewall)
- Telegram and AbuseIPDB use API key environment variables
- Honeypot path check is synchronous, instant (no rate limit on checking)
- AbuseIPDB check has 60-minute cache per IP to respect API quota
- GeoIP batch API respects 100-IP limit, 45 req/min rate limit with 0.5s delays
- Log watcher runs in background thread (watchdog Observer)
- API handlers async (FastAPI), share database session factory
- Auto-blocking scheduled as async tasks via `asyncio.create_task()`
- In-memory state structures (request_history, auth_failures) not thread-safe; acceptable because updates are additive and cooldown is forgiving
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
