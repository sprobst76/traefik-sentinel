"""Static security recommendations for common attack patterns."""

import re

# Recommendations by attack type
RECOMMENDATIONS = {
    "suspicious_path": {
        "default": "Automatisierter Scanner. Keine Aktion nötig wenn Status 404. Bei Status 200: Prüfen ob sensible Dateien exponiert sind.",
        "patterns": {
            r"\.env": "⚠️ .env-Zugriff! Sicherstellen dass keine .env-Dateien im Web-Root liegen. In nginx: `location ~ /\\. { deny all; }`",
            r"\.git": "⚠️ Git-Repository-Scan! .git-Ordner dürfen nicht öffentlich sein. Bei Status 200: Secrets rotieren! Nginx: `location ~ /\\.git { deny all; }`",
            r"wp-login|wp-admin|wp-content": "WordPress-Scanner. Ignorieren wenn kein WordPress installiert. Sonst: Login-URL ändern, Fail2Ban für wp-login.",
            r"phpmyadmin|pma": "phpMyAdmin-Scanner. Ignorieren wenn nicht installiert. Sonst: Zugriff auf IP beschränken oder entfernen.",
            r"config\.php|config\.yml": "Config-Datei-Scan. Sicherstellen dass Konfigurationsdateien nicht im Web-Root liegen.",
            r"shell|backdoor|c99|r57": "Webshell-Scanner. Keine Aktion nötig wenn Status 404.",
        }
    },
    "sql_injection": {
        "default": "SQL-Injection Versuch. Sicherstellen dass alle DB-Queries parametrisiert sind. WAF-Regel für SQL-Patterns empfohlen.",
        "patterns": {
            r"union.*select": "UNION-based SQLi. Bei dynamischen Queries: Prepared Statements verwenden.",
            r"or\s+1\s*=\s*1": "Boolean-based SQLi. Input-Validierung und Prepared Statements prüfen.",
        }
    },
    "rate_limit": {
        "default": "Zu viele Requests von dieser IP. Möglicher Bot/Scraper oder DDoS. Bei Bedarf IP temporär blockieren.",
        "patterns": {}
    },
    "auth_failures": {
        "default": "Mehrfache Login-Fehlversuche. Möglicher Brute-Force. Fail2Ban empfohlen: `failregex = ^<HOST>.*401`",
        "patterns": {}
    },
}

# Status code specific advice
STATUS_ADVICE = {
    200: "⚠️ KRITISCH: Ressource wurde ausgeliefert! Sofort prüfen ob sensible Daten geleakt wurden.",
    403: "✓ Zugriff verweigert - korrekt konfiguriert.",
    404: "✓ Ressource nicht gefunden - kein Handlungsbedarf.",
    401: "Authentifizierung erforderlich - Login-Versuch fehlgeschlagen.",
    500: "Server-Fehler bei Anfrage - Logs prüfen.",
}


def get_recommendation(event: dict) -> str:
    """Get a static security recommendation based on the event type and details."""
    reason = event.get("reason", "")
    details = event.get("details", "")
    status_code = event.get("status_code")

    # Get base recommendation for this reason
    reason_config = RECOMMENDATIONS.get(reason, {"default": "Unbekannter Angriffstyp.", "patterns": {}})
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
