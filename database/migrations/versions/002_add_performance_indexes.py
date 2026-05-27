"""add_performance_indexes

Revision ID: 002
Revises: 001
Create Date: 2026-05-26

Índices compostos de performance:
- raw_ticks: (asset, ts DESC)
- candles: (asset, timeframe, ts DESC)
- patterns: (asset, pattern_type, detected_at DESC)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # raw_ticks — consultas por asset + timestamp recente
    op.create_index(
        "idx_raw_ticks_asset_ts",
        "raw_ticks",
        ["asset", sa.text("ts DESC")],
    )

    # candles — consultas por asset, timeframe e timestamp
    op.create_index(
        "idx_candles_asset_tf_ts",
        "candles",
        ["asset", "timeframe", sa.text("ts DESC")],
    )

    # patterns — consultas por asset, tipo e data de detecção
    op.create_index(
        "idx_patterns_asset_type_detected",
        "patterns",
        ["asset", "pattern_type", sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_patterns_asset_type_detected", table_name="patterns")
    op.drop_index("idx_candles_asset_tf_ts", table_name="candles")
    op.drop_index("idx_raw_ticks_asset_ts", table_name="raw_ticks")
