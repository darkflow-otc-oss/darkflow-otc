import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from database.postgres.risk_models import RiskMetrics, Trade, Inventory

logger = logging.getLogger("darkflow.risk.engine")

class RiskEngine:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def update_exposure(self, asset: str):
        stmt = select(
            func.coalesce(func.sum(Trade.volume).filter(Trade.side == "CALL", Trade.is_hedge == False), 0),
            func.coalesce(func.sum(Trade.volume).filter(Trade.side == "PUT", Trade.is_hedge == False), 0)
        ).where(Trade.asset == asset)
        result = await self.session.execute(stmt)
        call_vol, put_vol = result.one()
        call_vol = call_vol or Decimal(0)
        put_vol = put_vol or Decimal(0)
        total = call_vol + put_vol
        imbalance = (call_vol - put_vol) / total if total > 0 else Decimal(0)

        base = Decimal("0.85")
        payout_call = base * (Decimal(1) - max(Decimal(0), imbalance))
        payout_put = base * (Decimal(1) - max(Decimal(0), -imbalance))

        exposure = call_vol - put_vol

        inv_stmt = select(Inventory).where(Inventory.asset == asset)
        inv = await self.session.execute(inv_stmt)
        inventory = inv.scalar_one_or_none()
        if inventory:
            inventory.net_client_position = call_vol - put_vol
            inventory.net_exposure = inventory.net_client_position + inventory.hedge_position
            inventory.last_updated = func.now()
        else:
            self.session.add(Inventory(asset=asset, net_client_position=call_vol - put_vol))

        metrics = RiskMetrics(
            asset=asset,
            total_call_volume=call_vol,
            total_put_volume=put_vol,
            imbalance_ratio=imbalance,
            current_payout_call=payout_call,
            current_payout_put=payout_put,
            exposure_usd=exposure
        )
        await self.session.merge(metrics)
        await self.session.commit()
        return metrics

    async def get_payouts(self, asset: str) -> dict:
        stmt = select(RiskMetrics).where(RiskMetrics.asset == asset)
        result = await self.session.execute(stmt)
        metrics = result.scalar_one_or_none()
        if not metrics:
            return {"asset": asset, "call": 0.85, "put": 0.85}
        return {
            "asset": asset,
            "call": float(metrics.current_payout_call),
            "put": float(metrics.current_payout_put),
            "imbalance": float(metrics.imbalance_ratio)
        }
