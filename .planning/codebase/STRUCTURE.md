# Codebase Structure

**Analysis Date:** 2026-04-11

## Directory Layout

```
traefik-sentinel/
├── app/                        # Python application package
│   ├── __init__.py            # Empty init file
│   ├── main.py                # FastAPI application and all HTTP routes
│   ├── config.py              # Environment variables and configuration constants
│   ├── database.py            # SQLAlchemy ORM models and migrations
│   ├── log_parser.py          # Traefik log parsing (JSON and CLF formats)
│   ├── log_watcher.py         # Watchdog-based file monitoring
│   ├── intruder_detection.py  # Threat pattern detection logic
│   ├── blocklist.py           # IP blocking, CIDR support, duration calculation
│   ├── auto_blocker.py        # Automatic blocking based on AbuseIPDB scores
│   ├── auto_reporter.py       # AbuseIPDB reporting
│   ├── abuseipdb.py           # AbuseIPDB API integration
│   ├── geoip.py               # GeoIP lookups via ip-api.com
│   ├── telegram_alerter.py    # Telegram notification dispatch
│   ├── security_advisor.py    # Static security recommendations
│   └── ollama_advisor.py      # Optional AI recommendations (not used by default)
├── templates/
│   └── index.html             # Single-page dashboard using HTMX
├── static/
│   ├── style.css              # Dashboard styling
│   └── favicon.svg            # Traefik Sentinel icon
├── scripts/
│   └── sync-blocklist-ipset.sh # Firewall sync script for ipset integration
├── data/                       # SQLite database directory (gitignored, created at runtime)
│   └── dashboard.db           # SQLite database
├── .env.example               # Environment variable template
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container image definition
├── docker-compose.yml         # Local development setup
├── README.md                  # Project documentation
├── CLAUDE.md                  # Project instructions and deployment notes
├── LICENSE                    # AGPL-3.0 license
└── .gitignore                 # Standard Python + data exclusions
```

## Directory Purposes

**app/:**
- Purpose: Core Python application source code
- Contains: FastAPI routes, ORM models, log parsing, threat detection, blocking logic, external integrations
- Key files: `main.py` (routes), `intruder_detection.py` (core logic), `blocklist.py` (IP management), `database.py` (persistence)

**templates/:**
- Purpose: Server-side rendered HTML dashboard
- Contains: Single `index.html` with HTMX markup for dynamic updates, no template variables (only client-side JavaScript)
- Key files: `index.html` (~600 lines of markup, styles inline via class names)

**static/:**
- Purpose: Client-side assets (CSS, images)
- Contains: `style.css` (dashboard styling), `favicon.svg` (icon)
- Key files: `style.css` (grid layout, tabs, tables, real-time streaming indicators)

**scripts/:**
- Purpose: Utility scripts for external integration
- Contains: Shell script for firewall ipset synchronization
- Key files: `sync-blocklist-ipset.sh` (reads `data/blocklist.ipset`, applies to iptables)

**data/:**
- Purpose: Runtime data storage (gitignored)
- Contains: SQLite database, blocklist exports
- Key files: `dashboard.db` (created at startup), `blocklist.json` (auto-exported), `blocklist.ipset` (firewall format)

## Key File Locations

**Entry Points:**
- `app/main.py`: Main FastAPI application (ASGI entry point)
- `app/main.py:37`: FastAPI instance created with lifespan hook
- `app/main.py:806-808`: Uvicorn startup for local testing

**Configuration:**
- `app/config.py`: All environment variables, detection thresholds, suspicious paths, honeypot paths
- `.env.example`: Template for required/optional variables

**Core Logic:**
- `app/intruder_detection.py`: Threat pattern detection (4 checks: suspicious path, SQL injection, rate limit, auth failures)
- `app/blocklist.py`: IP blocking with smart duration, CIDR support, repeat offender detection
- `app/auto_blocker.py`: Auto-blocking decision heuristics with AbuseIPDB score caching
- `app/log_parser.py`: Traefik log format parsing (both JSON and CLF)

**Testing/Development:**
- No test files in codebase (no unit tests committed)
- `Dockerfile`: Container image definition (Python 3.11, pip install requirements.txt)
- `docker-compose.yml`: Local dev setup with volume mount for logs

## Naming Conventions

**Files:**
- Module files: `snake_case.py` (e.g., `log_watcher.py`, `intruder_detection.py`)
- Templates: Descriptive lowercase (e.g., `index.html`)
- Static files: Lowercase with extension (e.g., `style.css`, `favicon.svg`)
- Shell scripts: Hyphenated descriptive (e.g., `sync-blocklist-ipset.sh`)

**Functions:**
- Async functions: Prefixed `async def` (e.g., `async def send_telegram_alert()`)
- Sync wrappers: Suffixed `_sync` (e.g., `send_alert_sync()`, `report_ip_sync()`)
- Private functions: Prefixed `_` (e.g., `_read_new_lines()`, `_is_whitelisted()`)
- Main entry point: `main.py`

**Variables:**
- Module singletons: PascalCase (e.g., `LogWatcher`, `IntruderDetector`)
- Global instances: lowercase (e.g., `watcher`, `detector`)
- Dataclasses: PascalCase (e.g., `ParsedLog`)
- ORM models: PascalCase (e.g., `AccessLog`, `IntruderEvent`, `BlockedIP`)
- Constants: UPPER_SNAKE_CASE (e.g., `RATE_LIMIT_REQUESTS`, `HONEYPOT_PATHS`)
- Configuration values: UPPER_SNAKE_CASE (e.g., `DATABASE_PATH`, `TELEGRAM_ENABLED`)

**Classes:**
- ORM models: Plural table name convention (e.g., `AccessLog` → `access_logs`)
- Detector: Suffix `Detector` (e.g., `IntruderDetector`)
- Event handler: Suffix `Handler` (e.g., `LogFileHandler`)
- Handler/watcher: `LogWatcher`

## Where to Add New Code

**New Feature (e.g., new detection rule):**
- Primary code: `app/intruder_detection.py`
  - Add method to `IntruderDetector` class (e.g., `check_new_pattern()`)
  - Add to `analyze()` checks list
  - Add pattern constants to `app/config.py` if configurable
- Recommendations: Update `app/security_advisor.py` with RECOMMENDATIONS dict entry
- Tests: Create `test_intruder_detection.py` (not currently in repo, add to root)

**New External Integration (e.g., new alerting service):**
- Primary code: Create `app/new_service.py` module
- Configuration: Add env vars and toggles to `app/config.py`
- Entry point: Add handler call from relevant dispatcher:
  - For log events: call from `log_watcher.process_line()`
  - For blocking events: call from `auto_blocker.notify_auto_block()` or `blocklist.block_ip()`
- Pattern: Use async function + sync wrapper (see `telegram_alerter.py` for pattern)

**New API Endpoint:**
- Location: `app/main.py`
- Pattern: Use `@app.get()` or `@app.post()` decorator, Session-based database access
- Query params: Use `Query()` for validation
- Response: Return dict or Pydantic model
- Database: Open SessionLocal, try/finally with close

**New Dashboard Widget/Tab:**
- HTML: Update `templates/index.html`
- Styling: Add CSS to `static/style.css`
- API endpoint: Create corresponding route in `app/main.py`
- JavaScript: Add fetch/HTMX calls in index.html script section

**New Configuration:**
- Location: `app/config.py` at appropriate section
- Pattern: `os.getenv("VAR_NAME", default_value)`
- Type: Validate/convert (int, bool, str.split() for lists)
- Document: Add to `.env.example`

## Special Directories

**data/:**
- Purpose: Runtime-generated state and database
- Generated: Yes (created by application at startup)
- Committed: No (.gitignore excludes)
- Content:
  - `dashboard.db`: SQLite database (main state store)
  - `blocklist.json`: JSON export of active blocklist (for external tools)
  - `blocklist.ipset`: ipset restore format (for firewall integration)

**.planning/:**
- Purpose: GSD planning and documentation
- Generated: No (manually created during analysis)
- Committed: Yes (tracking across planning phases)
- Content: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md, etc.

**screenshots/:**
- Purpose: UI documentation and README assets
- Generated: No (manually created/committed)
- Committed: Yes
- Content: PNG images of dashboard (German language, noted in README)

## Module Dependencies

**app/main.py (414 lines)** depends on:
- `app.config` (HOST, PORT, logging paths)
- `app.database` (SessionLocal, models)
- `app.log_watcher` (watcher singleton, callbacks)
- `app.geoip` (lookup_batch, country_code_to_flag)
- `app.security_advisor` (get_recommendation)
- `app.blocklist` (block_ip, unblock_ip, cleanup_expired_blocks)
- `app.abuseipdb` (check_ip, report_ip, is_configured)

**app/log_watcher.py (183 lines)** depends on:
- `app.config` (LOG_PATH)
- `app.log_parser` (parse_log_line)
- `app.database` (SessionLocal, AccessLog, IntruderEvent)
- `app.intruder_detection` (analyze_log)
- `app.telegram_alerter` (send_alert_sync)
- `app.auto_blocker` (check_and_block_honeypot, process_intruder_event)

**app/intruder_detection.py (201 lines)** depends on:
- `app.config` (thresholds, paths, whitelists)
- `app.log_parser` (ParsedLog)

**app/blocklist.py (332 lines)** depends on:
- `app.database` (BlockedIP)
- `app.auto_reporter` (report_ip_sync)

**app/auto_blocker.py (261 lines)** depends on:
- `app.database` (SessionLocal, IntruderEvent, BlockedIP)
- `app.blocklist` (block_ip, is_ip_blocked_by_cidr, ABUSE_SCORE_*)
- `app.abuseipdb` (check_ip, is_configured)
- `app.config` (HONEYPOT_*, WHITELISTED_IPS)
- `app.telegram_alerter` (send_alert)

---

*Structure analysis: 2026-04-11*
