import json
import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedLog:
    timestamp: datetime
    ip: str
    user: Optional[str]
    method: str
    path: str
    protocol: str
    status: int
    bytes: int
    referer: Optional[str]
    user_agent: Optional[str]
    request_num: int
    router: Optional[str]
    backend: Optional[str]
    duration_ms: int
    host: Optional[str] = None  # The requested hostname (e.g., app.example.com)


# CLF Pattern for backwards compatibility
CLF_PATTERN = re.compile(
    r'^(?P<ip>\S+)\s+-\s+(?P<user>\S+)\s+\[(?P<datetime>[^\]]+)\]\s+'
    r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<protocol>[^"]+)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\d+)\s+"(?P<referer>[^"]*)"\s+'
    r'"(?P<user_agent>[^"]*)"\s+(?P<request_num>\d+)\s+"(?P<router>[^"]*)"\s+'
    r'"(?P<backend>[^"]*)"\s+(?P<duration>\d+)ms$'
)
CLF_DATE_FORMAT = "%d/%b/%Y:%H:%M:%S %z"


def parse_json_log(line: str) -> Optional[ParsedLog]:
    """Parse a JSON format Traefik log line."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Parse timestamp (ISO format: 2026-02-16T19:59:31Z)
    try:
        time_str = data.get("time", data.get("StartUTC", ""))
        if time_str:
            timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        else:
            timestamp = datetime.utcnow()
    except ValueError:
        timestamp = datetime.utcnow()

    # Extract fields from JSON
    ip = data.get("ClientHost", data.get("ClientAddr", "").split(":")[0])
    host = data.get("RequestHost", "")
    method = data.get("RequestMethod", "")
    path = data.get("RequestPath", "")
    protocol = data.get("RequestProtocol", "")
    status = int(data.get("OriginStatus", data.get("DownstreamStatus", 0)))
    bytes_sent = int(data.get("OriginContentSize", data.get("DownstreamContentSize", 0)))

    # Duration in nanoseconds, convert to ms
    duration_ns = data.get("Duration", 0)
    duration_ms = int(duration_ns / 1_000_000) if duration_ns else 0

    router = data.get("RouterName", "")
    backend = data.get("ServiceURL", "")
    request_num = int(data.get("RequestCount", 0))

    # User from header or entrypoint auth
    user = data.get("ClientUsername", "")
    if not user or user == "-":
        user = None

    # User-Agent from headers
    headers = data.get("request_User-Agent", data.get("RequestHeaders", {}))
    if isinstance(headers, dict):
        user_agent = headers.get("User-Agent", [""])[0] if "User-Agent" in headers else None
    elif isinstance(headers, str):
        user_agent = headers
    else:
        user_agent = None

    return ParsedLog(
        timestamp=timestamp,
        ip=ip,
        user=user,
        method=method,
        path=path,
        protocol=protocol,
        status=status,
        bytes=bytes_sent,
        referer=None,
        user_agent=user_agent,
        request_num=request_num,
        router=router if router else None,
        backend=backend if backend else None,
        duration_ms=duration_ms,
        host=host if host else None,
    )


def parse_clf_log(line: str) -> Optional[ParsedLog]:
    """Parse a CLF format Traefik log line (legacy)."""
    match = CLF_PATTERN.match(line)
    if not match:
        return None

    data = match.groupdict()

    try:
        timestamp = datetime.strptime(data["datetime"], CLF_DATE_FORMAT)
    except ValueError:
        return None

    def clean(val):
        return val if val and val != "-" else None

    return ParsedLog(
        timestamp=timestamp,
        ip=data["ip"],
        user=clean(data["user"]),
        method=data["method"],
        path=data["path"],
        protocol=data["protocol"],
        status=int(data["status"]),
        bytes=int(data["bytes"]),
        referer=clean(data["referer"]),
        user_agent=clean(data["user_agent"]),
        request_num=int(data["request_num"]),
        router=clean(data["router"]),
        backend=clean(data["backend"]),
        duration_ms=int(data["duration"]),
        host=None,  # CLF doesn't include host
    )


def parse_log_line(line: str) -> Optional[ParsedLog]:
    """Parse a single Traefik access log line (JSON or CLF)."""
    line = line.strip()
    if not line:
        return None

    # Try JSON first (new format)
    if line.startswith("{"):
        return parse_json_log(line)

    # Fall back to CLF (legacy)
    return parse_clf_log(line)


def parse_log_file(file_path: str) -> list[ParsedLog]:
    """Parse all lines from a log file."""
    logs = []
    try:
        with open(file_path, "r") as f:
            for line in f:
                parsed = parse_log_line(line)
                if parsed:
                    logs.append(parsed)
    except FileNotFoundError:
        pass
    return logs
