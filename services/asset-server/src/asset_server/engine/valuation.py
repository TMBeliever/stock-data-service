from typing import List, Dict, Any
from asset_server.models import AssetItem, AssetCategory
from asset_server.providers.factory import get_market_data_provider
from asset_server.engine.fx import get_fx_rates


async def calculate_assets_valuation(items: List[AssetItem]) -> Dict[str, Any]:
    """
    全品类基础资产估值与基本盘核算引擎
    1. 动态拉取证券类标的现价；
    2. 拉取实时汇率字典，支持多币种 (USD, HKD, EUR, JPY 等) 折算为本位币 (CNY)；
    3. 计算总资产、总负债、真实净资产 (净资产 = 总资产 - 总负债)；
    4. 汇聚单项标的现价、原币市值、折合人民币市值与浮动盈亏；
    5. 计算大类资产分布汇总。
    """
    provider = get_market_data_provider()
    fx_rates = await get_fx_rates()

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
        curr = (item.currency or "CNY").strip().upper()
        fx_rate = fx_rates.get(curr, 1.0)

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

        # 原始币种估值
        market_val_raw = round(amt * current_price, 2)
        cost_val_raw = round(amt * cost, 2)
        pnl_raw = round(market_val_raw - cost_val_raw, 2)
        pnl_pct = round((pnl_raw / cost_val_raw) * 100, 2) if cost_val_raw > 0 else 0.0

        # 基准本位币 (CNY) 汇率折算值
        market_val_cny = round(market_val_raw * fx_rate, 2)
        cost_val_cny = round(cost_val_raw * fx_rate, 2)
        pnl_cny = round(market_val_cny - cost_val_cny, 2)

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
            # 基准折合人民币 (用于跨品类统一汇总与排序)
            "market_value": market_val_cny,
            "cost_value": cost_val_cny,
            "unrealized_pnl": pnl_cny,
            "unrealized_pnl_pct": pnl_pct,
            # 原币种数值与汇率
            "currency": curr,
            "fx_rate": fx_rate,
            "market_val_raw": market_val_raw,
            "cost_val_raw": cost_val_raw,
            "pnl_raw": pnl_raw,
            "note": item.note,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        enriched_items.append(item_dict)

        # 归集大类 (按折合本位币 CNY 汇总)
        if cat == AssetCategory.LIABILITY.value:
            total_liabilities += market_val_cny
            cat_stat = category_summary[cat]
            cat_stat["total_value"] = round(cat_stat["total_value"] + market_val_cny, 2)
            cat_stat["total_cost"] = round(cat_stat["total_cost"] + cost_val_cny, 2)
            cat_stat["count"] += 1
        else:
            total_assets += market_val_cny
            total_asset_cost += cost_val_cny
            cat_stat = category_summary.get(cat)
            if cat_stat:
                cat_stat["total_value"] = round(cat_stat["total_value"] + market_val_cny, 2)
                cat_stat["total_cost"] = round(cat_stat["total_cost"] + cost_val_cny, 2)
                cat_stat["unrealized_pnl"] = round(cat_stat["unrealized_pnl"] + pnl_cny, 2)
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
            "base_currency": "CNY",
            "fx_rates": fx_rates,
        },
        "categories": active_categories,
        "items": enriched_items,
    }

