from typing import Optional, List, Dict, Any
import datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import akshare as ak
import yfinance as yf
from core.models import parse_symbol, format_symbol, Market, AssetType

router = APIRouter(prefix="/api/v1", tags=["Market Intelligence, Screener & Flow"])

# --- 1. 资金流向模型 ---
class MoneyFlowItem(BaseModel):
    direction: str = Field(..., description="资金方向: 北向(外资流入A股), 南向(内资流入港股)")
    plate: str = Field(..., description="板块: 沪股通, 深股通, 港股通(沪), 港股通(深)")
    date: str
    net_inflow_million: Optional[float] = Field(None, description="当日净买入成交额 (百万元)")
    up_count: Optional[int] = Field(None, description="板块内上涨个股数")
    down_count: Optional[int] = Field(None, description="板块内下跌个股数")
    index_name: Optional[str] = Field(None, description="关联指数")
    index_change_pct: Optional[float] = Field(None, description="关联指数涨跌幅(%)")

class MoneyFlowResponse(BaseModel):
    date: str
    count: int
    data: List[MoneyFlowItem]

@router.get("/market/moneyflow", response_model=MoneyFlowResponse)
async def get_market_moneyflow():
    """
    获取今日核心资金流向指标：
    - 北向资金 (沪深股通外资净流入)
    - 南向资金 (内资南下买入港股)
    - 板块涨跌分布与关联指数表现
    """
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.is_empty if hasattr(df, "is_empty") else df.empty:
            raise HTTPException(status_code=404, detail="No money flow data available today")

        today_str = str(df["交易日"].iloc[0]) if "交易日" in df.columns else datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        items = []
        for _, row in df.iterrows():
            items.append(MoneyFlowItem(
                direction=str(row.get("资金方向", "")),
                plate=str(row.get("板块", "")),
                date=today_str,
                net_inflow_million=float(row["净额"]) if "净额" in row and str(row["净额"]) != "nan" else None,
                up_count=int(row["上涨数"]) if "上涨数" in row and str(row["上涨数"]) != "nan" else None,
                down_count=int(row["下跌数"]) if "下跌数" in row and str(row["下跌数"]) != "nan" else None,
                index_name=str(row.get("相关指数", "")),
                index_change_pct=float(row["指数涨跌幅"]) if "指数涨跌幅" in row and str(row["指数涨跌幅"]) != "nan" else None,
            ))

        return MoneyFlowResponse(
            date=today_str,
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch money flow: {str(e)}")


# --- 2. 指数成分股模型 ---
class ConstituentItem(BaseModel):
    symbol: str = Field(..., description="规范化标的代码: 如 600519.SH.STK")
    ticker: str
    name: str
    in_date: Optional[str] = Field(None, description="纳入指数日期")

class ConstituentResponse(BaseModel):
    index_symbol: str
    index_name: str
    count: int
    constituents: List[ConstituentItem]

@router.get("/index/constituents", response_model=ConstituentResponse)
async def get_index_constituents(
    index_symbol: str = Query(..., description="指数代码，如 000300 (沪深300), 000905 (中证500), SPX (标普500)")
):
    """
    获取宽基指数的最新真实成分股列表与股票池（用于策略选股范围限定或指数增强模型）。
    """
    ticker, market_str, type_str = parse_symbol(index_symbol)
    clean_symbol = format_symbol(ticker, market_str, AssetType.INDEX.value)

    # 1. A 股核心指数成分股 (000300, 000905 等)
    if market_str in [Market.SH.value, Market.SZ.value]:
        try:
            df = ak.index_stock_cons(symbol=ticker)
            if df is None or df.empty:
                raise HTTPException(status_code=404, detail=f"No constituents found for {clean_symbol}")

            items = []
            code_col = "品种代码" if "品种代码" in df.columns else "code"
            name_col = "品种名称" if "品种名称" in df.columns else "name"
            date_col = "纳入日期" if "纳入日期" in df.columns else "date"

            for _, row in df.iterrows():
                c_code = str(row[code_col]).zfill(6)
                c_market = Market.SH.value if c_code.startswith("6") else Market.SZ.value
                sym = f"{c_code}.{c_market}.STK"
                items.append(ConstituentItem(
                    symbol=sym,
                    ticker=c_code,
                    name=str(row[name_col]),
                    in_date=str(row[date_col]) if date_col in row and str(row[date_col]) != "None" else None
                ))

            idx_name = "沪深300指数" if ticker == "000300" else ("中证500指数" if ticker == "000905" else ticker)
            return ConstituentResponse(
                index_symbol=clean_symbol,
                index_name=idx_name,
                count=len(items),
                constituents=items
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch index constituents: {str(e)}")

    # 2. 美股指数成分股 (S&P 500, Nasdaq 100)
    # yfinance / Wikipedia 核心成分股
    if ticker in ["SPX", "GSPC", "SPY"]:
        sp500_sample = [
            ("AAPL", "Apple Inc."), ("MSFT", "Microsoft Corp."), ("NVDA", "NVIDIA Corp."),
            ("AMZN", "Amazon.com"), ("GOOGL", "Alphabet Class A"), ("META", "Meta Platforms"),
            ("TSLA", "Tesla Inc."), ("BRK.B", "Berkshire Hathaway"), ("UNH", "UnitedHealth Group"),
            ("JNJ", "Johnson & Johnson"), ("JPM", "JPMorgan Chase"), ("V", "Visa Inc.")
        ]
        items = [ConstituentItem(symbol=f"{t}.US.STK", ticker=t, name=n, in_date=None) for t, n in sp500_sample]
        return ConstituentResponse(
            index_symbol=clean_symbol,
            index_name="S&P 500 Representative Sample (核心代表性成分股样本)",
            count=len(items),
            constituents=items
        )

    raise HTTPException(status_code=400, detail=f"Unsupported index symbol: {clean_symbol}")


# --- 3. 全市场截面选股器模型 ---
class ScreenerItem(BaseModel):
    symbol: str
    ticker: str
    name: str
    latest_price: float
    pct_change: float
    volume: float
    amount: float

class ScreenerResponse(BaseModel):
    count: int
    data: List[ScreenerItem]

@router.get("/screener", response_model=ScreenerResponse)
async def run_screener(
    min_pct_change: Optional[float] = Query(None, description="最小涨跌幅(%)，如 3.0 (代表今日涨幅>=3%)"),
    max_pct_change: Optional[float] = Query(None, description="最大涨跌幅(%)，如 9.9"),
    min_price: Optional[float] = Query(None, description="最低价格 (元)"),
    max_price: Optional[float] = Query(None, description="最高价格 (元)"),
    min_amount: Optional[float] = Query(None, description="最低成交额 (元)，如 100000000 (代表1亿以上)"),
    limit: int = Query(50, ge=1, le=200, description="返回结果上限")
):
    """
    A 股全市场每日截面选股器 (A-Share Market Screener):
    基于 A 股全市场实时行情截面多因子筛选标的，支持涨跌幅、成交额、价格区间过滤。
    """
    try:
        # 实时拉取最新全市场快照
        df = ak.stock_zh_a_spot()
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="Market spot data currently unavailable")

        # 列名: 代码, 名称, 最新价, 涨跌额, 涨跌幅, 买入, 卖出, 昨收, 今开, 最高, 最低, 成交量, 成交额
        df["最新价"] = df["最新价"].astype(float)
        df["涨跌幅"] = df["涨跌幅"].astype(float)
        df["成交额"] = df["成交额"].astype(float)
        df["成交量"] = df["成交量"].astype(float)

        # 过滤条件
        if min_pct_change is not None:
            df = df[df["涨跌幅"] >= min_pct_change]
        if max_pct_change is not None:
            df = df[df["涨跌幅"] <= max_pct_change]
        if min_price is not None:
            df = df[df["最新价"] >= min_price]
        if max_price is not None:
            df = df[df["最新价"] <= max_price]
        if min_amount is not None:
            df = df[df["成交额"] >= min_amount]

        # 默认按涨跌幅降序
        df = df.sort_values(by="涨跌幅", ascending=False).head(limit)

        results = []
        for _, row in df.iterrows():
            raw_code = str(row["代码"]).lower()
            ticker = raw_code.replace("sh", "").replace("sz", "").replace("bj", "")
            market = "SH" if "sh" in raw_code or ticker.startswith("6") else ("SZ" if "sz" in raw_code or ticker.startswith("0") or ticker.startswith("3") else "BJ")
            sym = f"{ticker}.{market}.STK"

            results.append(ScreenerItem(
                symbol=sym,
                ticker=ticker,
                name=str(row["名称"]),
                latest_price=round(float(row["最新价"]), 2),
                pct_change=round(float(row["涨跌幅"]), 2),
                volume=float(row["成交量"]),
                amount=float(row["成交额"])
            ))

        return ScreenerResponse(
            count=len(results),
            data=results
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screener execution failed: {str(e)}")
