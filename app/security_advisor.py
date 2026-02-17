"""Static security recommendations for common attack patterns."""

import re

# Recommendations by attack type
RECOMMENDATIONS = {
    "suspicious_path": {
        "default": "Automated scanner. No action needed if status 404. If status 200: Check if sensitive files are exposed.",
        "patterns": {
            r"\.env": "⚠️ .env access attempt! Ensure no .env files are in web root. Nginx: `location ~ /\\. { deny all; }`",
            r"\.git": "⚠️ Git repository scan! .git folders must not be public. If status 200: Rotate secrets! Nginx: `location ~ /\\.git { deny all; }`",
            r"wp-login|wp-admin|wp-content": "WordPress scanner. Ignore if no WordPress installed. Otherwise: Change login URL, set up Fail2Ban for wp-login.",
            r"phpmyadmin|pma": "phpMyAdmin scanner. Ignore if not installed. Otherwise: Restrict access by IP or remove.",
            r"config\.php|config\.yml": "Config file scan. Ensure configuration files are not in web root.",
            r"shell|backdoor|c99|r57": "Webshell scanner. No action needed if status 404.",
        }
    },
    "sql_injection": {
        "default": "SQL injection attempt. Ensure all DB queries use parameterized statements. WAF rule for SQL patterns recommended.",
        "patterns": {
            r"union.*select": "UNION-based SQLi. Use prepared statements for dynamic queries.",
            r"or\s+1\s*=\s*1": "Boolean-based SQLi. Check input validation and use prepared statements.",
        }
    },
    "rate_limit": {
        "default": "Too many requests from this IP. Possible bot/scraper or DDoS. Consider temporarily blocking IP.",
        "patterns": {}
    },
    "auth_failures": {
        "default": "Multiple login failures. Possible brute-force attack. Fail2Ban recommended: `failregex = ^<HOST>.*401`",
        "patterns": {}
    },
    "honeypot": {
        "default": "Honeypot path triggered. IP automatically blocked. Known malicious scanning activity.",
        "patterns": {}
    },
}

# Status code specific advice
STATUS_ADVICE = {
    200: "⚠️ CRITICAL: Resource was served! Immediately check if sensitive data was leaked.",
    403: "✓ Access denied - correctly configured.",
    404: "✓ Resource not found - no action needed.",
    401: "Authentication required - login attempt failed.",
    500: "Server error on request - check logs.",
}


def get_recommendation(event: dict) -> str:
    """Get a static security recommendation based on the event type and details."""
    reason = event.get("reason", "")
    details = event.get("details", "")
    status_code = event.get("status_code")

    # Get base recommendation for this reason
    reason_config = RECOMMENDATIONS.get(reason, {"default": "Unknown attack type.", "patterns": {}})
    recommendation = reason_config["default"]

    # Check for specific patterns in details
    for pattern, advice in reason_config.get("patterns", {}).items():
        if re.search(pattern, details, re.IGNORECASE):
            recommendation = advice
            break

    # Add status code specific advice
    if status_code and status_code in STATUS_ADVICE:
        recommendation = f"{STATUS_ADVICE[status_code]} {recommendation}"

    return recommendation


def get_recommendation_for_display(reason: str, details: str = "", status_code: int = None) -> str:
    """Simplified function for display purposes."""
    return get_recommendation({
        "reason": reason,
        "details": details,
        "status_code": status_code,
    })
