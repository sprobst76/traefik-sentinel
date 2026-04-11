# Testing Patterns

**Analysis Date:** 2026-04-11

## Test Framework

**Status:** No automated testing infrastructure present

**No test runner configured:**
- No pytest, unittest, or vitest dependencies in `requirements.txt`
- No test configuration files (pytest.ini, setup.cfg, tox.ini)
- No test directories (no `tests/`, `test_*.py`, or `*_test.py` files)
- No test entry points in main.py or CI configuration

**Dependencies:** `requirements.txt` (9 packages total):
- fastapi==0.109.0
- uvicorn[standard]==0.27.0
- sqlalchemy==2.0.25
- aiosqlite==0.19.0
- httpx==0.26.0
- watchdog==3.0.0
- python-dotenv==1.0.0
- jinja2==3.1.3

No testing frameworks included.

## Current Testing Approach

**Manual Testing Only**
- No test files in codebase
- Integration testing would require:
  - Running Traefik with log generation
  - Manual verification of detection logic
  - Manual Telegram alert checking
  - Database inspection via SQLite CLI

**Code Validation Methods Observed:**
- Type hints throughout (runtime type checking in editor)
- Try/catch error handling (error logs to stdout)
- Local development with uvicorn: `if __name__ == "__main__": uvicorn.run(...)`

## Testable Components

**Mock-friendly Modules:**

**1. `log_parser.py` - Perfect for unit tests**
- `parse_json_log(line: str) -> Optional[ParsedLog]`
- `parse_clf_log(line: str) -> Optional[ParsedLog]`
- `parse_log_line(line: str) -> Optional[ParsedLog]`

Test cases would cover:
- Valid JSON log parsing
- Valid CLF log parsing
- Malformed JSON handling
- Missing fields handling
- Timestamp parsing edge cases (ISO format, CLF format, invalid)
- Edge case: empty lines, only whitespace

**2. `intruder_detection.py` - High test value**
- `IntruderDetector.check_suspicious_path(log: ParsedLog) -> Optional[dict]`
- `IntruderDetector.check_sql_injection(log: ParsedLog) -> Optional[dict]`
- `IntruderDetector.check_rate_limit(log: ParsedLog) -> Optional[dict]`
- `IntruderDetector.check_auth_failures(log: ParsedLog) -> Optional[dict]`
- `IntruderDetector.analyze(log: ParsedLog) -> list[dict]`

Test cases would cover:
- Static asset filtering (should NOT alert on .js, .css, .png)
- Suspicious path detection (WordPress, phpMyAdmin, .env, .git)
- SQL injection pattern matching (UNION SELECT, OR 1=1, etc.)
- Rate limit window behavior
- Whitelist bypass prevention
- Alert cooldown respected
- Multiple violations in single log

**3. `blocklist.py` - Pure logic, very testable**
- `parse_ip_or_cidr(ip_str: str) -> tuple[bool, Optional[...]]`
- `is_ip_in_cidr(ip: str, cidr: str) -> bool`
- `get_block_duration(reason: str, abuse_score: Optional[int]) -> Optional[timedelta]`
- `should_be_permanent(db: Session, ip: str, abuse_score: Optional[int]) -> bool`

Test cases would cover:
- Valid IP parsing
- Valid CIDR parsing (e.g., "192.168.0.0/24")
- Invalid IP/CIDR format rejection
- IP-in-CIDR detection (in range, out of range, edge cases)
- Block duration logic (rate_limit=24h, sql_injection=720h, permanent rules)
- Repeat offender detection (3+ blocks = permanent)
- High abuse score rules (>=80% = permanent)

**4. `security_advisor.py` - Pattern matching, testable**
- `get_recommendation(event: dict) -> str`

Test cases would cover:
- Recommendation by reason type
- Pattern matching in details field
- Status code specific advice (200=critical, 404=ok, etc.)
- Fallback to default recommendations

**5. `geoip.py` - Mocking required for external API**
- `country_code_to_flag(country_code: str) -> str`
- `lookup_ip(ip: str) -> Optional[dict]` (requires HTTP mocking)
- `lookup_batch(ips: list[str]) -> dict[str, dict]` (requires HTTP mocking)

Test cases would cover:
- Country code to emoji conversion (valid, invalid, empty)
- Cache hit/miss behavior
- Cache TTL expiration
- Private IP handling
- Batch API splitting (100 IPs max per request)
- Rate limit delays between batches
- HTTP error handling

**6. `abuseipdb.py` - Mocking required**
- `is_configured() -> bool`
- `check_ip(ip: str) -> Optional[dict]` (requires HTTP mocking)

Test cases would cover:
- Configuration check (with/without API key)
- Cache behavior
- API response parsing
- Error handling (timeouts, HTTP errors)

## Unit Test Candidates (High Priority)

```python
# Example: log_parser.py tests
def test_parse_json_log_valid():
    """Valid JSON log should parse correctly."""
    line = '{"time":"2026-02-16T19:59:31Z","ClientHost":"192.168.1.1",...}'
    result = parse_json_log(line)
    assert result.ip == "192.168.1.1"
    assert result.timestamp.year == 2026

def test_parse_json_log_malformed():
    """Malformed JSON should return None."""
    line = '{"incomplete": json'
    result = parse_json_log(line)
    assert result is None

def test_parse_log_line_prefers_json():
    """JSON format tried first."""
    line = '{"time":"2026-02-16T19:59:31Z",...}'
    result = parse_log_line(line)
    assert result is not None  # JSON parsed

def test_parse_log_line_fallback_to_clf():
    """Falls back to CLF if not JSON."""
    line = '192.168.1.1 - user [16/Feb/2026:19:59:31 +0000] "GET / HTTP/1.1" 200 1234 "-" "Mozilla/5.0" 1 "router" "backend" 100ms'
    result = parse_log_line(line)
    assert result is not None  # CLF parsed
    assert result.ip == "192.168.1.1"
```

```python
# Example: intruder_detection.py tests
def test_suspicious_path_detection():
    """Suspicious paths should be detected."""
    detector = IntruderDetector()
    log = ParsedLog(
        timestamp=datetime.now(),
        ip="192.168.1.1",
        path="/wp-admin/admin.php",
        # ... other required fields
    )
    result = detector.check_suspicious_path(log)
    assert result is not None
    assert result["reason"] == "suspicious_path"

def test_static_assets_not_flagged():
    """Static assets should not trigger alerts."""
    detector = IntruderDetector()
    log = ParsedLog(
        timestamp=datetime.now(),
        ip="192.168.1.1",
        path="/assets/style.css",  # Static asset
        # ... other required fields
    )
    result = detector.check_suspicious_path(log)
    assert result is None  # No alert

def test_whitelisted_ip_not_alerted():
    """Whitelisted IPs should not generate alerts."""
    with patch('app.config.WHITELISTED_IPS', ['192.168.1.1']):
        detector = IntruderDetector()
        log = ParsedLog(
            timestamp=datetime.now(),
            ip="192.168.1.1",
            path="/wp-admin",
            # ... other required fields
        )
        result = detector.check_suspicious_path(log)
        assert result is None

def test_alert_cooldown_respected():
    """Same IP/reason should not alert twice within cooldown."""
    detector = IntruderDetector()
    now = datetime.now()
    
    # First alert
    result1 = detector._should_alert("192.168.1.1", "sql_injection", now)
    assert result1 is True
    
    # Second alert immediately after (within 15 min cooldown)
    result2 = detector._should_alert("192.168.1.1", "sql_injection", now)
    assert result2 is False
    
    # After cooldown expires
    future = now + timedelta(minutes=16)
    result3 = detector._should_alert("192.168.1.1", "sql_injection", future)
    assert result3 is True

def test_rate_limit_detection():
    """Exceeding rate limit should be detected."""
    detector = IntruderDetector()
    with patch('app.config.RATE_LIMIT_REQUESTS', 5):
        with patch('app.config.RATE_LIMIT_WINDOW_SECONDS', 60):
            now = datetime.now()
            
            # Create 5 logs within window
            for i in range(5):
                log = ParsedLog(
                    timestamp=now + timedelta(seconds=i),
                    ip="192.168.1.1",
                    path=f"/path{i}",
                    status=200,
                    # ... other required fields
                )
                detector.check_rate_limit(log)
            
            # 6th log should trigger alert
            final_log = ParsedLog(
                timestamp=now + timedelta(seconds=5),
                ip="192.168.1.1",
                path="/path6",
                status=200,
                # ... other required fields
            )
            result = detector.check_rate_limit(final_log)
            assert result is not None
            assert result["reason"] == "rate_limit"

def test_sql_injection_detection():
    """SQL injection patterns should be detected."""
    detector = IntruderDetector()
    log = ParsedLog(
        timestamp=datetime.now(),
        ip="192.168.1.1",
        path="/search?q=test' UNION SELECT * FROM users--",
        # ... other required fields
    )
    result = detector.check_sql_injection(log)
    assert result is not None
    assert "union" in result["details"].lower()
```

```python
# Example: blocklist.py tests
def test_parse_single_ip():
    """Parse a single IP address."""
    is_cidr, parsed = parse_ip_or_cidr("192.168.1.1")
    assert is_cidr is False
    assert str(parsed) == "192.168.1.1"

def test_parse_ipv6_ip():
    """Parse IPv6 address."""
    is_cidr, parsed = parse_ip_or_cidr("2001:db8::1")
    assert is_cidr is False
    assert str(parsed) == "2001:db8::1"

def test_parse_cidr_range():
    """Parse CIDR range."""
    is_cidr, parsed = parse_ip_or_cidr("192.168.0.0/24")
    assert is_cidr is True
    assert str(parsed) == "192.168.0.0/24"

def test_parse_invalid_ip():
    """Invalid IP should return None."""
    is_cidr, parsed = parse_ip_or_cidr("not.an.ip.address")
    assert is_cidr is False
    assert parsed is None

def test_ip_in_cidr_range():
    """IP within CIDR range should be detected."""
    assert is_ip_in_cidr("192.168.1.50", "192.168.1.0/24") is True

def test_ip_outside_cidr_range():
    """IP outside CIDR range should not match."""
    assert is_ip_in_cidr("192.168.2.50", "192.168.1.0/24") is False

def test_block_duration_rate_limit():
    """Rate limit blocks should be 24 hours."""
    duration = get_block_duration("rate_limit")
    assert duration == timedelta(hours=24)

def test_block_duration_sql_injection():
    """SQL injection blocks should be 30 days."""
    duration = get_block_duration("sql_injection")
    assert duration == timedelta(hours=720)

def test_block_duration_high_abuse_score():
    """High abuse score should be permanent."""
    duration = get_block_duration("anything", abuse_score=85)
    assert duration is None  # Permanent

def test_repeat_offender_permanent():
    """Repeat offenders should be blocked permanently."""
    # Would require DB mock to test fully
    # Tests would verify logic in should_be_permanent()
    pass
```

## Integration Test Scenarios (Not Implemented)

If integration tests were added, they would test:

1. **End-to-end log processing:**
   - Write test Traefik logs to file
   - Verify they're parsed and stored in DB
   - Verify intruder events are created
   - Verify Telegram alert would be sent (mock API)

2. **Database operations:**
   - Create AccessLog entries
   - Trigger IntruderEvent creation
   - Create BlockedIP entries
   - Test cleanup retention policy

3. **API endpoints:**
   - GET /api/stats returns correct data
   - GET /api/intruders returns grouped events
   - POST /api/blocklist blocks IP correctly
   - DELETE /api/blocklist/{ip} unblocks IP

4. **External API mocking:**
   - Mock GeoIP API responses
   - Mock AbuseIPDB API responses
   - Mock Telegram API responses

## What NOT to Test

**External APIs (require mocking):**
- Actual HTTP calls to ip-api.com, AbuseIPDB, Telegram
- These should be unit tested with mock/stub responses

**File I/O (can be mocked):**
- Actual log file reading/writing
- Can mock `open()` and file operations

**Database (can use in-memory SQLite):**
- SQLAlchemy models can be tested with `:memory:` database
- Session management can be tested with test fixtures

**Async/event loop complexity:**
- Event loop management in `log_watcher.py`
- Async context switching in `telegram_alerter.py`
- These need careful fixture setup or integration tests

## Recommended Test Structure

If tests were to be added:

```
traefik-sentinel/
├── tests/
│   ├── conftest.py                 # Shared fixtures
│   ├── test_log_parser.py          # Unit tests for parsing
│   ├── test_intruder_detection.py  # Unit tests for detection logic
│   ├── test_blocklist.py           # Unit tests for blocking
│   ├── test_security_advisor.py    # Unit tests for recommendations
│   ├── test_geoip.py               # Unit tests with mocking
│   ├── test_abuseipdb.py           # Unit tests with mocking
│   └── integration/
│       ├── test_log_to_db.py       # End-to-end log processing
│       └── test_api_endpoints.py   # FastAPI endpoint tests
├── pytest.ini
└── requirements-test.txt            # pytest, pytest-asyncio, pytest-mock, httpx[testing]
```

**conftest.py would provide:**
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base

@pytest.fixture
def test_db():
    """In-memory test database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    yield TestingSessionLocal()

@pytest.fixture
def mock_http_client(monkeypatch):
    """Mock httpx.AsyncClient for external API tests."""
    # Would mock responses for ip-api.com, AbuseIPDB, Telegram
    pass

@pytest.fixture
def sample_parsed_log():
    """Sample ParsedLog for detector tests."""
    from app.log_parser import ParsedLog
    from datetime import datetime
    return ParsedLog(
        timestamp=datetime.now(),
        ip="192.168.1.1",
        user=None,
        method="GET",
        path="/",
        protocol="HTTP/1.1",
        status=200,
        bytes=1234,
        referer=None,
        user_agent="Mozilla/5.0",
        request_num=1,
        router="api@docker",
        backend="http://backend:8000",
        duration_ms=100,
        host="example.com"
    )
```

## Requirements for Testing

**If tests were to be implemented, add to requirements-test.txt:**
```
pytest==7.4.0
pytest-asyncio==0.21.0
pytest-cov==4.1.0
pytest-mock==3.11.0
httpx[testing]==0.26.0
freezegun==1.2.0          # For time-based tests
sqlalchemy[testing]==2.0.25
```

**Run commands would be:**
```bash
pytest                          # Run all tests
pytest -v                       # Verbose output
pytest --cov=app               # With coverage
pytest -k test_parser          # Filter by name
pytest tests/test_blocklist.py # Single file
```

---

*Testing analysis: 2026-04-11*

**Note:** This codebase currently has zero automated tests. All testing is manual. The above sections describe testability and recommended patterns IF tests were to be added.
