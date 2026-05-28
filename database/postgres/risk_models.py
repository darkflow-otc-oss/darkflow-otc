"""Modelos de risco, ordem, hedge e P&L"""
from sqlalchemy import Column, String, Numeric, Boolean, TIMESTAMP, ForeignKey, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from database.postgres.models import Base
import uuid

class Order(Base):
    __tablename__ = "orders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), default="MARKET")
    price = Column(Numeric(18,8), nullable=True)
    amount = Column(Numeric(18,8), nullable=False)
    is_institutional = Column(Boolean, default=False)
    status = Column(String(20), default="PENDING")
    client_id = Column(String(50), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    filled_at = Column(TIMESTAMP(timezone=True), nullable=True)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"))
    asset = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)
    price = Column(Numeric(18,8), nullable=False)
    volume = Column(Numeric(18,8), nullable=False)
    is_hedge = Column(Boolean, default=False)
    executed_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class Inventory(Base):
    __tablename__ = "inventory"
    asset = Column(String(50), primary_key=True)
    net_client_position = Column(Numeric(18,8), default=0)
    hedge_position = Column(Numeric(18,8), default=0)
    net_exposure = Column(Numeric(18,8), default=0)
    last_updated = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

class RiskMetrics(Base):
    __tablename__ = "risk_metrics"
    asset = Column(String(50), primary_key=True)
    total_call_volume = Column(Numeric(18,8), default=0)
    total_put_volume = Column(Numeric(18,8), default=0)
    imbalance_ratio = Column(Numeric(10,6), default=0)
    current_payout_call = Column(Numeric(5,4), default=0.85)
    current_payout_put = Column(Numeric(5,4), default=0.85)
    exposure_usd = Column(Numeric(18,2), default=0)
    exposure_limit = Column(Numeric(18,2), default=100000)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now())

class HedgeAllocation(Base):
    __tablename__ = "hedge_allocations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset = Column(String(50), nullable=False)
    hedge_type = Column(String(20), nullable=False)
    amount = Column(Numeric(18,8), nullable=False)
    price = Column(Numeric(18,8), nullable=False)
    allocated_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset = Column(String(50), nullable=False)
    realized_pnl = Column(Numeric(18,2), default=0)
    unrealized_pnl = Column(Numeric(18,2), default=0)
    total_pnl = Column(Numeric(18,2), default=0)
    snapshot_time = Column(TIMESTAMP(timezone=True), server_default=func.now())
