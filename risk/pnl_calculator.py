import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.postgres.risk_models import Trade, Inventory, PnLSnapshot
from database.postgres.models import Candle

logger = logging.getLogger("darkflow.risk.pnl")

class PnLCalculator:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def compute_pnl(self, asset: str):
        stmt = select(Candle).where(Candle.asset == asset).order_by(Candle.ts.desc()).limit(1)
        result = await self.session.execute(stmt)
        candle = result.scalar_one_or_none()
        mark_price = Decimal(str(candle.close)) if candle else Decimal("1.0")

        inv_stmt = select(Inventory).where(Inventory.asset == asset)
        inv = await self.session.execute(inv_stmt)
        inventory = inv.scalar_one_or_none()
        if not inventory:
            return None

        avg_stmt = select(func.avg(Trade.price)).where(Trade.asset == asset, Trade.is_hedge == False)
        avg_res = await self.session.execute(avg_stmt)
        avg_price = avg_res.scalar_one() or mark_price

        unrealized = inventory.net_exposure * (mark_price - avg_price)

        snapshot = PnLSnapshot(
            asset=asset,
            unrealized_pnl=unrealized,
            total_pnl=unrealized
        )
        self.session.add(snapshot)
        await self.session.commit()
        return snapshot

    async def get_history(self, asset: str, limit: int = 20) -> list[dict]:
        stmt = select(PnLSnapshot).where(PnLSnapshot.asset == asset).order_by(PnLSnapshot.snapshot_time.desc()).limit(limit)
        result = await self.session.execute(stmt)
        snapshots = result.scalars().all()
        return [
            {
                "timestamp": s.snapshot_time.isoformat(),
                "realized": float(s.realized_pnl),
                "unrealized": float(s.unrealized_pnl),
                "total": float(s.total_pnl)
            } for s in snapshots
        ]
