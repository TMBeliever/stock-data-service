from typing import Optional, List
import datetime
import asyncio
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import akshare as ak
from core.models import parse_symbol, format_symbol, Market

router = APIRouter(prefix="/api/v1", tags=["Margin Trading (融资融券)"])

# --- 1. 全市场两融走势 ---
class MarginMarketItem(BaseModel):
    date: str = Field(..., description="信用交易日期: YYYY-MM-DD")
    financing_buy: Optional[float] = Field(None, description="融资买入额 (元)")
    financing_balance: Optional[float] = Field(None, description="融资余额 (元)")
    securities_lending_volume: Optional[float] = Field(None, description="融券卖出量/余量 (股)")
    securities_lending_balance: Optional[float] = Field(None, description="融券余额 (元)")
    total_balance: Optional[float] = Field(None, description="融资融券余额合计 (元)")

class MarginMarketResponse(BaseModel):
    market: str
    count: int
    data: List[MarginMarketItem]

def _normalize_date(d: str) -> str:
    s = d.replace("-", "")
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else d

@router.get("/market/margin", response_model=MarginMarketResponse)
async def get_market_margin(
    market: str = Query(..., pattern="^(SH|SZ)$", description="市场: SH (上交所) 或 SZ (深交所)。北交所暂无两融业务，不支持"),
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD (默认近30日)"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD (默认当天)")
):
    """
    获取全市场融资融券每日走势 (做多/做空压力标准指标):
    融资余额、融资买入额、融券余量/余额、融资融券余额合计。
    """
    today = datetime.datetime.now(datetime.timezone.utc).date()
    end_d = end or today.strftime("%Y-%m-%d")
    start_d = start or (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    start_clean = start_d.replace("-", "")
    end_clean = end_d.replace("-", "")

    try:
        loop = asyncio.get_running_loop()
        items: List[MarginMarketItem] = []

        if market == "SH":
            df = await loop.run_in_executor(None, lambda: ak.stock_margin_sse(start_date=start_clean, end_date=end_clean))
            if df is None or df.empty:
                raise HTTPException(status_code=404, detail=f"No margin data available for {market} in range [{start_d}, {end_d}]")
            for _, row in df.iterrows():
                items.append(MarginMarketItem(
                    date=_normalize_date(str(row["信用交易日期"])),
                    financing_buy=float(row["融资买入额"]) if "融资买入额" in row else None,
                    financing_balance=float(row["融资余额"]) if "融资余额" in row else None,
                    securities_lending_volume=float(row["融券余量"]) if "融券余量" in row else None,
                    securities_lending_balance=float(row["融券余量金额"]) if "融券余量金额" in row else None,
                    total_balance=float(row["融资融券余额"]) if "融资融券余额" in row else None,
                ))
        else:  # SZ: 深交所仅提供按日查询接口，需按日循环拉取区间走势
            df = await loop.run_in_executor(None, lambda: ak.macro_china_market_margin_sz())
            if df is None or df.empty:
                raise HTTPException(status_code=404, detail=f"No margin data available for {market} in range [{start_d}, {end_d}]")
            df = df[(df["日期"].astype(str) >= start_d) & (df["日期"].astype(str) <= end_d)]
            for _, row in df.iterrows():
                def _f(v):
                    try:
                        return float(v) if str(v) != "nan" else None
                    except Exception:
                        return None
                items.append(MarginMarketItem(
                    date=str(row["日期"]),
                    financing_buy=_f(row.get("融资买入额")),
                    financing_balance=_f(row.get("融资余额")),
                    securities_lending_volume=_f(row.get("融券余量")),
                    securities_lending_balance=_f(row.get("融券余额")),
                    total_balance=_f(row.get("融资融券余额")),
                ))

        return MarginMarketResponse(market=market, count=len(items), data=items)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch market margin data: {str(e)}")


# --- 2. 个股两融明细 ---
class MarginStockItem(BaseModel):
    date: str = Field(..., description="信用交易日期: YYYY-MM-DD")
    symbol: str
    financing_buy: Optional[float] = Field(None, description="融资买入额 (元)")
    financing_balance: Optional[float] = Field(None, description="融资余额 (元)")
    lending_sell_volume: Optional[float] = Field(None, description="融券卖出量 (股)")
    lending_balance_volume: Optional[float] = Field(None, description="融券余量 (股)")
    total_balance: Optional[float] = Field(None, description="融资融券余额合计 (元)")

class MarginStockResponse(BaseModel):
    symbol: str
    date: str
    found: bool
    data: Optional[MarginStockItem] = None

@router.get("/stock/margin", response_model=MarginStockResponse)
async def get_stock_margin(
    symbol: str = Query(..., description="股票代码，如 600519 (茅台，需为两融标的), 000001 (平安银行)"),
    date: Optional[str] = Query(None, description="查询日期 YYYY-MM-DD (默认最近一个交易日，交易所两融明细通常 T+1 披露)")
):
    """
    获取个股融资融券明细 (仅两融标的池内股票支持):
    融资买入额/余额、融券卖出量/余量。北交所无两融业务，一律返回未找到。
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)

    if market_str == Market.BJ.value:
        raise HTTPException(status_code=400, detail="北交所暂无融资融券业务，无法提供两融明细数据")
    if market_str not in [Market.SH.value, Market.SZ.value]:
        raise HTTPException(status_code=400, detail=f"Margin trading data only supported for A-share (SH/SZ) symbols, got: {market_str}")

    today = datetime.datetime.now(datetime.timezone.utc).date()
    # 交易所两融明细披露通常滞后一个交易日，默认回溯查询前一日
    target_date = date or (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    date_clean = target_date.replace("-", "")

    try:
        loop = asyncio.get_running_loop()
        if market_str == Market.SH.value:
            df = await loop.run_in_executor(None, lambda: ak.stock_margin_detail_sse(date=date_clean))
            code_col, name_col = "标的证券代码", "标的证券简称"
        else:
            df = await loop.run_in_executor(None, lambda: ak.stock_margin_detail_szse(date=date_clean))
            code_col, name_col = "证券代码", "证券简称"

        if df is None or df.empty:
            return MarginStockResponse(symbol=clean_symbol, date=_normalize_date(date_clean), found=False, data=None)

        row_df = df[df[code_col].astype(str).str.zfill(6) == ticker.zfill(6)]
        if row_df.empty:
            return MarginStockResponse(symbol=clean_symbol, date=_normalize_date(date_clean), found=False, data=None)

        row = row_df.iloc[0]

        def _f(col: str) -> Optional[float]:
            try:
                return float(row[col]) if col in row and str(row[col]) != "nan" else None
            except Exception:
                return None

        item = MarginStockItem(
            date=_normalize_date(date_clean),
            symbol=clean_symbol,
            financing_buy=_f("融资买入额"),
            financing_balance=_f("融资余额"),
            lending_sell_volume=_f("融券卖出量"),
            lending_balance_volume=_f("融券余量"),
            total_balance=_f("融资融券余额"),
        )
        return MarginStockResponse(symbol=clean_symbol, date=_normalize_date(date_clean), found=True, data=item)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stock margin data for {clean_symbol}: {str(e)}")
