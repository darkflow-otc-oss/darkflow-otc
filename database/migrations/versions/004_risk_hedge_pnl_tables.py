"""add_risk_hedge_pnl_tables

Revision ID: 004
Revises: 003
Create Date: 2026-05-28
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table('orders',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('asset', sa.String(50), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('order_type', sa.String(20), server_default='MARKET'),
        sa.Column('price', sa.Numeric(18,8), nullable=True),
        sa.Column('amount', sa.Numeric(18,8), nullable=False),
        sa.Column('is_institutional', sa.Boolean, server_default='false'),
        sa.Column('status', sa.String(20), server_default='PENDING'),
        sa.Column('client_id', sa.String(50)),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('filled_at', sa.TIMESTAMP(timezone=True)),
    )
    op.create_index('idx_orders_asset', 'orders', ['asset'])
    op.create_index('idx_orders_status', 'orders', ['status'])

    op.create_table('trades',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('order_id', UUID(as_uuid=True)),
        sa.Column('asset', sa.String(50), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('price', sa.Numeric(18,8), nullable=False),
        sa.Column('volume', sa.Numeric(18,8), nullable=False),
        sa.Column('is_hedge', sa.Boolean, server_default='false'),
        sa.Column('executed_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_foreign_key('fk_trades_order', 'trades', 'orders', ['order_id'], ['id'])

    op.create_table('inventory',
        sa.Column('asset', sa.String(50), primary_key=True),
        sa.Column('net_client_position', sa.Numeric(18,8), server_default='0'),
        sa.Column('hedge_position', sa.Numeric(18,8), server_default='0'),
        sa.Column('net_exposure', sa.Numeric(18,8), server_default='0'),
        sa.Column('last_updated', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table('risk_metrics',
        sa.Column('asset', sa.String(50), primary_key=True),
        sa.Column('total_call_volume', sa.Numeric(18,8), server_default='0'),
        sa.Column('total_put_volume', sa.Numeric(18,8), server_default='0'),
        sa.Column('imbalance_ratio', sa.Numeric(10,6), server_default='0'),
        sa.Column('current_payout_call', sa.Numeric(5,4), server_default='0.85'),
        sa.Column('current_payout_put', sa.Numeric(5,4), server_default='0.85'),
        sa.Column('exposure_usd', sa.Numeric(18,2), server_default='0'),
        sa.Column('exposure_limit', sa.Numeric(18,2), server_default='100000'),
        sa.Column('timestamp', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table('hedge_allocations',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('asset', sa.String(50), nullable=False),
        sa.Column('hedge_type', sa.String(20), nullable=False),
        sa.Column('amount', sa.Numeric(18,8), nullable=False),
        sa.Column('price', sa.Numeric(18,8), nullable=False),
        sa.Column('allocated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table('pnl_snapshots',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('asset', sa.String(50), nullable=False),
        sa.Column('realized_pnl', sa.Numeric(18,2), server_default='0'),
        sa.Column('unrealized_pnl', sa.Numeric(18,2), server_default='0'),
        sa.Column('total_pnl', sa.Numeric(18,2), server_default='0'),
        sa.Column('snapshot_time', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table('pnl_snapshots')
    op.drop_table('hedge_allocations')
    op.drop_table('risk_metrics')
    op.drop_table('inventory')
    op.drop_table('trades')
    op.drop_table('orders')
