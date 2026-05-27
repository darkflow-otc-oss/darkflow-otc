"""
DARKFLOW OTC — SQLAlchemy Models
ORM para candles, patterns, sessions e probabilities.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean,
    DateTime, JSON, ARRAY, Text, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Candle(Base):
    __tablename__ = "candles"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset      = Column(String(50), nullable=False, index=True)
    timeframe  = Column(Integer, nullable=False, default=60)
    ts         = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    open       = Column(Numeric(18, 8), nullable=False)
    high       = Column(Numeric(18, 8), nullable=False)
    low        = Column(Numeric(18, 8), nullable=False)
    close      = Column(Numeric(18, 8), nullable=False)
    volume     = Column(Numeric(18, 8), default=0)
    source     = Column(String(30), default="websocket")
    session_id = Column(String(50))
    raw        = Column(JSONB)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "asset": self.asset,
            "timeframe": self.timeframe,
            "ts": self.ts.isoformat() if self.ts else None,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume or 0),
        }

    def __repr__(self):
        return f"<Candle {self.asset} {self.ts} O={self.open} C={self.close}>"


class Pattern(Base):
    __tablename__ = "patterns"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pattern_type      = Column(String(80), nullable=False, index=True)
    asset             = Column(String(50), nullable=False, index=True)
    detected_at       = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    features          = Column(JSONB)
    continuation_rate = Column(Numeric(5, 4), default=0)
    reversal_rate     = Column(Numeric(5, 4), default=0)
    false_break_rate  = Column(Numeric(5, 4), default=0)
    strength          = Column(Numeric(5, 4), default=0)
    frequency         = Column(Integer, default=1)
    cluster_id        = Column(String(50))
    vector_id         = Column(String(100))
    confirmed         = Column(Boolean, default=False)
    outcome           = Column(String(20))
    pnl               = Column(Numeric(10, 4))
    created_at        = Column(TIMESTAMP(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Pattern {self.pattern_type} {self.asset} strength={self.strength}>"


class CaptureSession(Base):
    __tablename__ = "capture_sessions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id     = Column(String(50), unique=True, nullable=False)
    started_at     = Column(TIMESTAMP(timezone=True), nullable=False)
    ended_at       = Column(TIMESTAMP(timezone=True))
    asset          = Column(String(50))
    messages_total = Column(Integer, default=0)
    candles_total  = Column(Integer, default=0)
    status         = Column(String(20), default="active")
    metadata_      = Column("metadata", JSONB)
    created_at     = Column(TIMESTAMP(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Session {self.session_id} {self.status}>"


class Probability(Base):
    __tablename__ = "probabilities"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pattern_type = Column(String(80), nullable=False, index=True)
    asset        = Column(String(50), nullable=False)
    direction    = Column(String(20), nullable=False)
    probability  = Column(Numeric(5, 4), nullable=False)
    sample_size  = Column(Integer, nullable=False)
    computed_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())
    valid_until  = Column(TIMESTAMP(timezone=True))
    metadata_    = Column("metadata", JSONB)

    def __repr__(self):
        return f"<Probability {self.pattern_type} {self.direction}={self.probability}>"


class RawTick(Base):
    __tablename__ = "raw_ticks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset       = Column(String(50), nullable=False, index=True)
    session_id  = Column(String(50))
    ts          = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    direction   = Column(String(10))
    ws_url      = Column(String(500))
    seq         = Column(Integer)
    data        = Column(JSONB)
    recorded_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<RawTick {self.asset} seq={self.seq}>"
