import httpx
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")


def get_security_recommendation(event: dict) -> str:
    """Get a security recommendation from Ollama for an intruder event."""
    reason = event.get("reason", "unknown")
    ip = event.get("ip", "unknown")
    details = event.get("details", "")
    status_code = event.get("status_code", "unknown")
    host = event.get("host", "unknown")

    reason_labels = {
        "suspicious_path": "Verdächtiger Pfad-Zugriff (Scanner/Bot)",
        "sql_injection": "SQL-Injection Versuch",
        "rate_limit": "Rate-Limit überschritten (möglicher DDoS/Brute-Force)",
        "auth_failures": "Mehrfache Authentifizierungsfehler (möglicher Brute-Force)",
    }
    reason_text = reason_labels.get(reason, reason)

    prompt = f"""Du bist ein IT-Security-Experte für Webserver-Absicherung. Ein Angreifer hat folgende verdächtige Aktivität ausgeführt. Gib eine kurze DEFENSIVE Empfehlung (1-2 Sätze) wie der Server-Admin sich schützen kann.

Angriffstyp: {reason_text}
Angreifer-IP: {ip}
Ziel-Host: {host}
HTTP-Status: {status_code}
Details: {details}

Antworte NUR mit der Schutzempfehlung, ohne Einleitung. Beispiele: IP blockieren, Fail2Ban konfigurieren, WAF-Regel hinzufügen, etc."""

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 150,
                    }
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama request failed: {e}")

    return ""
