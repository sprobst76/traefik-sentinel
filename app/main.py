import asyncio
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, desc
from app.config import HOST, PORT
from app.database import init_db, SessionLocal, AccessLog, IntruderEvent, BlockedIP
from app.log_watcher import watcher
from app.geoip import lookup_batch, get_cached, country_code_to_flag
from app.digest import send_digest


@lru_cache(maxsize=1000)
def resolve_ip(ip: str) -> str:
    """Reverse DNS lookup for IP address. Cached."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, socket.timeout):
        return ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    watcher.start()
    yield
    # Shutdown
    watcher.stop()


app = FastAPI(title="Traefik Dashboard", lifespan=lifespan)

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/stats")
async def get_stats(hours: int = Query(default=24, ge=1, le=168)):
    """Get overall statistics."""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        total_requests = db.query(func.count(AccessLog.id)).filter(
            AccessLog.timestamp >= since
        ).scalar() or 0

        unique_ips = db.query(func.count(func.distinct(AccessLog.ip))).filter(
            AccessLog.timestamp >= since
        ).scalar() or 0

        error_requests = db.query(func.count(AccessLog.id)).filter(
            AccessLog.timestamp >= since,
            AccessLog.status >= 400
        ).scalar() or 0

        avg_duration = db.query(func.avg(AccessLog.duration_ms)).filter(
            AccessLog.timestamp >= since
        ).scalar() or 0

        intruder_count = db.query(func.count(IntruderEvent.id)).filter(
            IntruderEvent.timestamp >= since
        ).scalar() or 0

        return {
            "total_requests": total_requests,
            "unique_ips": unique_ips,
            "error_requests": error_requests,
            "error_rate": round((error_requests / total_requests * 100) if total_requests > 0 else 0, 2),
            "avg_duration_ms": round(avg_duration, 2),
            "intruder_events": intruder_count,
            "period_hours": hours,
        }
    finally:
        db.close()


@app.get("/api/stats/services")
async def get_service_stats(hours: int = Query(default=24, ge=1, le=168)):
    """Get statistics per service/router."""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        results = db.query(
            AccessLog.router,
            func.count(AccessLog.id).label("count"),
            func.avg(AccessLog.duration_ms).label("avg_duration"),
        ).filter(
            AccessLog.timestamp >= since,
            AccessLog.router.isnot(None),
            AccessLog.router != "-"
        ).group_by(AccessLog.router).order_by(desc("count")).limit(20).all()

        return [
            {
                "service": r.router.split("@")[0] if r.router else "unknown",
                "router": r.router,
                "requests": r.count,
                "avg_duration_ms": round(r.avg_duration, 2) if r.avg_duration else 0,
            }
            for r in results
        ]
    finally:
        db.close()


@app.get("/api/stats/hosts")
async def get_host_stats(hours: int = Query(default=24, ge=1, le=168)):
    """Get statistics per host/subdomain."""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        results = db.query(
            AccessLog.host,
            func.count(AccessLog.id).label("count"),
            func.avg(AccessLog.duration_ms).label("avg_duration"),
        ).filter(
            AccessLog.timestamp >= since,
            AccessLog.host.isnot(None),
            AccessLog.host != ""
        ).group_by(AccessLog.host).order_by(desc("count")).limit(20).all()

        return [
            {
                "host": r.host,
                "requests": r.count,
                "avg_duration_ms": round(r.avg_duration, 2) if r.avg_duration else 0,
            }
            for r in results
        ]
    finally:
        db.close()


@app.get("/api/stats/ips")
async def get_top_ips(hours: int = Query(default=24, ge=1, le=168), limit: int = Query(default=10, ge=1, le=50)):
    """Get top IPs by request count with security assessment."""
    from sqlalchemy import case

    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        # Query with success/error breakdown
        results = db.query(
            AccessLog.ip,
            func.count(AccessLog.id).label("count"),
            func.count(func.distinct(AccessLog.path)).label("unique_paths"),
            func.sum(case((AccessLog.status.between(200, 299), 1), else_=0)).label("success_count"),
            func.sum(case((AccessLog.status.between(400, 499), 1), else_=0)).label("client_errors"),
            func.sum(case((AccessLog.status >= 500, 1), else_=0)).label("server_errors"),
        ).filter(
            AccessLog.timestamp >= since
        ).group_by(AccessLog.ip).order_by(desc("count")).limit(limit).all()

        # Get intruder event counts per IP
        intruder_counts = dict(
            db.query(IntruderEvent.ip, func.count(IntruderEvent.id))
            .filter(IntruderEvent.timestamp >= since)
            .group_by(IntruderEvent.ip)
            .all()
        )

        # Get blocked IPs
        blocked_ips = set(
            r.ip for r in db.query(BlockedIP.ip).filter(BlockedIP.active == 1).all()
        )

        # Get GeoIP info for all IPs in batch
        all_ips = [r.ip for r in results]
        geoip_data = await lookup_batch(all_ips)

        ip_stats = []
        for r in results:
            total = r.count
            success = r.success_count or 0
            client_err = r.client_errors or 0
            intruder_events = intruder_counts.get(r.ip, 0)

            # Calculate security risk
            risk_score = 0
            risk_reasons = []

            # High error rate is suspicious
            error_rate = (client_err / total * 100) if total > 0 else 0
            if error_rate > 50:
                risk_score += 2
                risk_reasons.append(f"{error_rate:.0f}% errors")

            # Intruder events are very suspicious
            if intruder_events > 0:
                risk_score += min(intruder_events, 3)
                risk_reasons.append(f"{intruder_events} alert{'s' if intruder_events > 1 else ''}")

            # Many unique paths with few successes = scanning
            if r.unique_paths > 10 and success < 5:
                risk_score += 2
                risk_reasons.append("Scanner behavior")

            # Determine risk level
            if risk_score >= 4:
                risk_level = "high"
                risk_label = "High Risk"
            elif risk_score >= 2:
                risk_level = "medium"
                risk_label = "Suspicious"
            else:
                risk_level = "low"
                risk_label = "Normal"

            # Get GeoIP info
            geo = geoip_data.get(r.ip, {})

            ip_stats.append({
                "ip": r.ip,
                "hostname": resolve_ip(r.ip),
                "requests": total,
                "unique_paths": r.unique_paths,
                "success_count": success,
                "error_count": client_err,
                "intruder_events": intruder_events,
                "risk_level": risk_level,
                "risk_label": risk_label,
                "risk_reasons": risk_reasons,
                "is_blocked": r.ip in blocked_ips,
                "country_code": geo.get("country_code", ""),
                "country": geo.get("country", ""),
                "flag": geo.get("flag", ""),
            })

        return ip_stats
    finally:
        db.close()


@app.get("/api/stats/status")
async def get_status_stats(hours: int = Query(default=24, ge=1, le=168)):
    """Get status code distribution."""
    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        results = db.query(
            AccessLog.status,
            func.count(AccessLog.id).label("count"),
        ).filter(
            AccessLog.timestamp >= since
        ).group_by(AccessLog.status).order_by(AccessLog.status).all()

        return [{"status": r.status, "count": r.count} for r in results]
    finally:
        db.close()


@app.get("/api/logs/recent")
async def get_recent_logs(limit: int = Query(default=50, ge=1, le=200)):
    """Get most recent log entries."""
    db = SessionLocal()
    try:
        results = db.query(AccessLog).order_by(desc(AccessLog.timestamp)).limit(limit).all()

        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "ip": r.ip,
                "hostname": resolve_ip(r.ip),
                "method": r.method,
                "path": r.path[:100],
                "status": r.status,
                "duration_ms": r.duration_ms,
                "router": r.router,
                "host": r.host,
            }
            for r in results
        ]
    finally:
        db.close()


@app.get("/api/intruders")
async def get_intruders(hours: int = Query(default=24, ge=1, le=168), limit: int = Query(default=50, ge=1, le=200)):
    """Get recent intruder events grouped by IP."""
    from app.security_advisor import get_recommendation

    db = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        results = db.query(IntruderEvent).filter(
            IntruderEvent.timestamp >= since
        ).order_by(desc(IntruderEvent.timestamp)).limit(limit * 5).all()

        # Group by IP
        grouped = {}
        for r in results:
            if r.ip not in grouped:
                grouped[r.ip] = {
                    "ip": r.ip,
                    "hostname": resolve_ip(r.ip),
                    "events": [],
                    "first_seen": r.timestamp,
                    "last_seen": r.timestamp,
                    "hosts": set(),
                    "reasons": set(),
                }
            group = grouped[r.ip]

            # Get recommendation (cached or generate static)
            rec = r.recommendation
            if not rec:
                rec = get_recommendation({
                    "reason": r.reason,
                    "details": r.details,
                    "status_code": r.status_code,
                })

            group["events"].append({
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "reason": r.reason,
                "details": r.details,
                "status_code": r.status_code,
                "host": r.host,
                "recommendation": rec,
            })
            if r.timestamp < group["first_seen"]:
                group["first_seen"] = r.timestamp
            if r.timestamp > group["last_seen"]:
                group["last_seen"] = r.timestamp
            if r.host:
                group["hosts"].add(r.host)
            group["reasons"].add(r.reason)

        # Get GeoIP info for all IPs in batch
        all_ips = list(grouped.keys())
        geoip_data = await lookup_batch(all_ips)

        # Convert to list and format
        result_list = []
        for ip, group in grouped.items():
            geo = geoip_data.get(ip, {})
            result_list.append({
                "ip": group["ip"],
                "hostname": group["hostname"],
                "event_count": len(group["events"]),
                "first_seen": group["first_seen"].isoformat(),
                "last_seen": group["last_seen"].isoformat(),
                "hosts": list(group["hosts"]),
                "reasons": list(group["reasons"]),
                "events": group["events"][:10],  # Limit events per IP
                "country_code": geo.get("country_code", ""),
                "country": geo.get("country", ""),
                "flag": geo.get("flag", ""),
            })

        # Sort by last_seen descending
        result_list.sort(key=lambda x: x["last_seen"], reverse=True)
        return result_list[:limit]
    finally:
        db.close()


@app.post("/api/intruders/{event_id}/recommendation")
async def get_recommendation_endpoint(event_id: int, use_ollama: bool = False):
    """Get security recommendation for a specific event."""
    from app.security_advisor import get_recommendation

    db = SessionLocal()
    try:
        event = db.query(IntruderEvent).filter(IntruderEvent.id == event_id).first()
        if not event:
            return {"error": "Event not found"}

        # Check if we already have a recommendation
        if event.recommendation:
            return {"recommendation": event.recommendation, "cached": True}

        # Get static recommendation (fast, no external dependency)
        event_dict = {
            "reason": event.reason,
            "details": event.details,
            "status_code": event.status_code,
        }
        recommendation = get_recommendation(event_dict)

        # Optionally enhance with Ollama for deeper analysis
        if use_ollama:
            try:
                from app.ollama_advisor import get_security_recommendation
                ollama_rec = get_security_recommendation({
                    "reason": event.reason,
                    "ip": event.ip,
                    "details": event.details,
                    "status_code": event.status_code,
                    "host": event.host,
                })
                if ollama_rec:
                    recommendation = f"{recommendation}\n\n🤖 KI-Analyse: {ollama_rec}"
            except Exception as e:
                print(f"Ollama failed: {e}")

        # Save recommendation
        event.recommendation = recommendation
        db.commit()

        return {"recommendation": recommendation, "cached": False}
    finally:
        db.close()


# ============== IP Blocklist API ==============

@app.get("/api/blocklist")
async def get_blocklist():
    """Get all blocked IPs and CIDR ranges."""
    db = SessionLocal()
    try:
        results = db.query(BlockedIP).filter(BlockedIP.active == 1).order_by(BlockedIP.blocked_at.desc()).all()

        # Get GeoIP info for non-CIDR entries
        single_ips = [r.ip for r in results if not getattr(r, 'is_cidr', 0) and '/' not in r.ip]
        geoip_data = await lookup_batch(single_ips) if single_ips else {}

        blocklist = []
        for r in results:
            is_cidr = bool(getattr(r, 'is_cidr', 0)) or '/' in r.ip
            geo = geoip_data.get(r.ip, {}) if not is_cidr else {}

            blocklist.append({
                "id": r.id,
                "ip": r.ip,
                "reason": r.reason,
                "blocked_at": r.blocked_at.isoformat(),
                "blocked_until": r.blocked_until.isoformat() if r.blocked_until else None,
                "is_cidr": is_cidr,
                "block_count": getattr(r, 'block_count', 1),
                "abuse_score": getattr(r, 'abuse_score', None),
                "auto_blocked": bool(getattr(r, 'auto_blocked', 0)),
                "permanent": r.blocked_until is None,
                "country_code": geo.get("country_code", ""),
                "country": geo.get("country", ""),
                "flag": geo.get("flag", ""),
            })

        return blocklist
    finally:
        db.close()


@app.post("/api/blocklist")
async def block_ip_endpoint(
    ip: str,
    reason: str = None,
    hours: int = None,
    report_abuse: bool = False,
    is_cidr: bool = False
):
    """Block an IP address or CIDR range and optionally report to AbuseIPDB."""
    from app.blocklist import block_ip as do_block_ip

    db = SessionLocal()
    try:
        # Get abuse score if we're checking
        abuse_score = None
        if report_abuse:
            from app.abuseipdb import check_ip, is_configured
            if is_configured() and not is_cidr:
                check_result = await check_ip(ip)
                if check_result and "abuse_score" in check_result:
                    abuse_score = check_result["abuse_score"]

        # Block the IP
        result = do_block_ip(
            db=db,
            ip=ip,
            reason=reason,
            abuse_score=abuse_score,
            auto_blocked=False,
            duration_hours=hours
        )

        # Report to AbuseIPDB if requested and successful
        if result.get("success") and report_abuse and not is_cidr:
            from app.abuseipdb import report_ip, is_configured
            if is_configured():
                report_result = await report_ip(
                    ip=ip,
                    categories=["web_app_attack", "hacking"],
                    comment=reason or "Malicious activity detected via Traefik Dashboard"
                )
                result["abuseipdb_report"] = report_result

        return result
    finally:
        db.close()


@app.delete("/api/blocklist/{ip:path}")
async def unblock_ip_endpoint(ip: str):
    """Unblock an IP address or CIDR range."""
    from app.blocklist import unblock_ip as do_unblock_ip

    db = SessionLocal()
    try:
        return do_unblock_ip(db, ip)
    finally:
        db.close()


@app.get("/api/blocklist/export")
async def export_blocklist():
    """Export blocklist for ipset sync."""
    db = SessionLocal()
    try:
        results = db.query(BlockedIP).filter(BlockedIP.active == 1).all()
        return "\n".join([r.ip for r in results])
    finally:
        db.close()


@app.post("/api/blocklist/cleanup")
async def cleanup_expired_blocks():
    """Manually trigger cleanup of expired blocks."""
    from app.blocklist import cleanup_expired_blocks as do_cleanup

    db = SessionLocal()
    try:
        count = do_cleanup(db)
        return {"success": True, "removed": count}
    finally:
        db.close()


@app.get("/api/blocklist/check/{ip}")
async def check_ip_blocked(ip: str):
    """Check if an IP is blocked (directly or via CIDR)."""
    from app.blocklist import is_ip_blocked_by_cidr

    db = SessionLocal()
    try:
        # Check direct block
        direct = db.query(BlockedIP).filter(
            BlockedIP.ip == ip,
            BlockedIP.active == 1
        ).first()

        if direct:
            return {
                "blocked": True,
                "type": "direct",
                "reason": direct.reason,
                "blocked_until": direct.blocked_until.isoformat() if direct.blocked_until else None
            }

        # Check CIDR coverage
        cidr_block = is_ip_blocked_by_cidr(db, ip)
        if cidr_block:
            return {
                "blocked": True,
                "type": "cidr",
                "cidr": cidr_block.ip,
                "reason": cidr_block.reason
            }

        return {"blocked": False}
    finally:
        db.close()


# ============== AbuseIPDB API ==============

@app.get("/api/abuseipdb/status")
async def abuseipdb_status():
    """Check if AbuseIPDB is configured."""
    from app.abuseipdb import is_configured
    return {"configured": is_configured()}


@app.get("/api/abuseipdb/check/{ip}")
async def check_ip_abuse(ip: str):
    """Check IP reputation in AbuseIPDB."""
    from app.abuseipdb import check_ip, get_risk_assessment, is_configured

    if not is_configured():
        return {"error": "AbuseIPDB API key not configured"}

    result = await check_ip(ip)
    if result and "error" not in result:
        risk_level, recommendation = get_risk_assessment(result.get("abuse_score", 0))
        result["risk_level"] = risk_level
        result["recommendation"] = recommendation

    return result


@app.post("/api/abuseipdb/report")
async def report_ip_abuse(ip: str, reason: str = None, categories: str = "web_app_attack,hacking"):
    """Report an IP to AbuseIPDB."""
    from app.abuseipdb import report_ip, is_configured

    if not is_configured():
        return {"error": "AbuseIPDB API key not configured"}

    category_list = [c.strip() for c in categories.split(",")]
    comment = reason or "Malicious activity detected"

    return await report_ip(ip, category_list, comment)


# ============== Log Retention API ==============

@app.get("/api/retention/stats")
async def retention_stats():
    """Get database statistics for retention planning."""
    from app.config import (
        RETENTION_ACCESS_LOGS_DAYS,
        RETENTION_INTRUDER_EVENTS_DAYS,
        RETENTION_BLOCKED_IPS_INACTIVE_DAYS,
    )

    db = SessionLocal()
    try:
        # Count rows per table
        access_count = db.query(func.count(AccessLog.id)).scalar() or 0
        intruder_count = db.query(func.count(IntruderEvent.id)).scalar() or 0
        blocked_count = db.query(func.count(BlockedIP.id)).scalar() or 0
        blocked_active = db.query(func.count(BlockedIP.id)).filter(BlockedIP.active == 1).scalar() or 0

        # Get date ranges
        access_oldest = db.query(func.min(AccessLog.timestamp)).scalar()
        intruder_oldest = db.query(func.min(IntruderEvent.timestamp)).scalar()

        # Calculate what would be deleted
        from datetime import timedelta
        access_cutoff = datetime.utcnow() - timedelta(days=RETENTION_ACCESS_LOGS_DAYS)
        intruder_cutoff = datetime.utcnow() - timedelta(days=RETENTION_INTRUDER_EVENTS_DAYS)
        blocked_cutoff = datetime.utcnow() - timedelta(days=RETENTION_BLOCKED_IPS_INACTIVE_DAYS)

        access_to_delete = db.query(func.count(AccessLog.id)).filter(
            AccessLog.timestamp < access_cutoff
        ).scalar() or 0

        intruder_to_delete = db.query(func.count(IntruderEvent.id)).filter(
            IntruderEvent.timestamp < intruder_cutoff
        ).scalar() or 0

        blocked_to_delete = db.query(func.count(BlockedIP.id)).filter(
            BlockedIP.active == 0,
            BlockedIP.blocked_at < blocked_cutoff
        ).scalar() or 0

        return {
            "retention_settings": {
                "access_logs_days": RETENTION_ACCESS_LOGS_DAYS,
                "intruder_events_days": RETENTION_INTRUDER_EVENTS_DAYS,
                "blocked_ips_inactive_days": RETENTION_BLOCKED_IPS_INACTIVE_DAYS,
            },
            "current_counts": {
                "access_logs": access_count,
                "intruder_events": intruder_count,
                "blocked_ips_total": blocked_count,
                "blocked_ips_active": blocked_active,
            },
            "oldest_entries": {
                "access_logs": access_oldest.isoformat() if access_oldest else None,
                "intruder_events": intruder_oldest.isoformat() if intruder_oldest else None,
            },
            "pending_cleanup": {
                "access_logs": access_to_delete,
                "intruder_events": intruder_to_delete,
                "blocked_ips_inactive": blocked_to_delete,
            },
        }
    finally:
        db.close()


@app.post("/api/retention/cleanup")
async def retention_cleanup(dry_run: bool = False):
    """
    Clean up old log entries based on retention settings.
    Use dry_run=true to see what would be deleted without actually deleting.
    """
    from app.config import (
        RETENTION_ACCESS_LOGS_DAYS,
        RETENTION_INTRUDER_EVENTS_DAYS,
        RETENTION_BLOCKED_IPS_INACTIVE_DAYS,
    )

    db = SessionLocal()
    try:
        from datetime import timedelta
        now = datetime.utcnow()

        access_cutoff = now - timedelta(days=RETENTION_ACCESS_LOGS_DAYS)
        intruder_cutoff = now - timedelta(days=RETENTION_INTRUDER_EVENTS_DAYS)
        blocked_cutoff = now - timedelta(days=RETENTION_BLOCKED_IPS_INACTIVE_DAYS)

        results = {}

        # Access logs
        access_query = db.query(AccessLog).filter(AccessLog.timestamp < access_cutoff)
        access_count = access_query.count()
        if not dry_run and access_count > 0:
            access_query.delete(synchronize_session=False)
        results["access_logs_deleted"] = access_count

        # Intruder events
        intruder_query = db.query(IntruderEvent).filter(IntruderEvent.timestamp < intruder_cutoff)
        intruder_count = intruder_query.count()
        if not dry_run and intruder_count > 0:
            intruder_query.delete(synchronize_session=False)
        results["intruder_events_deleted"] = intruder_count

        # Inactive blocked IPs (keep active ones!)
        blocked_query = db.query(BlockedIP).filter(
            BlockedIP.active == 0,
            BlockedIP.blocked_at < blocked_cutoff
        )
        blocked_count = blocked_query.count()
        if not dry_run and blocked_count > 0:
            blocked_query.delete(synchronize_session=False)
        results["blocked_ips_deleted"] = blocked_count

        if not dry_run:
            db.commit()
            # Vacuum to reclaim space (must be outside transaction)
            try:
                from sqlalchemy import text
                db.execute(text("VACUUM"))
            except:
                pass  # VACUUM may fail in some contexts, that's ok

        results["dry_run"] = dry_run
        results["success"] = True

        return results
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@app.post("/api/digest/send")
async def trigger_digest():
    """Manually trigger digest send. Returns status dict per D-17.
    Unauthenticated by design — operator firewalls the port (matches /api/blocklist)."""
    return await send_digest()


@app.get("/api/stream")
async def stream_logs():
    """Server-Sent Events endpoint for live log updates."""
    async def event_generator():
        queue = asyncio.Queue()

        def on_new_log(log):
            try:
                queue.put_nowait({
                    "timestamp": log.timestamp.isoformat(),
                    "ip": log.ip,
                    "hostname": resolve_ip(log.ip),
                    "method": log.method,
                    "path": log.path[:100],
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "router": log.router,
                    "host": log.host,
                })
            except asyncio.QueueFull:
                pass

        watcher.add_callback(on_new_log)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"
        finally:
            watcher.new_log_callbacks.remove(on_new_log)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
