import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.postgres.risk_models import Inventory, HedgeAllocation, Trade

logger = logging.getLogger("darkflow.risk.hedge")

class HedgeManager:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def allocate_hedge(self, asset: str, amount: Decimal, price: Decimal, hedge_type: str = "INTERNAL"):
        inv_stmt = select(Inventory).where(Inventory.asset == asset)
        inv = await self.session.execute(inv_stmt)
        inventory = inv.scalar_one_or_none()
        if inventory:
            inventory.hedge_position += amount
            inventory.net_exposure = inventory.net_client_position + inventory.hedge_position
        else:
            self.session.add(Inventory(asset=asset, hedge_position=amount, net_exposure=amount))

        allocation = HedgeAllocation(asset=asset, hedge_type=hedge_type, amount=amount, price=price)
        self.session.add(allocation)

        trade = Trade(
            asset=asset, side="HEDGE", price=price, volume=amount, is_hedge=True
        )
        self.session.add(trade)
        await self.session.commit()
        logger.info(f"Hedge allocated: {asset} {amount} @ {price} ({hedge_type})")
        return allocation

    async def get_inventory(self, asset: str = None) -> list[dict]:
        stmt = select(Inventory)
        if asset:
            stmt = stmt.where(Inventory.asset == asset)
        result = await self.session.execute(stmt)
        invs = result.scalars().all()
        return [
            {
                "asset": i.asset,
                "net_client": float(i.net_client_position),
                "hedge": float(i.hedge_position),
                "net_exposure": float(i.net_exposure),
                "last_updated": i.last_updated.isoformat()
            } for i in invs
        ]
