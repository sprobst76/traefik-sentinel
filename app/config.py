import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
LOG_PATH = os.getenv("TRAEFIK_LOG_PATH", "/var/log/traefik/access.log")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "dashboard.db"))

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "13923"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# Alert routing — minimum severity for immediate Telegram alerts
# Valid values: "critical" | "high" | "medium". Default "high" preserves existing behavior
# for deployments that only set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (ALERT-05).
_ALERT_MIN_SEVERITY_RAW = os.getenv("ALERT_MIN_SEVERITY", "high").lower()
if _ALERT_MIN_SEVERITY_RAW not in {"critical", "high", "medium"}:
    print(f"Config warning: ALERT_MIN_SEVERITY={_ALERT_MIN_SEVERITY_RAW!r} invalid, falling back to 'high'")
    ALERT_MIN_SEVERITY = "high"
else:
    ALERT_MIN_SEVERITY = _ALERT_MIN_SEVERITY_RAW

# Intruder Detection Thresholds
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
AUTH_FAILURE_THRESHOLD = int(os.getenv("AUTH_FAILURE_THRESHOLD", "10"))
AUTH_FAILURE_WINDOW_SECONDS = int(os.getenv("AUTH_FAILURE_WINDOW_SECONDS", "300"))

# Whitelisted IPs (no alerts for these)
WHITELISTED_IPS = [ip.strip() for ip in os.getenv("WHITELISTED_IPS", "").split(",") if ip.strip()]

# Suspicious Paths - must match at start of path (not substring)
SUSPICIOUS_PATHS = [
    "/wp-admin",
    "/wp-login.php",
    "/wp-content/",
    "/wp-includes/",
    "/.env",
    "/.git",
    "/.htaccess",
    "/phpMyAdmin",
    "/phpmyadmin",
    "/pma",
    "/cgi-bin/",
    "/shell.php",
    "/cmd.php",
    "/eval.php",
    "/exec.php",
    "/c99.php",
    "/r57.php",
    "/webshell",
    "/backdoor",
]

# Additional exact-match suspicious filenames
SUSPICIOUS_FILES = [
    "config.php",
    "config.yml",
    "config.yaml",
    "wp-config.php",
    ".env",
    ".htpasswd",
    "id_rsa",
    "passwd",
    "shadow",
]

# SQL Injection Patterns
SQL_INJECTION_PATTERNS = [
    r"union\s+select",
    r"or\s+1\s*=\s*1",
    r"and\s+1\s*=\s*1",
    r"'\s*or\s*'",
    r";\s*drop\s+",
    r";\s*delete\s+",
    r";\s*update\s+",
    r";\s*insert\s+",
    r"--\s*$",
    r"/\*.*\*/",
]

# Honeypot Paths - INSTANT BLOCK on first access
# These are paths that NO legitimate user would ever access
HONEYPOT_PATHS = [
    # WordPress (we don't use WordPress)
    "/wp-admin",
    "/wp-login.php",
    "/wp-content/uploads",
    "/xmlrpc.php",
    # PHP Admin tools
    "/phpMyAdmin",
    "/phpmyadmin",
    "/pma",
    "/adminer.php",
    "/adminer",
    # Shells & Backdoors
    "/shell.php",
    "/c99.php",
    "/r57.php",
    "/webshell",
    "/backdoor",
    "/cmd.php",
    "/eval.php",
    # Config files (should never be web-accessible)
    "/.env",
    "/.git/config",
    "/.git/HEAD",
    "/.aws/credentials",
    "/.docker/config.json",
    "/config.php.bak",
    "/wp-config.php",
    "/web.config",
    # Common exploit paths
    "/cgi-bin/",
    "/manager/html",  # Tomcat
    "/solr/admin",
    "/actuator",  # Spring Boot
    "/debug/pprof",  # Go debug
    # Scanners often check these
    "/telescope/requests",  # Laravel Telescope
    "/api/v1/pods",  # Kubernetes
    "/.well-known/security.txt",  # Not honeypot but often probed
    "/server-status",
    "/server-info",
    # Strapi/CMS
    "/strapi",
    "/_profiler",
    "/elfinder",
]

# Enable/disable instant honeypot blocking
HONEYPOT_INSTANT_BLOCK = os.getenv("HONEYPOT_INSTANT_BLOCK", "true").lower() == "true"

# Log Retention (in days)
RETENTION_ACCESS_LOGS_DAYS = int(os.getenv("RETENTION_ACCESS_LOGS_DAYS", "30"))
RETENTION_INTRUDER_EVENTS_DAYS = int(os.getenv("RETENTION_INTRUDER_EVENTS_DAYS", "90"))
RETENTION_BLOCKED_IPS_INACTIVE_DAYS = int(os.getenv("RETENTION_BLOCKED_IPS_INACTIVE_DAYS", "180"))  # Inactive blocks only

# Auto-Report to AbuseIPDB
# When enabled, automatically report IPs to AbuseIPDB when they are blocked
ABUSEIPDB_AUTO_REPORT = os.getenv("ABUSEIPDB_AUTO_REPORT", "true").lower() == "true"
ABUSEIPDB_REPORT_COOLDOWN_MINUTES = int(os.getenv("ABUSEIPDB_REPORT_COOLDOWN_MINUTES", "15"))  # Min time between reports for same IP

# Digest scheduling (per D-24, D-25, D-28)
# DIGEST_ENABLED controls whether the async scheduler task starts at lifespan
# startup. Manual /api/digest/send + /api/digest/preview remain active regardless.
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "true").lower() == "true"

# DIGEST_HOUR is the UTC hour (0-23) at which the daily digest fires.
# Invalid values (non-integer or out of range) fall back to 8 with a warning,
# mirroring the ALERT_MIN_SEVERITY pattern above.
try:
    _DIGEST_HOUR_RAW = int(os.getenv("DIGEST_HOUR", "8"))
except ValueError:
    print(f"Config warning: DIGEST_HOUR={os.getenv('DIGEST_HOUR')!r} is not a valid integer, falling back to 8")
    _DIGEST_HOUR_RAW = -1  # forces fallback in range check below

if not 0 <= _DIGEST_HOUR_RAW <= 23:
    print(f"Config warning: DIGEST_HOUR={_DIGEST_HOUR_RAW} out of range 0-23, falling back to 8")
    DIGEST_HOUR = 8
else:
    DIGEST_HOUR = _DIGEST_HOUR_RAW
