from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from decimal import Decimal
from uuid import UUID
from database.postgres.connection import get_db
from risk.order_book import OrderBookService
from risk.risk_engine import RiskEngine
from risk.hedge_manager import HedgeManager
from risk.pnl_calculator import PnLCalculator

router = APIRouter(prefix="/api/risk", tags=["Risk"])

class OrderRequest(BaseModel):
    asset: str
    side: str
    amount: float
    order_type: str = "MARKET"
    is_institutional: bool = False
    client_id: str = None

class HedgeRequest(BaseModel):
    asset: str
    amount: float
    price: float
    hedge_type: str = "INTERNAL"

@router.post("/order")
async def place_order(order: OrderRequest, db: AsyncSession = Depends(get_db)):
    service = OrderBookService(db)
    result = await service.place_order(
        asset=order.asset, side=order.side, amount=Decimal(str(order.amount)),
        order_type=order.order_type, is_institutional=order.is_institutional,
        client_id=order.client_id
    )
    return {"order_id": str(result.id), "status": result.status}

@router.post("/order/{order_id}/cancel")
async def cancel_order(order_id: UUID, db: AsyncSession = Depends(get_db)):
    service = OrderBookService(db)
    success = await service.cancel_order(order_id)
    if not success:
        raise HTTPException(404, "Order not found or already filled")
    return {"status": "cancelled"}

@router.get("/orderbook/{asset}")
async def get_order_book(asset: str, db: AsyncSession = Depends(get_db)):
    service = OrderBookService(db)
    book = await service.get_order_book(asset)
    return book

@router.get("/exposure/{asset}")
async def get_exposure(asset: str, db: AsyncSession = Depends(get_db)):
    engine = RiskEngine(db)
    metrics = await engine.update_exposure(asset)
    return {
        "asset": asset,
        "call_volume": float(metrics.total_call_volume),
        "put_volume": float(metrics.total_put_volume),
        "imbalance": float(metrics.imbalance_ratio),
        "payout_call": float(metrics.current_payout_call),
        "payout_put": float(metrics.current_payout_put),
        "exposure_usd": float(metrics.exposure_usd)
    }

@router.get("/payouts/{asset}")
async def get_payouts(asset: str, db: AsyncSession = Depends(get_db)):
    engine = RiskEngine(db)
    return await engine.get_payouts(asset)

@router.post("/hedge")
async def allocate_hedge(req: HedgeRequest, db: AsyncSession = Depends(get_db)):
    manager = HedgeManager(db)
    alloc = await manager.allocate_hedge(
        asset=req.asset, amount=Decimal(str(req.amount)),
        price=Decimal(str(req.price)), hedge_type=req.hedge_type
    )
    return {"allocation_id": str(alloc.id), "asset": req.asset, "amount": req.amount}

@router.get("/inventory")
async def get_inventory(asset: str = None, db: AsyncSession = Depends(get_db)):
    manager = HedgeManager(db)
    inv = await manager.get_inventory(asset)
    return inv

@router.get("/pnl/{asset}")
async def get_pnl(asset: str, db: AsyncSession = Depends(get_db)):
    calc = PnLCalculator(db)
    pnl = await calc.compute_pnl(asset)
    if not pnl:
        raise HTTPException(404, "No PnL data")
    return {
        "asset": asset,
        "unrealized_pnl": float(pnl.unrealized_pnl),
        "total_pnl": float(pnl.total_pnl),
        "timestamp": pnl.snapshot_time.isoformat()
    }

@router.get("/pnl/{asset}/history")
async def get_pnl_history(asset: str, limit: int = 20, db: AsyncSession = Depends(get_db)):
    calc = PnLCalculator(db)
    history = await calc.get_history(asset, limit)
    return history
