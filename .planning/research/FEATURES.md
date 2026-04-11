# Feature Landscape: Security Alert Notification Management

**Domain:** Security monitoring notification system for self-hosted reverse proxy
**Researched:** 2026-04-11
**Milestone context:** Improving notification quality in an existing Traefik Sentinel dashboard

---

## Current State (Baseline)

The existing `telegram_alerter.py` sends one Telegram message per intruder event with a
15-minute per-IP/reason cooldown. `auto_blocker.py` sends additional messages for honeypot
blocks and AbuseIPDB-triggered auto-blocks. On an internet-facing server this produces
dozens to hundreds of individual Telegram messages daily from routine scanner traffic —
the canonical definition of alert fatigue.

The codebase already has:
- Five severity-mapped threat types: `sql_injection` (critical), `honeypot` (critical),
  `auth_failures` (high), `rate_limit` (medium), `suspicious_path` (medium)
- Request-count escalation logic in `get_severity_header()`
- A 15-minute in-memory cooldown keyed on `(ip, reason)` in `IntruderDetector`
- AbuseIPDB score gating in `auto_blocker.py`

What is missing is the routing layer that decides *which events get an immediate ping*
vs. *which events are batched into a summary*.

---

## Table Stakes

Features users of this class of tool expect. Missing any of these and users disable
notifications entirely (the failure mode Traefik Sentinel is currently heading toward).

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Severity-gated immediate alerts** | Industry standard since Nagios/PagerDuty era. Critical-only paging is the first thing every on-call guide recommends. | Low | Severity mapping already exists in `THREAT_SEVERITY`. Need routing logic that reads it. |
| **Configurable severity threshold** | Operators have different risk tolerances. A single hardcoded threshold is wrong for everyone. | Low | One env var: `ALERT_MIN_SEVERITY` with values `critical\|high\|medium`. |
| **Per-event cooldown / deduplication** | Receiving 50 messages about the same scanner IP is useless. The existing 15-min cooldown is table stakes but the window is too short for non-critical events. | Low | Already implemented; extend cooldown for medium/low severity to 1-4 hours. |
| **Daily digest** | Neither Fail2Ban nor CrowdSec (free) offer this natively — it is the most-requested feature in self-hosted security tooling. Operators want one message per day, not hundreds. | Medium | Scheduled task; queries SQLite for events in the past N hours; sends one formatted Telegram message. |
| **Digest only when there is activity** | Empty "all quiet" digests train users to ignore the digest message entirely. | Low | Count events before sending; skip if zero. |
| **Configurable digest schedule** | 08:00 UTC is wrong for someone in a different timezone or with a different workflow. | Low | Env var: `DIGEST_CRON` or `DIGEST_HOUR`. |

**Complexity baseline for "table stakes" set:** All items are Low-Medium. No new
infrastructure, no new libraries beyond a scheduler.

---

## Differentiators

Features that go beyond what comparable tools offer (Fail2Ban, CrowdSec free, NetAlertX).
These create real value without adding significant operational burden.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Digest with top-N attacker table** | Context transforms a count into an actionable summary. Showing "5 events" is table stakes; showing "Top attacker: 1.2.3.4 (CN) — 23 SQL injection attempts, auto-blocked" is useful. | Medium | Requires aggregation query on `intruder_events` grouped by IP. |
| **Attack type breakdown in digest** | "47 suspicious path scans, 3 SQL injections, 1 honeypot trigger" lets the operator understand whether the day was noise or signal without opening the dashboard. | Low | GROUP BY reason query on the digest window. |
| **Block count summary in digest** | "8 IPs auto-blocked, 0 manual blocks" closes the loop: the operator knows the automated response worked. | Low | Query `blocked_ips` table filtered to digest window. |
| **Escalation for repeat offenders** | If the same IP triggers alerts 3+ times across separate cooldown windows, escalate to immediate alert even for medium severity. Matches industry "risk score escalation" pattern seen in Splunk/Elastic SIEM. | Medium | Requires event count query at alert time; 24h window already exists in `auto_blocker.py`. |
| **First-seen vs. known-bad distinction in digest** | Flagging new IPs (never seen before) vs. known-bad IPs (previously blocked, re-appearing) helps prioritize review. | Medium | Cross-reference `blocked_ips` table in digest query. |

---

## Anti-Features

Features that appear useful but create more problems than they solve in this context.
Build these and you will regret it.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Quiet hours / time-based suppression** | Suppressing critical alerts at night is the mistake that leads to breaches going undetected. The 2025 Unit 42 Global Incident Response Report traced 13% of social engineering incidents to ignored security alerts. For a single-operator self-hosted setup, the correct behavior is: critical alerts always fire, non-critical always go to digest. Time windows add complexity without safety. | Use severity filtering: medium/low always go to digest regardless of time. |
| **Per-event messages for auto-blocks** | Auto-blocks are the *success case* — the system worked. Sending a message for each auto-block on a busy server generates noise about things that are already handled. This is exactly the problem stated in PROJECT.md. | Include auto-block count in digest. Only send immediate alert if auto-block *fails* for a critical threat. |
| **Alert suppression rules / silences** | Prometheus Alertmanager-style silence rules require a UI, persistent storage, and ongoing maintenance. For a single-operator tool, they introduce "stale suppression" risk (rules that persist past their intended scope, silencing real threats silently). | If an IP is whitelisted, don't generate events at all. Keep the whitelist model. |
| **Multi-channel routing (email, Slack, webhook)** | The project constraint is "no new notification channels." Adding channels fragments attention and doubles the maintenance surface. CrowdSec's paid Console offers this; Traefik Sentinel is not trying to be CrowdSec. | Telegram is the chosen channel. Do it well. |
| **Per-recipient severity routing** | Enterprise SIEM feature (route critical to on-call, medium to team channel). This is a single-operator homelab tool. Multiple recipients = scope creep. | Single `TELEGRAM_CHAT_ID`. Keep it simple. |
| **ML-based anomaly detection or risk scoring** | The PROJECT.md explicitly states "additional detection patterns are out of scope." AI-driven triage is the 2026 enterprise trend but is architectural overkill for a 500-line Python app. | Use the existing deterministic severity mapping. It is sufficient. |
| **Delivery receipts / acknowledgement workflow** | PagerDuty-style "ack this alert to suppress escalation" adds state management, timers, and re-notification logic. For a homelab dashboard it creates more overhead than value. | Telegram read receipts are sufficient signal. |

---

## Feature Dependencies

```
Configurable severity threshold
    --> Severity-gated immediate alerts
            --> Escalation for repeat offenders (reads severity + event count)

Daily digest
    --> Digest only when there is activity (guard on digest)
    --> Attack type breakdown in digest (aggregation query)
    --> Top-N attacker table in digest (aggregation query)
    --> Block count summary in digest (additional query)
    --> First-seen vs. known-bad distinction (cross-reference query)

Configurable digest schedule
    --> Daily digest (scheduler needs the configured time)

Per-event cooldown (already exists)
    --> Severity-gated immediate alerts (cooldown window should vary by severity)
```

**Critical path for MVP:** Severity threshold env var + routing logic + daily digest + digest
schedule env var. Everything else is additive.

---

## MVP Recommendation

Prioritize in this order:

1. **Severity-gated immediate alerts** — one env var + routing check before calling
   `send_telegram_alert()`. Stops the flood immediately. Unblocks everything else.

2. **Configurable severity threshold** (`ALERT_MIN_SEVERITY`, default: `critical`) — lets
   the operator tune without code changes.

3. **Daily digest** — scheduled task, SQLite aggregation queries, single formatted Telegram
   message. Core value of the milestone.

4. **Digest schedule config** (`DIGEST_HOUR` env var, default: `8` for 08:00 UTC) — makes
   the digest usable across timezones.

5. **Digest only when there is activity** — trivial guard, prevents "all quiet" habituation.

6. **Attack type breakdown + block count in digest** — two additional GROUP BY queries;
   transforms a count into an actionable summary. Low complexity, high value.

Defer:

- **Top-N attacker table**: Medium complexity; add in a follow-up once basic digest works.
- **Escalation for repeat offenders**: Requires careful threshold tuning to avoid re-introducing
  noise; defer until digest is validated in production.
- **First-seen vs. known-bad distinction**: Useful but adds query complexity; not MVP.

---

## Implementation Notes for Downstream Requirements

### Scheduler choice
Python's `asyncio` event loop is already running (FastAPI). A simple `asyncio.create_task()`
with a sleep loop is sufficient for the digest scheduler. No APScheduler or Celery needed.
The `retention.py` module likely uses a similar pattern and can serve as a reference.

### Severity routing contract
The `THREAT_SEVERITY` dict in `telegram_alerter.py` is the single source of truth. The
routing function should read from it (with the request-count escalation already present)
and compare against `ALERT_MIN_SEVERITY`. Non-qualifying events should still be saved to
`intruder_events` in the database — they feed the digest.

### Digest query scope
The digest window should be configurable as a corollary of the schedule. A daily digest
at 08:00 should cover the past 24 hours. The SQLite `intruder_events` and `blocked_ips`
tables already contain the required data.

### Backwards compatibility constraint
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` must continue to work unchanged. New env vars
must have safe defaults: `ALERT_MIN_SEVERITY=critical`, `DIGEST_HOUR=8` (to send at 08:00
UTC), and `DIGEST_ENABLED=true`.

---

## Sources

- Alert fatigue industry data and suppression design principles: [Alert fatigue solutions for DevOps teams in 2025 | incident.io](https://incident.io/blog/alert-fatigue-solutions-for-dev-ops-teams-in-2025-what-works), [Alert Suppression Best Practices | upstat.io](https://upstat.io/blog/alert-suppression-best-practices), [Alert Fatigue Is Killing Your SOC (2026) | Torq](https://torq.io/blog/cybersecurity-alert-management-2026/)
- Priority-tier suppression model (critical bypass, medium dedup): [Prometheus Alertmanager Noise-Reduction | Netdata Academy](https://www.netdata.cloud/academy/prometheus-alert-manager/), [Google Security Operations alert suppression docs](https://docs.cloud.google.com/chronicle/docs/investigation/alert-suppression)
- Fail2Ban / CrowdSec digest feature gap (neither offers native daily digest in free tier): [CrowdSec vs Fail2Ban comparison | LetsHosting](https://www.letshosting.com/16626.html), [fail2ban vs CrowdSec vs Defensia | DEV Community](https://dev.to/defensia/fail2ban-vs-crowdsec-vs-defensia-an-honest-comparison-14hk)
- Self-hosted homelab IDS feature expectations: [Case Study: Self-Hosted Security Monitoring | techbuddies.io](https://www.techbuddies.io/2025/12/18/case-study-self-hosted-security-monitoring-for-a-linux-vps-homelab/), [Securing Your Homelab | excalibursheath.com](https://excalibursheath.com/guide/2025/09/07/homelab-security-automation-monitoring.html)
- Grafana Alertmanager grouping and mute timing patterns: [Grafana Alerting fundamentals](https://grafana.com/docs/grafana/latest/alerting/fundamentals/)
- Risk of ignored alerts leading to breaches: [Palo Alto Networks alert fatigue guide](https://www.paloaltonetworks.com/cyberpedia/how-to-reduce-security-alert-fatigue), [Preventing Alert Fatigue | Splunk](https://www.splunk.com/en_us/blog/learn/alert-fatigue.html)
