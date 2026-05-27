"""
DARKFLOW OTC — API Routes: Candles
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from database.postgres.connection import get_db
from database.postgres.models import Candle

logger = logging.getLogger("darkflow.api.candles")
router = APIRouter(prefix="/api/candles", tags=["Candles"])


@router.get("/")
async def list_candles(
    asset: str = Query("BTCUSD_otc"),
    limit: int = Query(100, le=1000),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candle)
        .where(Candle.asset == asset)
        .order_by(desc(Candle.ts))
        .limit(limit)
    )
    candles = result.scalars().all()
    return {"asset": asset, "count": len(candles), "candles": [c.to_dict() for c in candles]}


@router.get("/latest")
async def latest_candle(
    asset: str = Query("BTCUSD_otc"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candle).where(Candle.asset == asset).order_by(desc(Candle.ts)).limit(1)
    )
    candle = result.scalars().first()
    if not candle:
        raise HTTPException(status_code=404, detail="No candles found.")
    return candle.to_dict()


@router.get("/stats")
async def candle_stats(
    asset: str = Query("BTCUSD_otc"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Candle).where(Candle.asset == asset))
    candles = result.scalars().all()
    if not candles:
        return {"asset": asset, "total": 0}
    closes = [float(c.close) for c in candles]
    return {
        "asset": asset,
        "total": len(candles),
        "price_min": round(min(closes), 8),
        "price_max": round(max(closes), 8),
        "price_avg": round(sum(closes) / len(closes), 8),
    }
