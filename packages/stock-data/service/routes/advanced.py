from typing import Optional, List, Dict, Any
import datetime
import asyncio
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import akshare as ak
import yfinance as yf
from core.models import parse_symbol, format_symbol, Market, AssetType

router = APIRouter(prefix="/api/v1", tags=["Advanced Analytics: Sector, Holders, LHB & Macro"])

# --- 1. 公司画像与行业分类模型 ---
class CompanyProfileResponse(BaseModel):
    symbol: str
    ticker: str
    company_name: str
    industry: Optional[str] = Field(None, description="所属行业 (如：汽车制造业、半导体等)")
    main_business: Optional[str] = Field(None, description="主营业务范围")
    listing_date: Optional[str] = Field(None, description="上市日期")
    registered_capital: Optional[str] = Field(None, description="注册资本")
    intro: Optional[str] = Field(None, description="公司机构简介")

@router.get("/stock/profile", response_model=CompanyProfileResponse)
async def get_company_profile(
    symbol: str = Query(..., description="股票代码，如 002594 (比亚迪), 600519 (茅台), AAPL (苹果)")
):
    """
    获取公司画像与所属行业分类、主营业务及上市信息：
    - A 股：对接巨潮资讯官方上市公司画像与行业归类。
    - 美股/港股：对接 Yahoo Finance 官方行业分类 (Sector / Industry)。
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)

    # 1. A 股市场公司画像
    if market_str in [Market.SH.value, Market.SZ.value, Market.BJ.value]:
        try:
            df = ak.stock_profile_cninfo(symbol=ticker)
            if df is not None and not df.empty:
                row = df.iloc[0]
                return CompanyProfileResponse(
                    symbol=clean_symbol,
                    ticker=ticker,
                    company_name=str(row.get("公司名称", ticker)),
                    industry=str(row.get("所属行业", "")),
                    main_business=str(row.get("主营业务", "")),
                    listing_date=str(row.get("上市日期", "")),
                    registered_capital=str(row.get("注册资金", "")),
                    intro=str(row.get("机构简介", ""))
                )
        except Exception:
            pass

    # 2. 美股、港股市场行业分类
    try:
        yf_ticker = ticker if market_str == Market.US.value else f"{ticker.lstrip('0').zfill(4)}.HK"
        t = yf.Ticker(yf_ticker)
        info = t.info
        return CompanyProfileResponse(
            symbol=clean_symbol,
            ticker=ticker,
            company_name=info.get("longName", info.get("shortName", ticker)),
            industry=f"{info.get('sector', '')} - {info.get('industry', '')}".strip(" -"),
            main_business=info.get("longBusinessSummary", ""),
            listing_date=None,
            registered_capital=None,
            intro=info.get("longBusinessSummary", "")
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile for {clean_symbol}: {str(e)}")


# --- 2. 股东户数与十大流通股东模型 ---
class ShareholderItem(BaseModel):
    rank: int = Field(..., description="持股排名 (1-10)")
    name: str = Field(..., description="股东名称 (机构/个人)")
    shares: Optional[float] = Field(None, description="持股数量 (股)")
    ratio_pct: Optional[float] = Field(None, description="持股比例 (%)")
    share_nature: Optional[str] = Field(None, description="股本性质 (如：A股流通股/境外上市外资股)")

class ShareholdersResponse(BaseModel):
    symbol: str
    end_date: str = Field(..., description="统计报告期")
    publish_date: Optional[str] = Field(None, description="信息披露日期")
    total_shareholders: Optional[int] = Field(None, description="股东总户数")
    avg_shares_per_holder: Optional[float] = Field(None, description="户均持股数量 (筹码集中度关键指标)")
    top_holders: List[ShareholderItem]

@router.get("/stock/shareholders", response_model=ShareholdersResponse)
async def get_shareholders(
    symbol: str = Query(..., description="股票代码，如 002594 (比亚迪), 600519 (茅台)")
):
    """
    获取股东户数（筹码集中度）与十大流通股东名单：
    - 股东总数与户均持股量（用于判断散户交出筹码、庄家机构建仓）
    - 十大股东/流通股东名单、持股数与持股占比
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)

    try:
        df = ak.stock_main_stock_holder(stock=ticker)
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No shareholder records found for {clean_symbol}")

        latest_val = df["截至日期"].iloc[0]
        latest_date = str(latest_val)
        pub_date = str(df["公告日期"].iloc[0]) if "公告日期" in df.columns else None
        tot_holders = int(df["股东总数"].iloc[0]) if "股东总数" in df.columns and str(df["股东总数"].iloc[0]) != "nan" else None
        avg_shares = float(df["平均持股数"].iloc[0]) if "平均持股数" in df.columns and str(df["平均持股数"].iloc[0]) != "nan" else None

        # 提取最新一期十大股东
        current_df = df[df["截至日期"] == latest_val].head(10)
        items = []
        for idx, row in current_df.iterrows():
            shares_val = float(row["持股数量"]) if "持股数量" in row and str(row["持股数量"]) != "nan" else None
            ratio_val = float(row["持股比例"]) if "持股比例" in row and str(row["持股比例"]) != "nan" else None
            items.append(ShareholderItem(
                rank=int(row.get("编号", len(items) + 1)),
                name=str(row.get("股东名称", "")),
                shares=shares_val,
                ratio_pct=ratio_val,
                share_nature=str(row.get("股本性质", "")) if str(row.get("股本性质", "")) != "nan" else None
            ))

        return ShareholdersResponse(
            symbol=clean_symbol,
            end_date=latest_date,
            publish_date=pub_date,
            total_shareholders=tot_holders,
            avg_shares_per_holder=avg_shares,
            top_holders=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch shareholders: {str(e)}")


# --- 3. 全市场行业与概念板块行情排行榜 ---
class SectorRankItem(BaseModel):
    sector_name: str
    avg_price: float
    pct_change: float
    leading_stock: str
    leading_stock_pct: float

class SectorRankResponse(BaseModel):
    type: str
    count: int
    data: List[SectorRankItem]

@router.get("/market/sectors", response_model=SectorRankResponse)
async def get_market_sectors(
    indicator: str = Query("行业", pattern="^(行业|概念)$", description="板块类型: '行业' 或 '概念'"),
    limit: int = Query(30, ge=1, le=100, description="返回数量")
):
    """
    获取今日全市场板块行情热点排行：
    - 行业板块排行（申万行业分类热度）
    - 概念板块排行（华为汽车、光伏、低空经济、AI芯片等题材热点）
    - 各板块对应涨跌幅与领涨龙头股表现
    """
    try:
        df = ak.stock_sector_spot(indicator=indicator)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="Sector spot data unavailable")

        df["涨跌幅"] = df["涨跌幅"].astype(float)
        df = df.sort_values(by="涨跌幅", ascending=False).head(limit)

        items = []
        for _, row in df.iterrows():
            items.append(SectorRankItem(
                sector_name=str(row["板块"]),
                avg_price=round(float(row["平均价格"]), 2),
                pct_change=round(float(row["涨跌幅"]), 2),
                leading_stock=str(row["股票名称"]),
                leading_stock_pct=round(float(row["个股-涨跌幅"]), 2)
            ))

        return SectorRankResponse(
            type=indicator,
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sectors: {str(e)}")


# --- 4. 每日龙虎榜详情 ---
class DragonTigerItem(BaseModel):
    symbol: str
    ticker: str
    name: str
    close_price: Optional[float] = Field(None, description="收盘价")
    change_pct: Optional[float] = Field(None, description="涨跌幅(%)")
    turnover_volume: Optional[float] = Field(None, description="成交量 (源缺失时可能为 None)")
    turnover_amount: Optional[float] = Field(None, description="龙虎榜成交额 (元)")
    reason: str

class DragonTigerResponse(BaseModel):
    date: str
    count: int
    data: List[DragonTigerItem]

@router.get("/market/dragon-tiger", response_model=DragonTigerResponse)
async def get_dragon_tiger_list(
    date: Optional[str] = Query(None, description="交易日期 (YYYYMMDD 或 YYYY-MM-DD)，不传默认最近一个交易日")
):
    """
    获取每日龙虎榜数据：
    机构专用席位买卖、游资营业部大举建仓或抛售的个股及上榜原因（涨跌偏离值达7%、换手率达20%等）。
    数据源: 东方财富 (stock_lhb_detail_em)，稳定且含"上榜原因"字段。
    """
    target = date.replace("-", "") if date else ""
    date_clean = target or datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    latest_ok_date, df = None, None

    # 从目标日期向前回溯最多 7 个自然日，找到最近一个已发布数据的交易日
    base = datetime.datetime.strptime(date_clean, "%Y%m%d").date()
    for offset in range(0, 7):
        probe = (base - datetime.timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = ak.stock_lhb_detail_em(start_date=probe, end_date=probe)
            if df is not None and not df.empty:
                latest_ok_date = probe
                break
        except Exception:
            continue
        df = None

    if df is None or df.empty or latest_ok_date is None:
        return DragonTigerResponse(date=date_clean, count=0, data=[])

    # 列名兼容：官方接口变动时优先取新列名，其次回退旧列名
    code_col = "代码" if "代码" in df.columns else "股票代码"
    name_col = "名称" if "名称" in df.columns else "股票名称"
    reason_col = "上榜原因" if "上榜原因" in df.columns else "解读"
    # 成交额字段：优先龙虎榜成交额，其次 买入额+卖出额
    amount_col = "龙虎榜成交额" if "龙虎榜成交额" in df.columns else "龙虎榜买入额"
    close_col = "收盘价" if "收盘价" in df.columns else None

    items = []
    for _, row in df.iterrows():
        c_code = str(row[code_col]).zfill(6)
        c_market = "SH" if c_code.startswith("6") else "SZ"
        sym = f"{c_code}.{c_market}.STK"

        change = row.get("涨跌幅")
        if "涨跌幅" not in df.columns:
            change = row.get("对应值")
        amount = float(row[amount_col]) if amount_col in df.columns else None
        if amount_col == "龙虎榜买入额" and "龙虎榜卖出额" in df.columns:
            amount += float(row["龙虎榜卖出额"])

        items.append(DragonTigerItem(
            symbol=sym,
            ticker=c_code,
            name=str(row[name_col]),
            close_price=round(float(row[close_col]), 2) if close_col and close_col in df.columns else None,
            change_pct=round(float(change), 2) if change is not None else None,
            turnover_volume=float(row["成交量"]) if "成交量" in df.columns else None,
            turnover_amount=round(amount, 2) if amount is not None else None,
            reason=str(row[reason_col]) if reason_col in df.columns else ""
        ))

    return DragonTigerResponse(
        date=latest_ok_date,
        count=len(items),
        data=items
    )


# --- 5. 宏观国债无风险利率 ---
class TreasuryYieldItem(BaseModel):
    name: str
    code: str
    latest_yield: Optional[float] = Field(None, description="最新收益率 (%)")
    date: str

class TreasuryYieldResponse(BaseModel):
    updated_at: str
    data: List[TreasuryYieldItem]

@router.get("/macro/treasury-yield", response_model=TreasuryYieldResponse)
async def get_treasury_yields():
    """
    获取中美 10 年期国债收益率（大类资产配置与 DCF 估值模型的无风险利率基准锚）。
    真实数据源：
    - 美国：Yahoo Finance (^TNX)
    - 中国：中债国债收益率曲线 (AkShare bond_china_yield)
    """
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    results = []

    # 1. 美国 10 年期国债收益率 (^TNX)
    try:
        t = yf.Ticker("^TNX")
        hist = t.history(period="5d")
        if hist is not None and not hist.empty:
            latest_val = round(float(hist["Close"].iloc[-1]), 3)
            latest_d = hist.index[-1].strftime("%Y-%m-%d")
            results.append(TreasuryYieldItem(
                name="美国 10 年期国债收益率",
                code="US10Y",
                latest_yield=latest_val,
                date=latest_d
            ))
    except Exception:
        pass

    # 2. 中国 10 年期国债收益率 (中债真实数据)
    try:
        today = datetime.date.today()
        start_date = (today - datetime.timedelta(days=30)).strftime("%Y%m%d")
        end_date = today.strftime("%Y%m%d")
        df_yield = ak.bond_china_yield(start_date=start_date, end_date=end_date)
        if df_yield is not None and not df_yield.empty:
            df_gz = df_yield[df_yield["曲线名称"] == "中债国债收益率曲线"]
            if not df_gz.empty and "10年" in df_gz.columns:
                valid_rows = df_gz.dropna(subset=["10年", "日期"])
                if not valid_rows.empty:
                    latest_row = valid_rows.iloc[-1]
                    results.append(TreasuryYieldItem(
                        name="中国 10 年期国债基准收益率",
                        code="CN10Y",
                        latest_yield=round(float(latest_row["10年"]), 4),
                        date=str(latest_row["日期"])
                    ))
    except Exception:
        pass

    return TreasuryYieldResponse(
        updated_at=now_str,
        data=results
    )


# --- 6. 中国宏观经济核心月度序列 (PMI / CPI / PPI / M2) ---
class PMIItem(BaseModel):
    month: str = Field(..., description="统计月份: YYYY-MM")
    manufacturing_index: Optional[float] = Field(None, description="制造业PMI指数")
    manufacturing_yoy_pct: Optional[float] = Field(None, description="制造业PMI同比增长(%)")
    non_manufacturing_index: Optional[float] = Field(None, description="非制造业PMI指数")
    non_manufacturing_yoy_pct: Optional[float] = Field(None, description="非制造业PMI同比增长(%)")

class PMIResponse(BaseModel):
    updated_at: str
    count: int
    data: List[PMIItem]

def _f_or_none(v) -> Optional[float]:
    try:
        return float(v) if v is not None and str(v) != "nan" else None
    except Exception:
        return None

def _month_to_iso(v) -> str:
    """将 AkShare '2026年08月份' 格式月份字符串转为 YYYY-MM"""
    s = str(v)
    digits = "".join(c for c in s if c.isdigit())
    return f"{digits[:4]}-{digits[4:6]}" if len(digits) >= 6 else s

@router.get("/macro/china/pmi", response_model=PMIResponse)
async def get_china_pmi(
    limit: int = Query(24, ge=1, le=300, description="返回最近 N 个月数据 (默认24个月)")
):
    """
    获取中国官方制造业/非制造业 PMI 采购经理人指数月度序列 (宏观景气度核心先行指标)。
    数据源: 国家统计局 (AkShare macro_china_pmi)。
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.macro_china_pmi)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="PMI data currently unavailable")
        df = df.head(limit)
        items = [
            PMIItem(
                month=_month_to_iso(row["月份"]),
                manufacturing_index=_f_or_none(row.get("制造业-指数")),
                manufacturing_yoy_pct=_f_or_none(row.get("制造业-同比增长")),
                non_manufacturing_index=_f_or_none(row.get("非制造业-指数")),
                non_manufacturing_yoy_pct=_f_or_none(row.get("非制造业-同比增长")),
            )
            for _, row in df.iterrows()
        ]
        return PMIResponse(
            updated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch PMI data: {str(e)}")


class CPIItem(BaseModel):
    month: str = Field(..., description="统计月份: YYYY-MM")
    national_yoy_pct: Optional[float] = Field(None, description="全国CPI同比增长(%)")
    national_mom_pct: Optional[float] = Field(None, description="全国CPI环比增长(%)")
    city_yoy_pct: Optional[float] = Field(None, description="城市CPI同比增长(%)")
    rural_yoy_pct: Optional[float] = Field(None, description="农村CPI同比增长(%)")

class CPIResponse(BaseModel):
    updated_at: str
    count: int
    data: List[CPIItem]

@router.get("/macro/china/cpi", response_model=CPIResponse)
async def get_china_cpi(
    limit: int = Query(24, ge=1, le=300, description="返回最近 N 个月数据 (默认24个月)")
):
    """
    获取中国居民消费价格指数 (CPI) 月度序列，含全国/城市/农村同比与环比增速。
    数据源: 国家统计局 (AkShare macro_china_cpi)。
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.macro_china_cpi)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="CPI data currently unavailable")
        df = df.head(limit)
        items = [
            CPIItem(
                month=_month_to_iso(row["月份"]),
                national_yoy_pct=_f_or_none(row.get("全国-同比增长")),
                national_mom_pct=_f_or_none(row.get("全国-环比增长")),
                city_yoy_pct=_f_or_none(row.get("城市-同比增长")),
                rural_yoy_pct=_f_or_none(row.get("农村-同比增长")),
            )
            for _, row in df.iterrows()
        ]
        return CPIResponse(
            updated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch CPI data: {str(e)}")


class PPIItem(BaseModel):
    month: str = Field(..., description="统计月份: YYYY-MM")
    current_value: Optional[float] = Field(None, description="当月PPI指数值")
    yoy_pct: Optional[float] = Field(None, description="当月同比增长(%)")

class PPIResponse(BaseModel):
    updated_at: str
    count: int
    data: List[PPIItem]

@router.get("/macro/china/ppi", response_model=PPIResponse)
async def get_china_ppi(
    limit: int = Query(24, ge=1, le=300, description="返回最近 N 个月数据 (默认24个月)")
):
    """
    获取中国工业生产者出厂价格指数 (PPI) 月度序列 (企业端通胀/通缩核心先行指标)。
    数据源: 国家统计局 (AkShare macro_china_ppi)。
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.macro_china_ppi)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="PPI data currently unavailable")
        df = df.head(limit)
        items = [
            PPIItem(
                month=_month_to_iso(row["月份"]),
                current_value=_f_or_none(row.get("当月")),
                yoy_pct=_f_or_none(row.get("当月同比增长")),
            )
            for _, row in df.iterrows()
        ]
        return PPIResponse(
            updated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch PPI data: {str(e)}")


class M2Item(BaseModel):
    date: str = Field(..., description="统计日期: YYYY-MM-DD")
    m2_yoy_pct: Optional[float] = Field(None, description="M2货币供应同比增速(%)")

class M2Response(BaseModel):
    updated_at: str
    count: int
    data: List[M2Item]

@router.get("/macro/china/m2", response_model=M2Response)
async def get_china_m2(
    limit: int = Query(24, ge=1, le=300, description="返回最近 N 期数据 (默认24期)")
):
    """
    获取中国 M2 货币供应量同比增速序列 (流动性宽紧核心宏观指标)。
    数据源: 国家统计局 (AkShare macro_china_m2_yearly)。
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.macro_china_m2_yearly)
        if df is None or df.empty:
            raise HTTPException(status_code=503, detail="M2 data currently unavailable")
        df = df.sort_values(by="日期", ascending=False).head(limit)
        items = [
            M2Item(
                date=str(row["日期"]),
                m2_yoy_pct=_f_or_none(row.get("今值")),
            )
            for _, row in df.iterrows()
        ]
        return M2Response(
            updated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            count=len(items),
            data=items
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch M2 data: {str(e)}")

