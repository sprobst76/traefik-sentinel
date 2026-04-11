# Coding Conventions

**Analysis Date:** 2026-04-11

## Naming Patterns

**Files:**
- Lowercase with underscores: `log_parser.py`, `intruder_detection.py`, `telegram_alerter.py`
- Module names match their primary responsibility
- Constants in ALL_CAPS in config files

**Functions:**
- Lowercase with underscores: `resolve_ip()`, `_read_new_lines()`, `check_suspicious_path()`
- Private/internal functions prefixed with underscore: `_is_whitelisted()`, `_should_alert()`, `_clean_old_entries()`
- Async functions follow same naming convention: `send_telegram_alert()`, `lookup_batch()`
- Verb-first naming for actions: `check_*`, `parse_*`, `block_*`, `analyze_*`

**Variables:**
- Lowercase with underscores: `request_history`, `auth_failures`, `alert_cooldown`
- Single-letter variables only in loops: `for r in results:`, `for b in blocks:`
- Caching variables: `_ip_cache`, `_geoip_cache`, `_batch_queue`

**Classes:**
- PascalCase: `IntruderDetector`, `LogFileHandler`, `LogWatcher`
- SQLAlchemy models use descriptive names: `AccessLog`, `IntruderEvent`, `BlockedIP`

**Constants:**
- ALL_CAPS in modules: `RATE_LIMIT_REQUESTS`, `HONEYPOT_PATHS`, `THREAT_SEVERITY`
- Grouped with related constants in config or module top
- Dictionary constants for configuration: `CATEGORIES`, `RECOMMENDATIONS`, `THREAT_SEVERITY`, `BLOCK_DURATIONS`

## Code Style

**Formatting:**
- No explicit formatter/linter configured (review requirements.txt)
- Standard Python style observed: 4-space indentation
- Line length varies (no strict limit observed)
- Two blank lines between top-level definitions
- Imports organized but no strict grouping enforced

**Imports:**
- Standard library imports first (asyncio, os, json, re, datetime, etc.)
- Third-party frameworks (fastapi, sqlalchemy, httpx, watchdog)
- Local app imports: `from app.config import`, `from app.database import`
- Path aliases not used; relative imports within `app/` module

**Import Organization:**
1. Standard library (`import asyncio`, `from datetime import`, etc.)
2. Third-party (`from fastapi import`, `import sqlalchemy`)
3. Local app (`from app.config import`, `from app.database import`)

Example from `main.py` (lines 1-14):
```python
import asyncio
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from app.config import HOST, PORT
from app.database import init_db, SessionLocal, AccessLog, IntruderEvent, BlockedIP
from app.log_watcher import watcher
from app.geoip import lookup_batch, get_cached, country_code_to_flag
```

**Linting/Formatting:**
- No .eslintrc, .flake8, .black, or pylint config files present
- Code generally follows PEP 8 conventions by observation
- No pre-commit hooks or formatting automation detected

## Error Handling

**Pattern 1: Try/Except with Print to Stdout**
Used in async functions and file operations:
```python
try:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, timeout=10.0)
        return response.status_code == 200
except Exception as e:
    print(f"Failed to send Telegram alert: {e}")
    return False
```
Location: `telegram_alerter.py:104-110`, `geoip.py:84-85`

**Pattern 2: Try/Finally with Resource Cleanup**
Used throughout for database session management:
```python
db = SessionLocal()
try:
    # database operations
    results = db.query(AccessLog).filter(...).all()
finally:
    db.close()
```
Location: `main.py:53-88`, `blocklist.py:200+`

**Pattern 3: Optional Returns with None**
Parsing functions return None on failure:
```python
def parse_json_log(line: str) -> Optional[ParsedLog]:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
```
Location: `log_parser.py:38-43`

**Pattern 4: Try/Except with Fallback**
Handles graceful degradation:
```python
try:
    timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
except ValueError:
    timestamp = datetime.utcnow()  # Use current time as fallback
```
Location: `log_parser.py:46-53`

**Pattern 5: Dict Success/Error Returns**
API and utility functions return structured dicts:
```python
return {"error": "Invalid IP or CIDR format", "success": False}
return {"success": True, "id": blocked.id, "ip": ip, "is_cidr": is_cidr}
```
Location: `blocklist.py:135, 154, 220`

**Pattern 6: RuntimeError Handling for Event Loops**
Async context switching:
```python
try:
    return asyncio.run(send_telegram_alert(event))
except RuntimeError:
    # If there's already an event loop running
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(send_telegram_alert(event))
```
Location: `telegram_alerter.py:113-120`

**No Custom Exceptions:**
- No custom exception classes defined
- Uses built-in exceptions: `ValueError`, `FileNotFoundError`, `json.JSONDecodeError`
- No exception chaining or nested custom error types

## Logging

**Framework:** Console printing via `print()`

**Patterns:**
- Error logs: `print(f"Error reading log file: {e}")`
- Migration logs: `print(f"Migration: Added column {col_name}")`
- Event logs: `print(f"GeoIP lookup failed for {ip}: {e}")`

**When to Log:**
- External API failures: GeoIP lookups, Telegram sends, AbuseIPDB checks
- File operations: Log reading errors, file not found
- Database migration issues
- Auto-blocking decisions (optional, via notifications instead)

**No DEBUG/INFO/WARNING levels** - all console output treated equally

Location: Throughout modules, e.g., `log_watcher.py:41`, `database.py:99`, `geoip.py:85`

## Comments

**When to Comment:**
- Complex detection logic with multiple conditions
- Non-obvious algorithmic choices (rate limit windows, caching TTLs)
- Module-level docstrings explaining purpose

**JSDoc/TSDoc:**
- Minimal docstrings on functions
- Module docstrings common: `"""GeoIP lookup module using ip-api.com..."""` (geoip.py:1-3)
- Function docstrings present but brief: `"""Reverse DNS lookup for IP address. Cached."""` (main.py:19)
- Type hints used: `def lookup_batch(ips: list[str]) -> dict[str, dict]:`

**Example from codebase:**
```python
def _should_alert(self, ip: str, reason: str, now: datetime) -> bool:
    """Check if we should alert for this IP/reason combo."""
    # Never alert whitelisted IPs
    if self._is_whitelisted(ip):
        return False

    key = (ip, reason)
    last_alert = self.alerted.get(key)
    if last_alert and (now - last_alert) < self.alert_cooldown:
        return False
    self.alerted[key] = now
    return True
```
Location: `intruder_detection.py:45-56`

## Function Design

**Size:** Small, focused functions (10-30 lines typical)
- Detection checks: `check_suspicious_path()` (20 lines)
- Parsing: `parse_json_log()` (40 lines, but data extraction)
- Complex analysis: `get_top_ips()` (80 lines, but endpoint with query building)

**Parameters:**
- Explicit parameters preferred
- Database operations pass `db: Session`
- Optional parameters with defaults: `send_alert(message: str, parse_mode: str = "Markdown")`
- Type hints consistently used: `def block_ip(db: Session, ip: str, reason: str = None, ...) -> dict:`

**Return Values:**
- Consistent return types: functions return either Dict, Optional[Dict], or None
- API endpoints return Dict for JSON serialization
- Parsing functions return dataclass instances or None: `Optional[ParsedLog]`
- Database operations return success indicators: `{"success": True, ...}`

Location: `blocklist.py:119-228`, `log_parser.py:38-151`

## Module Design

**Exports:**
- All public functions exported at module level
- Global detector instance pattern: `detector = IntruderDetector()` at module level (intruder_detection.py:195)
- Wrapper functions for async: `def send_alert_sync(event: dict)` (telegram_alerter.py:113)

**Barrel Files:**
- Not used; each module imported directly
- Example: `from app.log_parser import parse_log_line` not `from app import parse_log_line`

**Module Responsibilities:**
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

**Usage:** Consistently applied throughout
- Function parameters: `def check_ip(ip: str) -> Optional[dict]:`
- Dataclass fields: `@dataclass class ParsedLog: timestamp: datetime`
- Type unions: `list[str]`, `dict[str, dict]`, `tuple[bool, Optional[...]]`
- SQLAlchemy Column types: `Column(String(45), Integer, DateTime)`

**Optional types:** `Optional[str]`, `Optional[dict]`, `Optional[timedelta]`

## Caching Patterns

**In-memory dictionaries:**
- `_geoip_cache: dict[str, tuple[datetime, dict]]` (geoip.py:12)
- `_ip_cache: dict[str, tuple[datetime, dict]]` (abuseipdb.py:13)
- `_abuse_check_cache: dict[str, tuple[datetime, dict]]` (auto_blocker.py:19)

**Cache structure:** `{key: (timestamp, data)}`

**TTL pattern:** Stored alongside data, checked at retrieval
```python
if datetime.utcnow() - cached_time < CACHE_TTL:
    return cached_data
```

**Cleanup:** Manual cleanup functions provided
```python
def cleanup_cache():
    """Remove expired cache entries."""
    now = datetime.utcnow()
    expired = [ip for ip, (cache_time, _) in _cache.items() if now - cache_time >= CACHE_TTL]
    for ip in expired:
        del _cache[ip]
```

## Dataclasses

**Usage:** Single dataclass for structured data
```python
@dataclass
class ParsedLog:
    timestamp: datetime
    ip: str
    user: Optional[str]
    method: str
    # ... other fields
```
Location: `log_parser.py:8-24`

## Decorators

**Used Decorators:**
- `@lru_cache(maxsize=1000)`: DNS lookup caching (main.py:17)
- `@asynccontextmanager`: FastAPI lifespan management (main.py:27)
- `@app.get()`, `@app.post()`, `@app.delete()`: FastAPI route decorators
- SQLAlchemy table metadata: `__tablename__`, `__table_args__`

---

*Convention analysis: 2026-04-11*
