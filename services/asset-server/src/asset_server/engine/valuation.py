from typing import List, Dict, Any
from asset_server.models import AssetItem, AssetCategory
from asset_server.providers.factory import get_market_data_provider


async def calculate_assets_valuation(items: List[AssetItem]) -> Dict[str, Any]:
    """
    全品类基础资产估值与基本盘核算引擎
    1. 动态拉取证券类标的现价；
    2. 计算总资产、总负债、真实净资产 (净资产 = 总资产 - 总负债)；
    3. 汇聚单项标的现价、市值与浮动盈亏；
    4. 计算大类资产分布汇总。
    """
    provider = get_market_data_provider()

    # 1. 提取所有具备行情代码的标的
    symbols = list(set(item.symbol.strip() for item in items if item.symbol and item.symbol.strip()))
    quotes_map = await provider.get_batch_quotes(symbols) if symbols else {}

    total_assets = 0.0
    total_liabilities = 0.0
    total_asset_cost = 0.0

    category_summary: Dict[str, Dict[str, Any]] = {}
    for cat in AssetCategory:
        category_summary[cat.value] = {
            "category": cat.value,
            "total_value": 0.0,
            "total_cost": 0.0,
            "unrealized_pnl": 0.0,
            "count": 0,
            "percentage": 0.0,
        }

    enriched_items = []

    for item in items:
        cat = item.category
        amt = float(item.amount or 0.0)
        cost = float(item.cost_price or 0.0)

        # 估值单价决定逻辑
        current_price = cost
        change_pct = 0.0
        prev_close = cost

        if item.symbol and item.symbol in quotes_map:
            snap = quotes_map[item.symbol]
            current_price = snap.price
            change_pct = snap.change_pct
            prev_close = snap.prev_close
        elif item.manual_price is not None:
            current_price = float(item.manual_price)

        market_val = round(amt * current_price, 2)
        cost_val = round(amt * cost, 2)
        pnl = round(market_val - cost_val, 2)
        pnl_pct = round((pnl / cost_val) * 100, 2) if cost_val > 0 else 0.0

        item_dict = {
            "id": item.id,
            "user_id": item.user_id,
            "category": item.category,
            "name": item.name,
            "symbol": item.symbol,
            "amount": amt,
            "cost_price": cost,
            "manual_price": item.manual_price,
            "current_price": current_price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "market_value": market_val,
            "cost_value": cost_val,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "currency": item.currency,
            "note": item.note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        enriched_items.append(item_dict)

        # 归集大类
        if cat == AssetCategory.LIABILITY.value:
            total_liabilities += market_val
            cat_stat = category_summary[cat]
            cat_stat["total_value"] = round(cat_stat["total_value"] + market_val, 2)
            cat_stat["total_cost"] = round(cat_stat["total_cost"] + cost_val, 2)
            cat_stat["count"] += 1
        else:
            total_assets += market_val
            total_asset_cost += cost_val
            cat_stat = category_summary.get(cat)
            if cat_stat:
                cat_stat["total_value"] = round(cat_stat["total_value"] + market_val, 2)
                cat_stat["total_cost"] = round(cat_stat["total_cost"] + cost_val, 2)
                cat_stat["unrealized_pnl"] = round(cat_stat["unrealized_pnl"] + pnl, 2)
                cat_stat["count"] += 1

    total_assets = round(total_assets, 2)
    total_liabilities = round(total_liabilities, 2)
    total_asset_cost = round(total_asset_cost, 2)
    net_worth = round(total_assets - total_liabilities, 2)
    total_unrealized_pnl = round(total_assets - total_asset_cost, 2)
    total_return_pct = round((total_unrealized_pnl / total_asset_cost) * 100, 2) if total_asset_cost > 0 else 0.0

    # 计算大类占比 (基于总资产)
    for cat_data in category_summary.values():
        val = cat_data["total_value"]
        if total_assets > 0 and cat_data["category"] != AssetCategory.LIABILITY.value:
            cat_data["percentage"] = round((val / total_assets) * 100, 2)
        else:
            cat_data["percentage"] = 0.0

    # 仅过滤出包含实际资产或负债的大类
    active_categories = [c for c in category_summary.values() if c["count"] > 0]

    return {
        "summary": {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "net_worth": net_worth,
            "total_cost": total_asset_cost,
            "unrealized_pnl": total_unrealized_pnl,
            "return_pct": total_return_pct,
            "item_count": len(items),
        },
        "categories": active_categories,
        "items": enriched_items,
    }
