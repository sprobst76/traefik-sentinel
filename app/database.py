from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Index
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_PATH

# Ensure data directory exists
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    ip = Column(String(45), nullable=False, index=True)
    user = Column(String(255), nullable=True)
    method = Column(String(10), nullable=False)
    path = Column(String(2048), nullable=False)
    protocol = Column(String(20), nullable=False)
    status = Column(Integer, nullable=False, index=True)
    bytes = Column(Integer, nullable=False)
    referer = Column(String(2048), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    request_num = Column(Integer, nullable=True)
    router = Column(String(255), nullable=True, index=True)
    backend = Column(String(255), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    host = Column(String(255), nullable=True, index=True)  # Requested hostname

    __table_args__ = (
        Index("idx_timestamp_ip", "timestamp", "ip"),
        Index("idx_router_timestamp", "router", "timestamp"),
        Index("idx_host_timestamp", "host", "timestamp"),
    )


class IntruderEvent(Base):
    __tablename__ = "intruder_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    ip = Column(String(45), nullable=False, index=True)
    reason = Column(String(255), nullable=False)
    details = Column(String(2048), nullable=True)
    request_count = Column(Integer, nullable=True)
    alerted = Column(Integer, default=0)
    status_code = Column(Integer, nullable=True)
    host = Column(String(255), nullable=True)
    recommendation = Column(String(2048), nullable=True)


class BlockedIP(Base):
    __tablename__ = "blocked_ips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String(45), nullable=False, unique=True, index=True)  # IP or CIDR notation
    reason = Column(String(255), nullable=True)
    blocked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    blocked_until = Column(DateTime, nullable=True)  # None = permanent
    active = Column(Integer, default=1)  # 1 = active, 0 = unblocked
    is_cidr = Column(Integer, default=0)  # 1 = CIDR range, 0 = single IP
    block_count = Column(Integer, default=1)  # Number of times this IP was blocked
    abuse_score = Column(Integer, nullable=True)  # AbuseIPDB score at time of block
    auto_blocked = Column(Integer, default=0)  # 1 = auto-blocked, 0 = manual


class DigestEvent(Base):
    __tablename__ = "digest_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    source = Column(String(20), nullable=False)       # "intruder" | "auto_block"
    source_id = Column(Integer, nullable=False)       # logical FK to intruder_events.id or blocked_ips.id
    severity = Column(String(10), nullable=False)     # "critical" | "high" | "medium"
    sent_at = Column(DateTime, nullable=True, index=True)  # NULL = pending


def init_db():
    Base.metadata.create_all(engine)
    # Run migrations for new columns
    _migrate_blocked_ips_table()


def _migrate_blocked_ips_table():
    """Add new columns to blocked_ips if they don't exist."""
    from sqlalchemy import text

    with engine.connect() as conn:
        # Check existing columns
        result = conn.execute(text("PRAGMA table_info(blocked_ips)"))
        existing_cols = {row[1] for row in result.fetchall()}

        migrations = [
            ("is_cidr", "INTEGER DEFAULT 0"),
            ("block_count", "INTEGER DEFAULT 1"),
            ("abuse_score", "INTEGER"),
            ("auto_blocked", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                try:
                    conn.execute(text(f"ALTER TABLE blocked_ips ADD COLUMN {col_name} {col_def}"))
                    conn.commit()
                    print(f"Migration: Added column {col_name}")
                except Exception as e:
                    print(f"Migration warning for {col_name}: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
