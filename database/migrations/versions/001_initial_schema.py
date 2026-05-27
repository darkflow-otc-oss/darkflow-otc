"""initial_schema

Revision ID: 001
Revises: None
Create Date: 2026-05-26

Todas as tabelas do DARKFLOW OTC: candles, patterns, capture_sessions,
probabilities, raw_ticks.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # ── candles ──────────────────────────────────────────────────────────────
    op.create_table(
        "candles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("asset", sa.String(50), nullable=False, index=True),
        sa.Column("timeframe", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, index=True),
        sa.Column("open", sa.Numeric(18, 8), nullable=False),
        sa.Column("high", sa.Numeric(18, 8), nullable=False),
        sa.Column("low", sa.Numeric(18, 8), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.Column("volume", sa.Numeric(18, 8), server_default=sa.text("0")),
        sa.Column("source", sa.String(30), server_default="websocket"),
        sa.Column("session_id", sa.String(50)),
        sa.Column("raw", JSONB),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_candles_asset_ts", "candles", ["asset", sa.text("ts DESC")])
    op.create_index("idx_candles_ts", "candles", [sa.text("ts DESC")])
    op.create_unique_constraint("idx_candles_unique", "candles", ["asset", "timeframe", "ts"])

    # ── patterns ─────────────────────────────────────────────────────────────
    op.create_table(
        "patterns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("pattern_type", sa.String(80), nullable=False, index=True),
        sa.Column("asset", sa.String(50), nullable=False, index=True),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False, index=True),
        sa.Column("candle_ids", sa.ARRAY(UUID(as_uuid=True))),
        sa.Column("features", JSONB),
        sa.Column("continuation_rate", sa.Numeric(5, 4), server_default=sa.text("0")),
        sa.Column("reversal_rate", sa.Numeric(5, 4), server_default=sa.text("0")),
        sa.Column("false_break_rate", sa.Numeric(5, 4), server_default=sa.text("0")),
        sa.Column("strength", sa.Numeric(5, 4), server_default=sa.text("0")),
        sa.Column("frequency", sa.Integer, server_default=sa.text("1")),
        sa.Column("cluster_id", sa.String(50)),
        sa.Column("vector_id", sa.String(100)),
        sa.Column("confirmed", sa.Boolean, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_patterns_type", "patterns", ["pattern_type"])
    op.create_index("idx_patterns_asset", "patterns", ["asset"])
    op.create_index("idx_patterns_detected", "patterns", [sa.text("detected_at DESC")])

    # ── capture_sessions ─────────────────────────────────────────────────────
    op.create_table(
        "capture_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", sa.String(50), unique=True, nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("asset", sa.String(50)),
        sa.Column("messages_total", sa.Integer, server_default=sa.text("0")),
        sa.Column("candles_total", sa.Integer, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("metadata", JSONB),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    # ── probabilities ────────────────────────────────────────────────────────
    op.create_table(
        "probabilities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("pattern_type", sa.String(80), nullable=False, index=True),
        sa.Column("asset", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("probability", sa.Numeric(5, 4), nullable=False),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("valid_until", sa.TIMESTAMP(timezone=True)),
        sa.Column("metadata", JSONB),
    )
    op.create_index("idx_prob_pattern", "probabilities", ["pattern_type", "asset"])

    # ── raw_ticks ────────────────────────────────────────────────────────────
    op.create_table(
        "raw_ticks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("asset", sa.String(50), nullable=False, index=True),
        sa.Column("session_id", sa.String(50)),
        sa.Column("ts", sa.TIMESTAMP(timezone=True), nullable=False, index=True),
        sa.Column("direction", sa.String(10)),
        sa.Column("ws_url", sa.String(500)),
        sa.Column("seq", sa.Integer),
        sa.Column("data", JSONB),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("raw_ticks")
    op.drop_index("idx_prob_pattern", table_name="probabilities")
    op.drop_table("probabilities")
    op.drop_table("capture_sessions")
    op.drop_index("idx_patterns_detected", table_name="patterns")
    op.drop_index("idx_patterns_asset", table_name="patterns")
    op.drop_index("idx_patterns_type", table_name="patterns")
    op.drop_table("patterns")
    op.drop_index("idx_candles_unique", table_name="candles")
    op.drop_index("idx_candles_ts", table_name="candles")
    op.drop_index("idx_candles_asset_ts", table_name="candles")
    op.drop_table("candles")
