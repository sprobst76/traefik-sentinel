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
