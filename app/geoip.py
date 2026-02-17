"""
GeoIP lookup module using ip-api.com (free, no API key required).
Rate limit: 45 requests/minute for free tier.
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional
import asyncio

# In-memory cache for IP -> country lookups
_geoip_cache: dict[str, tuple[datetime, dict]] = {}
CACHE_TTL = timedelta(hours=24)  # Cache for 24 hours

# Batch queue for bulk lookups
_batch_queue: list[str] = []
_batch_lock = asyncio.Lock()


def country_code_to_flag(country_code: str) -> str:
    """Convert ISO country code to emoji flag."""
    if not country_code or len(country_code) != 2:
        return ""

    # Convert country code to regional indicator symbols
    # A = 🇦 (U+1F1E6), B = 🇧 (U+1F1E7), etc.
    try:
        return "".join(chr(0x1F1E6 + ord(c.upper()) - ord('A')) for c in country_code)
    except:
        return ""


async def lookup_ip(ip: str) -> Optional[dict]:
    """
    Look up GeoIP info for a single IP.
    Returns dict with country_code, country, city, isp, etc.
    """
    # Check cache first
    if ip in _geoip_cache:
        cached_time, cached_data = _geoip_cache[ip]
        if datetime.utcnow() - cached_time < CACHE_TTL:
            return cached_data

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={
                    "fields": "status,message,country,countryCode,city,isp,org,as,query"
                }
            )

            if response.status_code == 200:
                data = response.json()

                if data.get("status") == "success":
                    result = {
                        "ip": data.get("query", ip),
                        "country_code": data.get("countryCode", ""),
                        "country": data.get("country", ""),
                        "city": data.get("city", ""),
                        "isp": data.get("isp", ""),
                        "org": data.get("org", ""),
                        "asn": data.get("as", ""),
                        "flag": country_code_to_flag(data.get("countryCode", "")),
                    }
                    _geoip_cache[ip] = (datetime.utcnow(), result)
                    return result
                else:
                    # Private IP or invalid
                    result = {
                        "ip": ip,
                        "country_code": "",
                        "country": "Private/Reserved",
                        "city": "",
                        "isp": "",
                        "org": "",
                        "asn": "",
                        "flag": "",
                    }
                    _geoip_cache[ip] = (datetime.utcnow(), result)
                    return result

    except Exception as e:
        print(f"GeoIP lookup failed for {ip}: {e}")

    return None


async def lookup_batch(ips: list[str]) -> dict[str, dict]:
    """
    Look up GeoIP info for multiple IPs using batch API.
    ip-api.com supports batch of up to 100 IPs.
    Returns dict mapping IP -> geoip info.
    """
    results = {}

    # First, check cache and filter out cached IPs
    uncached_ips = []
    for ip in ips:
        if ip in _geoip_cache:
            cached_time, cached_data = _geoip_cache[ip]
            if datetime.utcnow() - cached_time < CACHE_TTL:
                results[ip] = cached_data
                continue
        uncached_ips.append(ip)

    if not uncached_ips:
        return results

    # Batch API (max 100 per request)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Split into batches of 100
            for i in range(0, len(uncached_ips), 100):
                batch = uncached_ips[i:i+100]

                response = await client.post(
                    "http://ip-api.com/batch",
                    json=[{"query": ip, "fields": "status,country,countryCode,city,isp,org,as,query"} for ip in batch],
                )

                if response.status_code == 200:
                    batch_data = response.json()

                    for item in batch_data:
                        ip = item.get("query", "")
                        if item.get("status") == "success":
                            result = {
                                "ip": ip,
                                "country_code": item.get("countryCode", ""),
                                "country": item.get("country", ""),
                                "city": item.get("city", ""),
                                "isp": item.get("isp", ""),
                                "org": item.get("org", ""),
                                "asn": item.get("as", ""),
                                "flag": country_code_to_flag(item.get("countryCode", "")),
                            }
                        else:
                            result = {
                                "ip": ip,
                                "country_code": "",
                                "country": "Private/Reserved",
                                "city": "",
                                "isp": "",
                                "org": "",
                                "asn": "",
                                "flag": "",
                            }

                        _geoip_cache[ip] = (datetime.utcnow(), result)
                        results[ip] = result

                # Small delay between batches to respect rate limits
                if i + 100 < len(uncached_ips):
                    await asyncio.sleep(0.5)

    except Exception as e:
        print(f"GeoIP batch lookup failed: {e}")

    return results


def get_cached(ip: str) -> Optional[dict]:
    """Get cached GeoIP info (sync, no API call)."""
    if ip in _geoip_cache:
        cached_time, cached_data = _geoip_cache[ip]
        if datetime.utcnow() - cached_time < CACHE_TTL:
            return cached_data
    return None


def cleanup_cache():
    """Remove expired cache entries."""
    now = datetime.utcnow()
    expired = [
        ip for ip, (cache_time, _) in _geoip_cache.items()
        if now - cache_time >= CACHE_TTL
    ]
    for ip in expired:
        del _geoip_cache[ip]
