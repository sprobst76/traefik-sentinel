"""AbuseIPDB API Integration for checking and reporting malicious IPs."""

import os
import httpx
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

ABUSEIPDB_API_KEY = os.getenv("ABUSEIPDB_API_KEY", "")
ABUSEIPDB_BASE_URL = "https://api.abuseipdb.com/api/v2"

# Cache for IP checks (avoid hitting API limits)
_ip_cache: dict[str, tuple[datetime, dict]] = {}
CACHE_TTL = timedelta(hours=1)

# AbuseIPDB Categories
CATEGORIES = {
    "port_scan": 14,
    "hacking": 15,
    "brute_force": 18,
    "bad_web_bot": 19,
    "exploited_host": 20,
    "web_app_attack": 21,
    "ssh": 22,
    "iot_targeted": 23,
}


def is_configured() -> bool:
    """Check if AbuseIPDB API key is configured."""
    return bool(ABUSEIPDB_API_KEY)


async def check_ip(ip: str) -> Optional[dict]:
    """
    Check IP reputation in AbuseIPDB.
    Returns dict with abuseConfidenceScore, totalReports, etc.
    """
    if not is_configured():
        return None

    # Check cache first
    if ip in _ip_cache:
        cached_time, cached_data = _ip_cache[ip]
        if datetime.utcnow() - cached_time < CACHE_TTL:
            return cached_data

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{ABUSEIPDB_BASE_URL}/check",
                headers={
                    "Key": ABUSEIPDB_API_KEY,
                    "Accept": "application/json",
                },
                params={
                    "ipAddress": ip,
                    "maxAgeInDays": 90,
                    "verbose": True,
                },
            )

            if response.status_code == 200:
                data = response.json().get("data", {})
                result = {
                    "ip": data.get("ipAddress"),
                    "abuse_score": data.get("abuseConfidenceScore", 0),
                    "total_reports": data.get("totalReports", 0),
                    "country": data.get("countryCode", ""),
                    "isp": data.get("isp", ""),
                    "domain": data.get("domain", ""),
                    "is_tor": data.get("isTor", False),
                    "is_public": data.get("isPublic", True),
                    "last_reported": data.get("lastReportedAt"),
                    "usage_type": data.get("usageType", ""),
                }
                # Cache the result
                _ip_cache[ip] = (datetime.utcnow(), result)
                return result

            elif response.status_code == 429:
                # Rate limited
                return {"error": "rate_limited", "abuse_score": -1}

    except Exception as e:
        print(f"AbuseIPDB check failed for {ip}: {e}")
        return {"error": str(e), "abuse_score": -1}

    return None


async def report_ip(
    ip: str,
    categories: list[str],
    comment: str,
) -> dict:
    """
    Report an IP to AbuseIPDB.

    categories: list of category names like ["web_app_attack", "hacking"]
    comment: Description of the attack (max 1024 chars)
    """
    if not is_configured():
        return {"error": "AbuseIPDB API key not configured"}

    # Convert category names to numbers
    category_ids = [CATEGORIES.get(c, 21) for c in categories]
    category_str = ",".join(str(c) for c in category_ids)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{ABUSEIPDB_BASE_URL}/report",
                headers={
                    "Key": ABUSEIPDB_API_KEY,
                    "Accept": "application/json",
                },
                data={
                    "ip": ip,
                    "categories": category_str,
                    "comment": comment[:1024],
                },
            )

            if response.status_code == 200:
                data = response.json().get("data", {})
                # Clear cache for this IP
                _ip_cache.pop(ip, None)
                return {
                    "success": True,
                    "ip": data.get("ipAddress"),
                    "abuse_score": data.get("abuseConfidenceScore", 0),
                }

            elif response.status_code == 429:
                return {"error": "Rate limit erreicht. Bitte später erneut versuchen."}

            elif response.status_code == 422:
                error_detail = response.json().get("errors", [{}])[0].get("detail", "")
                if "already reported" in error_detail.lower():
                    return {"error": "IP wurde bereits kürzlich gemeldet (15 Min Cooldown)"}
                return {"error": f"Validierungsfehler: {error_detail}"}

            else:
                return {"error": f"API Fehler: {response.status_code}"}

    except Exception as e:
        return {"error": f"Verbindungsfehler: {str(e)}"}


def get_risk_assessment(abuse_score: int) -> tuple[str, str]:
    """
    Get risk level and recommendation based on abuse score.
    Returns (risk_level, recommendation)
    """
    if abuse_score >= 80:
        return "critical", "Bekannter Angreifer - sofort blockieren!"
    elif abuse_score >= 50:
        return "high", "Häufig gemeldet - Blockieren empfohlen"
    elif abuse_score >= 25:
        return "medium", "Vereinzelt gemeldet - beobachten"
    elif abuse_score > 0:
        return "low", "Wenige Meldungen"
    else:
        return "none", "Keine Meldungen bekannt"


def build_report_comment(intruder_data: dict) -> str:
    """Build a comment for AbuseIPDB report from intruder data."""
    parts = []

    if intruder_data.get("event_count"):
        parts.append(f"{intruder_data['event_count']} attack attempts")

    if intruder_data.get("reasons"):
        reason_map = {
            "suspicious_path": "path scanning",
            "sql_injection": "SQL injection",
            "rate_limit": "rate limit exceeded",
            "auth_failures": "authentication brute-force",
        }
        reasons = [reason_map.get(r, r) for r in intruder_data["reasons"]]
        parts.append(f"Attack types: {', '.join(reasons)}")

    if intruder_data.get("hosts"):
        hosts = [h.split(".")[0] for h in intruder_data["hosts"][:3]]
        parts.append(f"Targeted hosts: {', '.join(hosts)}")

    if intruder_data.get("details"):
        # Add sample paths
        parts.append(f"Sample: {intruder_data['details'][:200]}")

    return ". ".join(parts) if parts else "Malicious activity detected"
