"""
DARKFLOW OTC — Data Access Layer
Repository assíncrono para todas as tabelas do sistema.
"""

import logging
from uuid import UUID
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.postgres.models import RawTick, Candle, Pattern

logger = logging.getLogger("darkflow.database.repositories")


async def insert_raw_tick(session: AsyncSession, tick_data: dict) -> RawTick:
    """Insere um tick bruto na tabela raw_ticks."""
    stmt = (
        pg_insert(RawTick)
        .values(
            asset=tick_data.get("asset", "unknown"),
            session_id=tick_data.get("session_id", ""),
            ts=tick_data.get("ts", datetime.utcnow().isoformat()),
            direction=tick_data.get("direction", "received"),
            ws_url=tick_data.get("ws_url", ""),
            seq=tick_data.get("seq", 0),
            data=tick_data.get("data", {}),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    await session.commit()
    logger.debug(f"📌 RawTick inserted: {tick_data.get('asset')} seq={tick_data.get('seq')}")
    return RawTick(
        asset=tick_data.get("asset", "unknown"),
        session_id=tick_data.get("session_id", ""),
        ts=tick_data.get("ts", datetime.utcnow().isoformat()),
        direction=tick_data.get("direction", "received"),
        ws_url=tick_data.get("ws_url", ""),
        seq=tick_data.get("seq", 0),
        data=tick_data.get("data", {}),
    )


async def get_latest_candles(
    session: AsyncSession,
    asset: str,
    timeframe: int = 60,
    limit: int = 100,
) -> list[Candle]:
    """Busca os últimos N candles para um ativo + timeframe."""
    stmt = (
        select(Candle)
        .where(Candle.asset == asset, Candle.timeframe == timeframe)
        .order_by(Candle.ts.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    logger.debug(f"🕯  get_latest_candles: {asset} tf={timeframe}s → {len(rows)} rows")
    return list(rows)


async def insert_pattern(session: AsyncSession, pattern_data: dict) -> Pattern:
    """Insere um padrão detectado na tabela patterns."""
    pattern = Pattern(
        pattern_type=pattern_data.get("pattern_type", "unknown"),
        asset=pattern_data.get("asset", "unknown"),
        detected_at=pattern_data.get("detected_at", datetime.utcnow()),
        features=pattern_data.get("features"),
        continuation_rate=pattern_data.get("continuation_rate", 0),
        reversal_rate=pattern_data.get("reversal_rate", 0),
        false_break_rate=pattern_data.get("false_break_rate", 0),
        strength=pattern_data.get("strength", 0),
        frequency=pattern_data.get("frequency", 1),
        cluster_id=pattern_data.get("cluster_id"),
        vector_id=pattern_data.get("vector_id"),
        confirmed=pattern_data.get("confirmed", False),
    )
    session.add(pattern)
    await session.commit()
    await session.refresh(pattern)
    logger.info(f"📊 Pattern inserted: {pattern.pattern_type} {pattern.asset} id={pattern.id}")
    return pattern


async def get_patterns_by_asset(
    session: AsyncSession,
    asset: str,
    limit: int = 50,
) -> list[Pattern]:
    """Busca os últimos padrões detectados para um ativo."""
    stmt = (
        select(Pattern)
        .where(Pattern.asset == asset)
        .order_by(Pattern.detected_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    logger.debug(f"🔍 get_patterns_by_asset: {asset} → {len(rows)} patterns")
    return list(rows)


async def update_pattern_outcome(
    session: AsyncSession,
    pattern_id: UUID,
    outcome: str,
    pnl: float = 0.0,
) -> Pattern | None:
    """Atualiza o resultado (WIN/LOSS) e PnL de um padrão."""
    stmt = select(Pattern).where(Pattern.id == pattern_id)
    result = await session.execute(stmt)
    pattern = result.scalar_one_or_none()

    if pattern is None:
        logger.warning(f"⚠️  Pattern {pattern_id} not found for outcome update.")
        return None

    pattern.outcome = outcome
    pattern.pnl = pnl
    pattern.confirmed = True
    await session.commit()
    await session.refresh(pattern)
    logger.info(f"✅ Pattern {pattern_id} outcome={outcome} pnl={pnl}")
    return pattern
