import logging
from uuid import UUID
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from database.postgres.risk_models import Order, Trade
from database.postgres.models import Candle

logger = logging.getLogger("darkflow.risk.orderbook")

class OrderBookService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def place_order(self, asset: str, side: str, amount: Decimal,
                          order_type: str = "MARKET", price: Decimal = None,
                          is_institutional: bool = False, client_id: str = None) -> Order:
        order = Order(
            asset=asset, side=side, amount=amount,
            order_type=order_type, price=price,
            is_institutional=is_institutional, client_id=client_id
        )
        self.session.add(order)
        await self.session.flush()

        if order_type == "MARKET":
            mark_price = await self._get_mark_price(asset)
            trade = Trade(
                order_id=order.id, asset=asset, side=side,
                price=mark_price, volume=amount, is_hedge=False
            )
            self.session.add(trade)
            order.status = "FILLED"
            order.filled_at = func.now()
            await self.session.commit()
            logger.info(f"Market order filled: {order.id} {side} {amount} @ {mark_price}")
        else:
            await self.session.commit()
            logger.info(f"Limit order placed: {order.id}")
        return order

    async def cancel_order(self, order_id: UUID) -> bool:
        stmt = select(Order).where(Order.id == order_id, Order.status == "PENDING")
        result = await self.session.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            return False
        order.status = "CANCELLED"
        await self.session.commit()
        logger.info(f"Order cancelled: {order_id}")
        return True

    async def get_order_book(self, asset: str) -> dict:
        stmt = select(Order).where(Order.asset == asset, Order.status == "PENDING")
        result = await self.session.execute(stmt)
        orders = result.scalars().all()
        bids = [{"price": float(o.price), "amount": float(o.amount)} for o in orders if o.side in ("CALL", "BUY")]
        asks = [{"price": float(o.price), "amount": float(o.amount)} for o in orders if o.side in ("PUT", "SELL")]
        return {"asset": asset, "bids": bids, "asks": asks}

    async def _get_mark_price(self, asset: str) -> Decimal:
        stmt = select(Candle).where(Candle.asset == asset).order_by(Candle.ts.desc()).limit(1)
        result = await self.session.execute(stmt)
        candle = result.scalar_one_or_none()
        return Decimal(str(candle.close)) if candle else Decimal("1.0")
