"""add_pattern_outcome_pnl

Revision ID: 003
Revises: 002
Create Date: 2026-05-26

Adiciona colunas outcome e pnl à tabela patterns para
rastreamento de resultado do padrão (WIN/LOSS).
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("patterns", sa.Column("outcome", sa.String(20)))
    op.add_column("patterns", sa.Column("pnl", sa.Numeric(10, 4)))


def downgrade() -> None:
    op.drop_column("patterns", "pnl")
    op.drop_column("patterns", "outcome")
