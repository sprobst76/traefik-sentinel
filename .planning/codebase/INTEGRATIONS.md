# External Integrations

**Analysis Date:** 2026-04-11

## APIs & External Services

**GeoIP Lookup:**
- Service: ip-api.com
  - What it's used for: Reverse geolocation for IP addresses (country, city, ISP, ASN)
  - SDK/Client: httpx (async HTTP)
  - Rate limit: 45 requests/minute (free tier)
  - Cache: 24-hour in-memory cache
  - File: `app/geoip.py`
  - API endpoint: `http://ip-api.com/json/{ip}` (single) or `http://ip-api.com/batch` (bulk up to 100 IPs)
  - No API key required

**AbuseIPDB Integration:**
- Service: AbuseIPDB (IP reputation database)
  - What it's used for: Check IP abuse score, report malicious IPs, risk assessment
  - SDK/Client: httpx (async HTTP)
  - Auth: Environment variable `ABUSEIPDB_API_KEY`
  - File: `app/abuseipdb.py`
  - API base: `https://api.abuseipdb.com/api/v2`
  - Endpoints:
    - `GET /check` - Check IP reputation (cache TTL: 1 hour)
    - `POST /report` - Report IP with categories and comment
  - Categories supported: port_scan, hacking, brute_force, bad_web_bot, exploited_host, web_app_attack, ssh, iot_targeted
  - Rate limiting: Subject to API tier (free, basic, premium)
  - Configuration: `ABUSEIPDB_API_KEY` (optional), `ABUSEIPDB_AUTO_REPORT` (default: true)

**Telegram Bot Notifications:**
- Service: Telegram Bot API
  - What it's used for: Real-time security alerts with severity levels
  - SDK/Client: httpx (async HTTP)
  - Auth: 
    - Bot token: `TELEGRAM_BOT_TOKEN` (from @BotFather)
    - Chat ID: `TELEGRAM_CHAT_ID` (destination chat)
  - File: `app/telegram_alerter.py`
  - API endpoint: `https://api.telegram.org/bot{TOKEN}/sendMessage`
  - Message format: HTML markup with emoji indicators
  - Severity levels: critical (🔴), high (🟠), medium (🟡)
  - Optional alerts for: threat type, attacker IP, country, target host, status code, attack details, recommendations

## Data Storage

**Databases:**
- SQLite (local file-based)
  - Connection: `sqlite:///[DATABASE_PATH]`
  - Client: SQLAlchemy ORM
  - File: `app/database.py`
  - Location: `data/dashboard.db` (in container: `/app/data/dashboard.db`)
  - Tables:
    - `access_logs` - All parsed HTTP access logs from Traefik
    - `intruder_events` - Detected attack events with recommendations
    - `blocked_ips` - IP blocklist with optional CIDR support and expiry times

**File Storage:**
- Local filesystem only (no cloud storage)
  - Log files: Read from mounted Traefik directory
  - Database: SQLite file in `data/` directory
  - Config: Environment variables via `.env` file

**Caching:**
- In-memory caching:
  - GeoIP lookups: 24-hour TTL (prevent duplicate API calls)
  - AbuseIPDB checks: 1-hour TTL
  - DNS hostname resolution: 1000-entry LRU cache (function-level)

## Authentication & Identity

**Auth Provider:**
- None - Dashboard is intended for internal use only
- No authentication layer implemented
- Relies on network access control (Docker network or firewall)

## Monitoring & Observability

**Error Tracking:**
- None (no external service)
- Errors logged to console

**Logs:**
- Console output (stdout/stderr)
- Captured in Docker logs via `docker logs -f traefik-sentinel`
- Input source: Traefik JSON access logs read from filesystem

## CI/CD & Deployment

**Hosting:**
- Docker container (portable)
- Production: `/srv/ai-lab/traefik-dashboard/` on dedicated server
- Container name: `traefik-sentinel`
- Health check: HTTP GET `/api/stats` (interval: 30s, timeout: 10s, retries: 3)

**CI Pipeline:**
- None (manual Docker Compose deployment)
- Build command: `docker compose up -d --build`

## Environment Configuration

**Required env vars:**
- `TRAEFIK_LOG_DIR` - Path to Traefik access log directory (default: `/var/log/traefik`)
- `TRAEFIK_LOG_PATH` - Full path to log file (default: `/var/log/traefik/access.log`)

**Optional env vars:**
- `PORT` - Dashboard port (default: 13923)
- `TZ` - Timezone (default: UTC)
- `TELEGRAM_BOT_TOKEN` - Telegram bot token for alerts
- `TELEGRAM_CHAT_ID` - Telegram destination chat ID
- `ABUSEIPDB_API_KEY` - AbuseIPDB API key (free tier from abuseipdb.com)
- `ABUSEIPDB_AUTO_REPORT` - Auto-report blocked IPs (default: true)
- `RATE_LIMIT_REQUESTS` - Rate limit threshold (default: 500)
- `RATE_LIMIT_WINDOW_SECONDS` - Rate limit window (default: 60)
- `AUTH_FAILURE_THRESHOLD` - Brute-force threshold (default: 10)
- `AUTH_FAILURE_WINDOW_SECONDS` - Brute-force window (default: 300)
- `WHITELISTED_IPS` - Comma-separated IPs to exclude from alerts
- `HONEYPOT_INSTANT_BLOCK` - Instant block honeypot access (default: true)
- `RETENTION_ACCESS_LOGS_DAYS` - Keep access logs (default: 30)
- `RETENTION_INTRUDER_EVENTS_DAYS` - Keep intruder events (default: 90)
- `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` - Keep inactive blocks (default: 180)

**Secrets location:**
- `.env` file (gitignored)
- Docker Compose reads from `.env` or environment
- No secrets committed to repository

## Webhooks & Callbacks

**Incoming:**
- None - Application does not expose webhook receivers

**Outgoing:**
- Telegram: `https://api.telegram.org/bot{TOKEN}/sendMessage` (HTTP POST)
- AbuseIPDB report: `https://api.abuseipdb.com/api/v2/report` (HTTP POST)
- GeoIP lookup: `http://ip-api.com/json/{ip}` (HTTP GET)
- GeoIP batch: `http://ip-api.com/batch` (HTTP POST, up to 100 IPs per request)

## Log Ingestion

**Traefik Integration:**
- Source: JSON access logs from Traefik (file-based monitoring)
- File watching: Watchdog monitors for changes to `TRAEFIK_LOG_PATH`
- Parser: `app/log_parser.py` - Parses Traefik JSON format
- Database: Parsed logs stored in `access_logs` table
- Real-time streaming: Server-Sent Events (SSE) endpoint at `/api/stream` for live dashboard updates

## Export Capabilities

**Blocklist Export:**
- Plain text format (one IP/CIDR per line)
- Endpoint: `GET /api/blocklist/export`
- Used by: `scripts/sync-blocklist-ipset.sh` for firewall synchronization

---

*Integration audit: 2026-04-11*
