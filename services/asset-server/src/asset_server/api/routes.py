from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from asset_server.database import get_db
from asset_server.models import AssetItem, AssetCategory
from asset_server.engine.valuation import calculate_assets_valuation

router = APIRouter()


def resolve_user_id(x_user_id: Optional[str] = Header(None, alias="x-user-id")) -> int:
    """提取经过统一网关校验注入的当前用户 ID，本地独立开发测试默认回退至 1"""
    if x_user_id:
        try:
            return int(x_user_id)
        except ValueError:
            pass
    return 1


# =========================================================================
# Pydantic 请求与响应模型
# =========================================================================
class AssetCreateRequest(BaseModel):
    category: AssetCategory = Field(default=AssetCategory.EQUITY, description="资产大类")
    name: str = Field(..., max_length=128, description="资产名称 (如: 沪深300 ETF, 招商银行存款)")
    symbol: Optional[str] = Field(None, max_length=64, description="标的代码 (股票/ETF类填写，现金/房产留空)")
    amount: float = Field(default=1.0, ge=0, description="持有数量/份额/本金")
    cost_price: float = Field(default=0.0, ge=0, description="买入成本均价 (单价)")
    manual_price: Optional[float] = Field(None, ge=0, description="手动估值单价 (无行情代码资产使用)")
    currency: str = Field(default="CNY", max_length=8, description="计价币种")
    note: Optional[str] = Field(None, max_length=512, description="备注信息")


class AssetUpdateRequest(BaseModel):
    category: Optional[AssetCategory] = None
    name: Optional[str] = Field(None, max_length=128)
    symbol: Optional[str] = Field(None, max_length=64)
    amount: Optional[float] = Field(None, ge=0)
    cost_price: Optional[float] = Field(None, ge=0)
    manual_price: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, max_length=8)
    note: Optional[str] = Field(None, max_length=512)


# =========================================================================
# 路由端点定义
# =========================================================================
@router.get("/health", tags=["System"])
async def health_check():
    """资产服务健康检查探针"""
    return {"status": "healthy", "service": "asset-server"}


@router.get("/api/v1/asset/overview", tags=["Asset Overview"])
async def get_asset_overview(
    user_id: int = Depends(resolve_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    【全景资产基本盘总览】
    返回用户的总资产、总负债、净资产（总资产 - 负债）、累计浮动盈亏以及各资产大类分布统计。
    """
    stmt = select(AssetItem).where(AssetItem.user_id == user_id).order_by(AssetItem.id.asc())
    res = await db.execute(stmt)
    items = list(res.scalars().all())

    valuation = await calculate_assets_valuation(items)
    return {
        "status": "success",
        "summary": valuation["summary"],
        "categories": valuation["categories"],
        "items": valuation["items"],
    }



@router.get("/api/v1/asset/items", tags=["Asset Management"])
async def list_asset_items(
    category: Optional[str] = Query(None, description="按大类筛选 (如 CASH, EQUITY, LIABILITY)"),
    user_id: int = Depends(resolve_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    【资产明细列表】
    查询名下资产明细，自动结合最新市场行情计算当前单价、市值与浮动盈亏。
    """
    stmt = select(AssetItem).where(AssetItem.user_id == user_id)
    if category:
        stmt = stmt.where(AssetItem.category == category.upper())
    stmt = stmt.order_by(AssetItem.id.desc())

    res = await db.execute(stmt)
    items = list(res.scalars().all())

    valuation = await calculate_assets_valuation(items)
    return {
        "status": "success",
        "summary": valuation["summary"],
        "items": valuation["items"],
    }


@router.post("/api/v1/asset/items", tags=["Asset Management"])
async def create_asset_item(
    req: AssetCreateRequest,
    user_id: int = Depends(resolve_user_id),
    db: AsyncSession = Depends(get_db),
):
    """【新增资产】登记一笔新的资产或负债项目"""
    item = AssetItem(
        user_id=user_id,
        category=req.category.value,
        name=req.name.strip(),
        symbol=req.symbol.strip() if req.symbol else None,
        amount=req.amount,
        cost_price=req.cost_price,
        manual_price=req.manual_price,
        currency=req.currency.strip().upper(),
        note=req.note.strip() if req.note else None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    # 附带即时估值返回
    valuation = await calculate_assets_valuation([item])
    enriched = valuation["items"][0] if valuation["items"] else {}
    return {
        "status": "success",
        "message": "资产已成功添加",
        "data": enriched,
    }


@router.put("/api/v1/asset/items/{item_id}", tags=["Asset Management"])
async def update_asset_item(
    item_id: int,
    req: AssetUpdateRequest,
    user_id: int = Depends(resolve_user_id),
    db: AsyncSession = Depends(get_db),
):
    """【编辑资产】更新指定资产的份额、成本单价、估值或备注"""
    stmt = select(AssetItem).where(AssetItem.id == item_id, AssetItem.user_id == user_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="未找到该资产项或无权修改")

    if req.category is not None:
        item.category = req.category.value
    if req.name is not None:
        item.name = req.name.strip()
    if req.symbol is not None:
        item.symbol = req.symbol.strip() if req.symbol.strip() else None
    if req.amount is not None:
        item.amount = req.amount
    if req.cost_price is not None:
        item.cost_price = req.cost_price
    if req.manual_price is not None:
        item.manual_price = req.manual_price
    if req.currency is not None:
        item.currency = req.currency.strip().upper()
    if req.note is not None:
        item.note = req.note.strip() if req.note.strip() else None

    await db.commit()
    await db.refresh(item)

    valuation = await calculate_assets_valuation([item])
    enriched = valuation["items"][0] if valuation["items"] else {}
    return {
        "status": "success",
        "message": "资产已成功更新",
        "data": enriched,
    }


@router.delete("/api/v1/asset/items/{item_id}", tags=["Asset Management"])
async def delete_asset_item(
    item_id: int,
    user_id: int = Depends(resolve_user_id),
    db: AsyncSession = Depends(get_db),
):
    """【删除资产】移除指定的资产或负债项目"""
    stmt = select(AssetItem).where(AssetItem.id == item_id, AssetItem.user_id == user_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="未找到该资产项或无权删除")

    await db.delete(item)
    await db.commit()
    return {
        "status": "success",
        "message": "资产已成功移除",
        "id": item_id,
    }
