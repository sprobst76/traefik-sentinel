# Technology Stack

**Analysis Date:** 2026-04-11

## Languages

**Primary:**
- Python 3.11 - Backend REST API and log processing

**Secondary:**
- HTML - Dashboard templates (templates/index.html)
- CSS - Frontend styling (static/style.css)
- JavaScript - HTMX for dynamic UI without build step

## Runtime

**Environment:**
- Python 3.11 (slim Docker image)

**Package Manager:**
- pip
- Lockfile: `requirements.txt`

## Frameworks

**Core:**
- FastAPI 0.109.0 - REST API framework
- Uvicorn[standard] 0.27.0 - ASGI server

**Template & Frontend:**
- Jinja2 3.1.3 - HTML template rendering
- HTMX - No-build dynamic UI enhancements

**Database:**
- SQLAlchemy 2.0.25 - ORM for database operations
- aiosqlite 0.19.0 - Async SQLite support

**File Watching:**
- Watchdog 3.0.0 - Monitor Traefik log files for changes

**HTTP Client:**
- httpx 0.26.0 - Async HTTP client for external APIs

**Configuration:**
- python-dotenv 1.0.0 - Load environment variables from .env

## Key Dependencies

**Critical:**
- FastAPI 0.109.0 - Core web framework for REST API
- SQLAlchemy 2.0.25 - Database ORM and query building
- Watchdog 3.0.0 - Log file monitoring for real-time updates
- httpx 0.26.0 - Async HTTP calls to external services (AbuseIPDB, Telegram, GeoIP)

**Infrastructure:**
- Uvicorn 0.27.0 - Production-grade ASGI server
- aiosqlite 0.19.0 - Async database access

## Configuration

**Environment:**
- Managed via environment variables in `.env` file
- Configuration loaded via `python-dotenv`
- All critical configs can be overridden at runtime

**Key configs in `.env.example`:**
- `TRAEFIK_LOG_DIR` - Path to Traefik access logs
- `PORT` - Dashboard port (default: 13923)
- `TELEGRAM_BOT_TOKEN` - Telegram notification bot
- `TELEGRAM_CHAT_ID` - Telegram destination chat
- `ABUSEIPDB_API_KEY` - AbuseIPDB API credentials
- `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS` - Detection thresholds
- `AUTH_FAILURE_THRESHOLD`, `AUTH_FAILURE_WINDOW_SECONDS` - Brute-force thresholds
- `HONEYPOT_INSTANT_BLOCK` - Auto-block honeypot access
- `RETENTION_ACCESS_LOGS_DAYS`, `RETENTION_INTRUDER_EVENTS_DAYS`, `RETENTION_BLOCKED_IPS_INACTIVE_DAYS` - Data cleanup policies

**Build:**
- `Dockerfile` - Multi-stage Python 3.11 container
- `docker-compose.yml` - Volume mounts for logs and database

## Platform Requirements

**Development:**
- Python 3.11+
- pip for dependency management
- Access to Traefik log file (watch mode)

**Production:**
- Docker and Docker Compose
- Read-only access to Traefik access log file: `/var/log/traefik/access.log`
- Optional: Telegram bot token (from @BotFather)
- Optional: AbuseIPDB API key (free tier available at abuseipdb.com)
- Optional: External GeoIP service (ip-api.com, free tier)

## Database

**SQLite:**
- Location: `data/dashboard.db` (in container at `/app/data/dashboard.db`)
- No external database server required
- Persistent volume mount: `./data:/app/data`

**Tables:**
- `access_logs` - Parsed Traefik log entries
- `intruder_events` - Detected attack events
- `blocked_ips` - IP blocklist with expiry and CIDR support

## Containerization

**Docker:**
- Base image: `python:3.11-slim`
- Exposed port: 13923
- Restart policy: `unless-stopped`
- Health check: HTTP GET to `/api/stats`

**Volumes:**
- `./data:/app/data` - SQLite database persistence
- `${TRAEFIK_LOG_DIR}:/logs:ro` - Read-only access to Traefik logs

---

*Stack analysis: 2026-04-11*
