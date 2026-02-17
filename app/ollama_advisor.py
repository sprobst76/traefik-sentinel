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
        "suspicious_path": "Suspicious path access (scanner/bot)",
        "sql_injection": "SQL injection attempt",
        "rate_limit": "Rate limit exceeded (possible DDoS/brute-force)",
        "auth_failures": "Multiple authentication failures (possible brute-force)",
        "honeypot": "Honeypot path triggered",
    }
    reason_text = reason_labels.get(reason, reason)

    prompt = f"""You are an IT security expert for web server hardening. An attacker has performed the following suspicious activity. Provide a brief DEFENSIVE recommendation (1-2 sentences) on how the server admin can protect themselves.

Attack type: {reason_text}
Attacker IP: {ip}
Target host: {host}
HTTP status: {status_code}
Details: {details}

Reply ONLY with the protection recommendation, without introduction. Examples: Block IP, configure Fail2Ban, add WAF rule, etc."""

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
