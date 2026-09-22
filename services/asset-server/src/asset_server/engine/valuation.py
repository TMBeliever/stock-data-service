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

        snap = None
        if item.symbol:
            sym_clean = item.symbol.strip()
            snap = quotes_map.get(sym_clean)
            if not snap:
                for k, v in quotes_map.items():
                    if k.upper() == sym_clean.upper() or k.startswith(f"{sym_clean.upper()}.") or sym_clean.upper().startswith(f"{k.upper()}."):
                        snap = v
                        break

        if snap and snap.price and snap.price > 0:
            current_price = snap.price
            change_pct = snap.change_pct
            prev_close = snap.prev_close if snap.prev_close and snap.prev_close > 0 else current_price
        elif item.manual_price is not None and float(item.manual_price) > 0:
            current_price = float(item.manual_price)
        elif cost > 0:
            current_price = cost
        elif cat in [AssetCategory.CASH.value, AssetCategory.FIXED_INCOME.value]:
            # 银行存款/现金默认单价为 1.0 (按本金保本核算)
            current_price = 1.0
            if cost <= 0:
                cost = 1.0

        # === 存款与固收利息核算 (Accrued Interest Calculation) ===
        deposit_type = getattr(item, "deposit_type", None) or "NONE"
        interest_rate = float(getattr(item, "interest_rate", 0.0) or 0.0)
        start_date_str = getattr(item, "start_date", None)
        end_date_str = getattr(item, "end_date", None)
        settlement_cycle = getattr(item, "settlement_cycle", None) or "MATURITY"
        auto_rollover = bool(getattr(item, "auto_rollover", False))

        accrued_interest_raw = 0.0
        days_held = 0
        days_remaining = None
        is_matured = False
        term_days = None

        if deposit_type in ["DEMAND", "FIXED", "NOTICE", "LARGE_CD"] and interest_rate > 0:
            import datetime
            today = datetime.date.today()
            s_date = None
            e_date = None
            if start_date_str:
                try:
                    s_date = datetime.date.fromisoformat(start_date_str.strip())
                except Exception:
                    pass
            if end_date_str:
                try:
                    e_date = datetime.date.fromisoformat(end_date_str.strip())
                except Exception:
                    pass

            # 确定计息天数
            if s_date:
                days_held = max(0, (today - s_date).days)
                if e_date:
                    term_days = max(0, (e_date - s_date).days)
                    days_remaining = max(0, (e_date - today).days)
                    if today >= e_date:
                        is_matured = True
                        effective_days = term_days
                    else:
                        effective_days = days_held
                else:
                    effective_days = days_held

                # 银行标准采用实际天数法：本金 * (年利率 / 100) * (天数 / 365)
                # amt 为存款本金 (成本值)
                accrued_interest_raw = round(amt * (interest_rate / 100.0) * (effective_days / 365.0), 2)

        # 原始币种估值
        if deposit_type in ["DEMAND", "FIXED", "NOTICE", "LARGE_CD"] and interest_rate > 0:
            # 存款类资产：成本即为本金，最新市值 = 本金 + 累计产生的利息
            cost_val_raw = round(amt, 2)
            market_val_raw = round(cost_val_raw + accrued_interest_raw, 2)
            pnl_raw = accrued_interest_raw
            pnl_pct = round((pnl_raw / cost_val_raw) * 100, 2) if cost_val_raw > 0 else 0.0
            current_price = round(market_val_raw / amt, 4) if amt > 0 else 1.0
        else:
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
            # 存款与计息专属字段
            "deposit_type": deposit_type,
            "interest_rate": interest_rate,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "settlement_cycle": settlement_cycle,
            "auto_rollover": auto_rollover,
            "accrued_interest": accrued_interest_raw,
            "accrued_interest_cny": round(accrued_interest_raw * fx_rate, 2),
            "days_held": days_held,
            "days_remaining": days_remaining,
            "term_days": term_days,
            "is_matured": is_matured,
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

