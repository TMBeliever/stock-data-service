from typing import Optional, List
import asyncio
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import akshare as ak
import yfinance as yf
from core.models import parse_symbol, format_symbol, Market

router = APIRouter(prefix="/api/v1/stock", tags=["Dividends & Corporate Actions"])

class DividendItem(BaseModel):
    report_date: str = Field(..., description="分红方案对应报告期截止日: YYYY-MM-DD")
    announcement_date: Optional[str] = Field(None, description="最新公告日期: YYYY-MM-DD")
    record_date: Optional[str] = Field(None, description="股权登记日: YYYY-MM-DD (仅 A 股提供)")
    ex_dividend_date: Optional[str] = Field(None, description="除权除息日: YYYY-MM-DD")
    cash_per_share: Optional[float] = Field(None, description="每股现金分红金额 (税前，本币计价)")
    bonus_share_ratio: Optional[float] = Field(None, description="每股送转股比例 (如 0.3 表示每股送转0.3股，仅 A 股提供)")
    dividend_yield_pct: Optional[float] = Field(None, description="股息率(%) (仅 A 股提供)")
    plan_progress: Optional[str] = Field(None, description="分红方案进度 (如：实施分配/董事会预案，仅 A 股提供)")
    plan_description: Optional[str] = Field(None, description="分红方案人类可读描述 (如：10派6.00元，仅 A 股提供)")

class DividendResponse(BaseModel):
    symbol: str
    ticker: str
    market: str
    currency: str
    count: int
    dividends: List[DividendItem]

@router.get("/dividends", response_model=DividendResponse)
async def get_dividends(
    symbol: str = Query(..., description="股票代码，如 600519 (茅台), AAPL (苹果), 00700 (腾讯控股)"),
    limit: int = Query(20, ge=1, le=200, description="返回最近 N 条历史分红记录 (默认20条)")
):
    """
    获取标的历史分红送配记录 (回测收益序列还原、除权除息日核对的必要基础数据):
    - A 股：对接东方财富分红送配详情，含每股现金分红、送转比例、股权登记日、除权除息日与方案进度
    - 美股/港股：对接 Yahoo Finance 官方历史分红序列 (每股现金分红金额)，源端无送转比例/股权登记日等字段
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)

    # 1. A 股分红送配详情
    if market_str in [Market.SH.value, Market.SZ.value, Market.BJ.value]:
        try:
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(None, lambda: ak.stock_fhps_detail_em(symbol=ticker))
            if df is None or df.empty:
                raise HTTPException(status_code=404, detail=f"No dividend records found for {clean_symbol}")

            # 按报告期倒序取最近 N 条
            df = df.sort_values(by="报告期", ascending=False).head(limit)

            items = []
            for _, row in df.iterrows():
                def _s(v) -> Optional[str]:
                    if v is None or str(v) in ("nan", "NaT", "None", ""):
                        return None
                    return str(v)

                def _f(v) -> Optional[float]:
                    try:
                        if v is None or str(v) in ("nan", "NaT", "None", ""):
                            return None
                        return float(v)
                    except Exception:
                        return None

                # "现金分红-现金分红比例" 为每 10 股派现金额，换算为每股金额
                cash_ratio = _f(row.get("现金分红-现金分红比例"))
                cash_per_share = round(cash_ratio / 10.0, 4) if cash_ratio is not None else None

                bonus_ratio = _f(row.get("送转股份-送转总比例"))
                bonus_per_share = round(bonus_ratio / 10.0, 4) if bonus_ratio is not None else None

                div_yield = _f(row.get("现金分红-股息率"))
                div_yield_pct = round(div_yield * 100.0, 4) if div_yield is not None else None

                items.append(DividendItem(
                    report_date=_s(row.get("报告期")) or "",
                    announcement_date=_s(row.get("最新公告日期")),
                    record_date=_s(row.get("股权登记日")),
                    ex_dividend_date=_s(row.get("除权除息日")),
                    cash_per_share=cash_per_share,
                    bonus_share_ratio=bonus_per_share,
                    dividend_yield_pct=div_yield_pct,
                    plan_progress=_s(row.get("方案进度")),
                    plan_description=_s(row.get("现金分红-现金分红比例描述")),
                ))

            return DividendResponse(
                symbol=clean_symbol,
                ticker=ticker,
                market=market_str,
                currency="CNY",
                count=len(items),
                dividends=items
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch dividends for {clean_symbol}: {str(e)}")

    # 2. 美股、港股历史分红 (yfinance)
    try:
        yf_ticker = ticker if market_str == Market.US.value else f"{ticker.lstrip('0').zfill(4)}.HK"
        loop = asyncio.get_running_loop()

        def _fetch_yf_dividends(t_str: str):
            return yf.Ticker(t_str).dividends

        div_series = await loop.run_in_executor(None, _fetch_yf_dividends, yf_ticker)

        if div_series is None or div_series.empty:
            raise HTTPException(status_code=404, detail=f"No dividend records found for {clean_symbol}")

        div_series = div_series.sort_index(ascending=False).head(limit)

        items = []
        for dt_idx, cash_amount in div_series.items():
            items.append(DividendItem(
                report_date=dt_idx.strftime("%Y-%m-%d"),
                announcement_date=None,
                record_date=None,
                ex_dividend_date=dt_idx.strftime("%Y-%m-%d"),
                cash_per_share=round(float(cash_amount), 4),
                bonus_share_ratio=None,
                dividend_yield_pct=None,
                plan_progress=None,
                plan_description=None,
            ))

        return DividendResponse(
            symbol=clean_symbol,
            ticker=ticker,
            market=market_str,
            currency="USD" if market_str == Market.US.value else "HKD",
            count=len(items),
            dividends=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch overseas dividends for {clean_symbol}: {str(e)}")
