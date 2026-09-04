from typing import Optional, List, Dict, Any
import datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import pandas as pd
import akshare as ak
import yfinance as yf
from core.models import parse_symbol, format_symbol, Market, AssetType
from core.database import meta_db

router = APIRouter(prefix="/api/v1/stock", tags=["Stock Fundamentals & Valuation"])

class ValuationPoint(BaseModel):
    date: str
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    market_cap_billion: Optional[float] = None

class ValuationResponse(BaseModel):
    symbol: str
    ticker: str
    market: str
    name: Optional[str] = None
    date: str = Field(..., description="估值统计日期: YYYY-MM-DD")
    currency: str = "CNY"
    pe_ttm: Optional[float] = Field(None, description="市盈率(TTM)")
    pe_static: Optional[float] = Field(None, description="市盈率(静) / 预测市盈率")
    pb: Optional[float] = Field(None, description="市净率(PB)")
    market_cap_billion: Optional[float] = Field(None, description="总市值 (亿元 或 10亿美元)")
    dividend_yield_pct: Optional[float] = Field(None, description="股息率(%)")
    history: Optional[List[ValuationPoint]] = Field(None, description="历史估值走势 (当 include_history=true 时返回)")

@router.get("/valuation", response_model=ValuationResponse)
async def get_stock_valuation(
    symbol: str = Query(..., description="股票代码，如 002594 (比亚迪), 600519 (茅台), AAPL (苹果)"),
    include_history: bool = Query(False, description="是否返回近 1 年历史估值走势序列")
):
    """
    获取个股基础面估值数据：PE(TTM)、PB、市值、股息率等。
    - A股：对接百度股市通/新浪官方数据源，返回真实 PE(TTM)、PB、总市值。
    - 美股/港股：对接 Yahoo Finance 官方估值与基本面指标。
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)

    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # 1. A 股市场标的估值查询
    if market_str in [Market.SH.value, Market.SZ.value, Market.BJ.value]:
        try:
            # 抓取真实市盈率(TTM)
            df_pe = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="市盈率(TTM)", period="近一年")
            # 抓取真实市净率
            df_pb = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="市净率", period="近一年")
            # 抓取总市值
            df_mv = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="总市值", period="近一年")

            latest_pe = float(df_pe["value"].dropna().iloc[-1]) if not df_pe.empty else None
            latest_pb = float(df_pb["value"].dropna().iloc[-1]) if not df_pb.empty else None
            latest_mv = float(df_mv["value"].dropna().iloc[-1]) if not df_mv.empty else None
            latest_date = str(df_pe["date"].dropna().iloc[-1]) if not df_pe.empty else today_str

            history_points = None
            if include_history and not df_pe.empty and not df_pb.empty:
                # 拼接历史序列
                merged = df_pe.merge(df_pb, on="date", suffixes=("_pe", "_pb"))
                if not df_mv.empty:
                    merged = merged.merge(df_mv, on="date")
                    merged.rename(columns={"value": "value_mv"}, inplace=True)
                
                history_points = []
                for _, row in merged.iterrows():
                    history_points.append(ValuationPoint(
                        date=str(row["date"]),
                        pe_ttm=float(row["value_pe"]) if "value_pe" in row and not pd.isna(row["value_pe"]) else None,
                        pb=float(row["value_pb"]) if "value_pb" in row and not pd.isna(row["value_pb"]) else None,
                        market_cap_billion=float(row["value_mv"]) if "value_mv" in row and not pd.isna(row["value_mv"]) else None,
                    ))

            sym_info = meta_db.get_symbol(clean_symbol)
            name = sym_info["name"] if sym_info else ticker

            return ValuationResponse(
                symbol=clean_symbol,
                ticker=ticker,
                market=market_str,
                name=name,
                date=latest_date,
                currency="CNY",
                pe_ttm=round(latest_pe, 2) if latest_pe else None,
                pb=round(latest_pb, 2) if latest_pb else None,
                market_cap_billion=round(latest_mv, 2) if latest_mv else None,
                history=history_points
            )
        except Exception as e:
            # 备选走 yfinance
            pass

    # 2. 美股、港股及海外资产估值查询
    try:
        yf_ticker = ticker
        if market_str == Market.HK.value:
            clean_hk = ticker.lstrip("0")
            clean_hk = clean_hk.zfill(4) if len(clean_hk) < 4 else clean_hk
            yf_ticker = f"{clean_hk}.HK"
        elif market_str == Market.SH.value:
            yf_ticker = f"{ticker}.SS"
        elif market_str == Market.SZ.value:
            yf_ticker = f"{ticker}.SZ"

        t = yf.Ticker(yf_ticker)
        info = t.info

        pe_ttm = info.get("trailingPE")
        pe_fwd = info.get("forwardPE")
        pb = info.get("priceToBook")
        market_cap = info.get("marketCap")
        div_yield = info.get("dividendYield")
        name = info.get("shortName", ticker)

        mv_billion = round(market_cap / 1e8, 2) if market_cap and market_str in ["SH", "SZ"] else (round(market_cap / 1e9, 2) if market_cap else None)

        return ValuationResponse(
            symbol=clean_symbol,
            ticker=ticker,
            market=market_str,
            name=name,
            date=today_str,
            currency="USD" if market_str == Market.US.value else ("HKD" if market_str == Market.HK.value else "CNY"),
            pe_ttm=round(pe_ttm, 2) if pe_ttm else None,
            pe_static=round(pe_fwd, 2) if pe_fwd else None,
            pb=round(pb, 2) if pb else None,
            market_cap_billion=mv_billion,
            dividend_yield_pct=round(div_yield, 2) if div_yield else None,
            history=None
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch valuation for {clean_symbol}: {str(e)}")
