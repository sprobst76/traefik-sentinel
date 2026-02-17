import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
from app.config import (
    SUSPICIOUS_PATHS,
    SUSPICIOUS_FILES,
    SQL_INJECTION_PATTERNS,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    AUTH_FAILURE_THRESHOLD,
    AUTH_FAILURE_WINDOW_SECONDS,
    WHITELISTED_IPS,
)
from app.log_parser import ParsedLog


class IntruderDetector:
    def __init__(self):
        # Track requests per IP: {ip: [(timestamp, path), ...]}
        self.request_history: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
        # Track auth failures per IP: {ip: [timestamp, ...]}
        self.auth_failures: dict[str, list[datetime]] = defaultdict(list)
        # Track already alerted IPs for specific reasons: {(ip, reason): timestamp}
        self.alerted: dict[tuple[str, str], datetime] = {}
        # Cooldown period for re-alerting same IP/reason
        self.alert_cooldown = timedelta(minutes=15)

    def _is_whitelisted(self, ip: str) -> bool:
        """Check if IP is whitelisted."""
        return ip in WHITELISTED_IPS

    def _clean_old_entries(self, ip: str, now: datetime):
        """Remove entries older than the detection window."""
        rate_cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
        auth_cutoff = now - timedelta(seconds=AUTH_FAILURE_WINDOW_SECONDS)

        self.request_history[ip] = [
            (ts, path) for ts, path in self.request_history[ip] if ts > rate_cutoff
        ]
        self.auth_failures[ip] = [
            ts for ts in self.auth_failures[ip] if ts > auth_cutoff
        ]

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

    def _is_static_asset(self, path: str) -> bool:
        """Check if path is a static asset (JS, CSS, images, fonts)."""
        # Common static asset directories
        static_prefixes = ('/assets/', '/static/', '/_next/', '/dist/', '/build/', '/public/')
        path_lower = path.lower()

        if any(path_lower.startswith(p) for p in static_prefixes):
            return True

        # Common static file extensions
        static_extensions = (
            '.js', '.css', '.map', '.woff', '.woff2', '.ttf', '.eot', '.otf',
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.avif',
            '.mp3', '.mp4', '.webm', '.ogg', '.wav',
        )
        if any(path_lower.endswith(ext) for ext in static_extensions):
            return True

        return False

    def check_suspicious_path(self, log: ParsedLog) -> Optional[dict]:
        """Check if the request path matches known attack patterns."""
        path_lower = log.path.lower()

        # Skip static assets - these are legitimate browser requests
        if self._is_static_asset(log.path):
            return None

        # Check path prefixes (e.g., /wp-admin, /.env)
        for suspicious in SUSPICIOUS_PATHS:
            if path_lower.startswith(suspicious.lower()):
                reason = "suspicious_path"
                if self._should_alert(log.ip, reason, log.timestamp):
                    return {
                        "ip": log.ip,
                        "reason": reason,
                        "details": f"Accessed suspicious path: {log.path}",
                        "timestamp": log.timestamp,
                        "status_code": log.status,
                        "host": log.host,
                    }

        # Check for suspicious filenames at end of path
        filename = path_lower.split("/")[-1].split("?")[0]
        for suspicious_file in SUSPICIOUS_FILES:
            if filename == suspicious_file.lower():
                reason = "suspicious_path"
                if self._should_alert(log.ip, reason, log.timestamp):
                    return {
                        "ip": log.ip,
                        "reason": reason,
                        "details": f"Accessed suspicious file: {log.path}",
                        "timestamp": log.timestamp,
                        "status_code": log.status,
                        "host": log.host,
                    }

        return None

    def check_sql_injection(self, log: ParsedLog) -> Optional[dict]:
        """Check for SQL injection patterns in the path/query."""
        path_lower = log.path.lower()
        for pattern in SQL_INJECTION_PATTERNS:
            if re.search(pattern, path_lower, re.IGNORECASE):
                reason = "sql_injection"
                if self._should_alert(log.ip, reason, log.timestamp):
                    return {
                        "ip": log.ip,
                        "reason": reason,
                        "details": f"SQL injection attempt: {log.path[:200]}",
                        "timestamp": log.timestamp,
                        "status_code": log.status,
                        "host": log.host,
                    }
        return None

    def check_rate_limit(self, log: ParsedLog) -> Optional[dict]:
        """Check if IP exceeds rate limit."""
        self._clean_old_entries(log.ip, log.timestamp)
        self.request_history[log.ip].append((log.timestamp, log.path))

        request_count = len(self.request_history[log.ip])
        if request_count > RATE_LIMIT_REQUESTS:
            reason = "rate_limit"
            if self._should_alert(log.ip, reason, log.timestamp):
                return {
                    "ip": log.ip,
                    "reason": reason,
                    "details": f"Rate limit exceeded: {request_count} requests in {RATE_LIMIT_WINDOW_SECONDS}s",
                    "timestamp": log.timestamp,
                    "request_count": request_count,
                    "status_code": log.status,
                    "host": log.host,
                }
        return None

    def check_auth_failures(self, log: ParsedLog) -> Optional[dict]:
        """Check for excessive authentication failures."""
        if log.status in (401, 403):
            self._clean_old_entries(log.ip, log.timestamp)
            self.auth_failures[log.ip].append(log.timestamp)

            failure_count = len(self.auth_failures[log.ip])
            if failure_count >= AUTH_FAILURE_THRESHOLD:
                reason = "auth_failures"
                if self._should_alert(log.ip, reason, log.timestamp):
                    return {
                        "ip": log.ip,
                        "reason": reason,
                        "details": f"Auth failures: {failure_count} in {AUTH_FAILURE_WINDOW_SECONDS}s",
                        "timestamp": log.timestamp,
                        "request_count": failure_count,
                        "status_code": log.status,
                        "host": log.host,
                    }
        return None

    def analyze(self, log: ParsedLog) -> list[dict]:
        """Analyze a log entry for all intrusion patterns."""
        events = []

        # Check all patterns
        checks = [
            self.check_suspicious_path(log),
            self.check_sql_injection(log),
            self.check_rate_limit(log),
            self.check_auth_failures(log),
        ]

        for result in checks:
            if result:
                events.append(result)

        return events


# Global detector instance
detector = IntruderDetector()


def analyze_log(log: ParsedLog) -> list[dict]:
    """Analyze a log entry for intrusion patterns."""
    return detector.analyze(log)
