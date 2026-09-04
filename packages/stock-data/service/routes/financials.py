from typing import Optional, List, Dict, Any, Tuple
from collections import OrderedDict
import time
import asyncio
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
import akshare as ak
import yfinance as yf
from core.models import parse_symbol, format_symbol, Market

router = APIRouter(prefix="/api/v1/stock", tags=["Financial Statements & Reports"])

def _normalize_date_str(val: Any) -> Optional[str]:
    if val is None or str(val).lower() in ["nan", "none", "nat", ""]:
        return None
    s = str(val).strip().split(" ")[0].split("T")[0]
    s_clean = s.replace("-", "")
    if len(s_clean) == 8 and s_clean.isdigit():
        return f"{s_clean[:4]}-{s_clean[4:6]}-{s_clean[6:]}"
    return s

class FinancialReportItem(BaseModel):
    report_date: str = Field(..., description="报告期截止日: YYYY-MM-DD")
    announcement_date: Optional[str] = Field(None, description="公告披露日期: YYYY-MM-DD (Point-in-Time 权威依据)")
    revenue: Optional[float] = Field(None, description="营业总收入 (元)")
    net_profit: Optional[float] = Field(None, description="净利润 (元)")
    total_assets: Optional[float] = Field(None, description="资产总计 (元)")
    total_liabilities: Optional[float] = Field(None, description="负债合计 (元)")
    operating_cash_flow: Optional[float] = Field(None, description="经营活动产生的现金流量净额 (元)")
    gross_margin_pct: Optional[float] = Field(None, description="销售毛利率 (%)")
    net_margin_pct: Optional[float] = Field(None, description="销售净利率 (%)")
    debt_to_asset_pct: Optional[float] = Field(None, description="资产负债率 (%)")
    roa: Optional[float] = Field(None, description="总资产收益率-ROA (%)")
    roe: Optional[float] = Field(None, description="净资产收益率-ROE (%)")
    raw_details: Optional[Dict[str, Any]] = Field(None, description="该报告期完整原始会计科目")

class FinancialResponse(BaseModel):
    symbol: str
    ticker: str
    market: str
    currency: str
    as_of: Optional[str] = None
    pit_status: str = Field("STRICT", description="Point-in-Time 状态: STRICT (严格披露日过滤), ESTIMATED (以报告期近似估算), UNAVAILABLE")
    count: int
    reports: List[FinancialReportItem]

class FinancialCache:
    """带 TTL (15分钟) 与容量上限 (50条) 的安全内存缓存，杜绝内存无限泄漏"""
    def __init__(self, max_size: int = 50, ttl_seconds: int = 900):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[str, Tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        expire_time, val = self._data[key]
        if time.time() > expire_time:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return val

    def set(self, key: str, val: Any):
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self.max_size:
            self._data.popitem(last=False)
        self._data[key] = (time.time() + self.ttl_seconds, val)

_FINANCIAL_CACHE = FinancialCache(max_size=50, ttl_seconds=900)

async def _fetch_sina_reports(full_stock_code: str):
    cached = _FINANCIAL_CACHE.get(full_stock_code)
    if cached is not None:
        return cached

    last_err = None
    for attempt in range(3):
        try:
            loop = asyncio.get_running_loop()
            df_lrb = await loop.run_in_executor(None, lambda: ak.stock_financial_report_sina(stock=full_stock_code, symbol="利润表"))
            df_fzb = await loop.run_in_executor(None, lambda: ak.stock_financial_report_sina(stock=full_stock_code, symbol="资产负债表"))
            df_llb = await loop.run_in_executor(None, lambda: ak.stock_financial_report_sina(stock=full_stock_code, symbol="现金流量表"))
            _FINANCIAL_CACHE.set(full_stock_code, (df_lrb, df_fzb, df_llb))
            return df_lrb, df_fzb, df_llb
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    raise last_err

@router.get("/financials", response_model=FinancialResponse)
async def get_financials(
    symbol: str = Query(..., description="股票代码，如 002594 (比亚迪), 600519 (茅台), AAPL (苹果)"),
    limit: int = Query(8, ge=1, le=40, description="返回近 N 个季报期 (默认8个季度，即近2年)"),
    as_of: Optional[str] = Query(None, description="Point-in-Time 回测基准日期: YYYY-MM-DD。若指定，A股按官方公告披露日严格过滤 (Strict PIT)；海外标的因源端缺少权威历史公告时间戳，以报告期估算 (pit_status=ESTIMATED)。")
):
    """
    获取上市公司深度财务报表与核心财务比率：
    - 营业总收入与净利润、资产总计、负债合计与资产负债率、经营性现金流净额、综合毛利率与销售净利率
    - A 股支持官方公告披露日 (announcement_date) 的严格 PIT (Strict Point-in-Time) 过滤
    - 海外标的 (US/HK) 披露日缺失，响应中 pit_status 明确标注为 ESTIMATED 或 UNAVAILABLE，不冒充严格 PIT
    """
    ticker, market_str, type_str = parse_symbol(symbol)
    clean_symbol = format_symbol(ticker, market_str, type_str)
    as_of_fmt = _normalize_date_str(as_of) if as_of else None

    # 1. A 股深度财报 (基于新浪三大财务报表)
    if market_str in [Market.SH.value, Market.SZ.value, Market.BJ.value]:
        market_code = "sh" if market_str == Market.SH.value else ("sz" if market_str == Market.SZ.value else "bj")
        full_stock_code = f"{market_code}{ticker}"

        try:
            # 获取利润表、资产负债表、现金流量表 (带重试与内存缓存)
            df_lrb, df_fzb, df_llb = await _fetch_sina_reports(full_stock_code)

            if df_lrb is None or df_lrb.empty:
                raise HTTPException(status_code=404, detail=f"No financial reports found for {clean_symbol}")

            reports: List[FinancialReportItem] = []
            report_dates = df_lrb["报告日"].dropna().tolist()

            for d in report_dates:
                if len(reports) >= limit:
                    break

                row_lrb = df_lrb[df_lrb["报告日"] == d].iloc[0] if not df_lrb[df_lrb["报告日"] == d].empty else {}
                row_fzb = df_fzb[df_fzb["报告日"] == d].iloc[0] if not df_fzb.empty and not df_fzb[df_fzb["报告日"] == d].empty else {}
                row_llb = df_llb[df_llb["报告日"] == d].iloc[0] if not df_llb.empty and not df_llb[df_llb["报告日"] == d].empty else {}

                rep_date_fmt = _normalize_date_str(d) or str(d)
                ann_date_raw = row_lrb.get("公告日期") if hasattr(row_lrb, "get") else None
                ann_date_fmt = _normalize_date_str(ann_date_raw)

                # Point-in-Time 严格过滤：若指定 as_of，披露日缺失或晚于基准日的报表绝不返回
                if as_of_fmt:
                    if not ann_date_fmt:
                        # 严格 PIT：若披露日未知，绝不伪造报告期为公开日，必须排除以杜绝未来函数
                        continue
                    if ann_date_fmt > as_of_fmt:
                        continue

                rev = float(row_lrb.get("营业总收入") or row_lrb.get("营业收入") or 0.0) if hasattr(row_lrb, "get") else None
                np = float(row_lrb.get("净利润") or row_lrb.get("归属于母公司所有者的净利润") or 0.0) if hasattr(row_lrb, "get") else None
                # 毛利率必须用营业成本 (COGS) 而非营业总成本 (含销售/管理/研发费用)，
                # 后者会得出经营利润率，系统性低估毛利率
                cost = float(row_lrb.get("营业成本") or row_lrb.get("营业总成本") or 0.0) if hasattr(row_lrb, "get") else None

                assets = float(row_fzb.get("资产总计") or 0.0) if hasattr(row_fzb, "get") else None
                liabilities = float(row_fzb.get("负债合计") or 0.0) if hasattr(row_fzb, "get") else None
                ocf = float(row_llb.get("经营活动产生的现金流量净额") or 0.0) if hasattr(row_llb, "get") else None

                # 计算比率
                debt_ratio = round((liabilities / assets) * 100.0, 2) if assets and liabilities and assets > 0 else None
                gross_margin = round(((rev - cost) / rev) * 100.0, 2) if rev and cost and rev > 0 else None
                net_margin = round((np / rev) * 100.0, 2) if rev and np and rev > 0 else None
                roa = round((np / assets) * 100.0, 2) if assets and np and assets > 0 else None

                raw_dict = {}
                if hasattr(row_lrb, "to_dict"):
                    raw_dict.update({k: v for k, v in row_lrb.to_dict().items() if str(v) != "nan" and v is not None})

                reports.append(FinancialReportItem(
                    report_date=rep_date_fmt,
                    announcement_date=ann_date_fmt,
                    revenue=rev if rev and rev > 0 else None,
                    net_profit=np,
                    total_assets=assets if assets and assets > 0 else None,
                    total_liabilities=liabilities if liabilities and liabilities > 0 else None,
                    operating_cash_flow=ocf,
                    gross_margin_pct=gross_margin,
                    net_margin_pct=net_margin,
                    debt_to_asset_pct=debt_ratio,
                    roa=roa,
                    roe=None,  # Sina 利润表无直接 ROE 科目，通过 valuation 接口获取
                    raw_details=raw_dict
                ))

            return FinancialResponse(
                symbol=clean_symbol,
                ticker=ticker,
                market=market_str,
                currency="CNY",
                as_of=as_of_fmt,
                pit_status="STRICT",
                count=len(reports),
                reports=reports
            )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch financials for {clean_symbol}: {str(e)}")

    # 2. 美股、港股海外财报 (基于 yfinance)
    try:
        yf_ticker = ticker if market_str == Market.US.value else f"{ticker.lstrip('0').zfill(4)}.HK"
        loop = asyncio.get_running_loop()

        # 属性访问触发真实 HTTP 请求，必须全部在 executor 内完成，避免阻塞事件循环
        def _fetch_yf_data(t_str: str):
            t_obj = yf.Ticker(t_str)
            return (
                t_obj.quarterly_financials,
                t_obj.quarterly_balance_sheet,
                t_obj.quarterly_cashflow,
                t_obj.info,
            )

        fin, bs, cf, info = await loop.run_in_executor(None, _fetch_yf_data, yf_ticker)

        if fin is None or fin.empty:
            raise HTTPException(status_code=404, detail=f"No financial records found for {clean_symbol}")

        # 从 yfinance.info 提取全年度指标（曾经报告期查询）
        def _safe_pct(val) -> Optional[float]:
            if val is None: return None
            try:
                v = float(val)
                if v == 0 or v != v: return None  # NaN check
                # yfinance 返回小数形式 (0.079)，转化为百分比
                return round(v * 100.0, 2) if abs(v) < 10 else round(v, 2)
            except Exception:
                return None

        info_roa = _safe_pct(info.get('returnOnAssets'))
        info_roe = _safe_pct(info.get('returnOnEquity'))
        info_gross_margin = _safe_pct(info.get('grossMargins'))
        info_profit_margin = _safe_pct(info.get('profitMargins'))

        reports = []
        for col_date in list(fin.columns):
            if len(reports) >= limit:
                break

            d_str = col_date.strftime("%Y-%m-%d")

            # Point-in-Time 过滤
            if as_of_fmt and d_str > as_of_fmt:
                continue

            is_latest = len(reports) == 0  # 只对最新一期填入 info 级别指标

            def _get(df, row, col):
                """精确匹配 col; 如无则取日期最接近的可用列 (bs/cf 更新频率可能慢于 fin)"""
                try:
                    if df is None or row not in df.index:
                        return None
                    if col in df.columns:
                        v = float(df.loc[row, col])
                        return v if v == v else None
                    # 回落: 取 col 之前最近的可用列
                    before = sorted([c for c in df.columns if c <= col], reverse=True)
                    if before:
                        v = float(df.loc[row, before[0]])
                        return v if v == v else None
                except Exception:
                    pass
                return None

            rev = _get(fin, "Total Revenue", col_date)
            np_val = _get(fin, "Net Income", col_date)
            gross_profit = _get(fin, "Gross Profit", col_date)
            assets = _get(bs, "Total Assets", col_date)
            liabilities = _get(bs, "Total Liabilities Net Minority Interest", col_date)
            ocf = _get(cf, "Operating Cash Flow", col_date)

            debt_ratio = round(liabilities / assets * 100.0, 2) if assets and liabilities and assets > 0 else None
            net_margin = round(np_val / rev * 100.0, 2) if rev and np_val and rev > 0 else None
            gross_margin = round(gross_profit / rev * 100.0, 2) if gross_profit and rev and rev > 0 else None

            # 最新期使用 yfinance info 的全年指标作为补充
            if is_latest:
                if gross_margin is None: gross_margin = info_gross_margin
                if net_margin is None: net_margin = info_profit_margin

            # 期初资产取前一列 (同比更早一期)，用于平均资产
            prev_assets = None
            if assets and "Total Assets" in bs.index:
                prev_cols = sorted([c for c in bs.columns if c < col_date], reverse=True)
                if prev_cols:
                    try:
                        prev_v = float(bs.loc["Total Assets", prev_cols[0]])
                        if prev_v == prev_v:
                            prev_assets = prev_v
                    except Exception:
                        pass

            # ROA/ROE 年化: 单季净利 x4 / 平均资产。不年化会把 ROA 低估约 4 倍。
            if np_val and assets and assets > 0:
                avg_assets = (assets + prev_assets) / 2 if prev_assets and prev_assets > 0 else assets
                roa = round((np_val * 4.0) / avg_assets * 100.0, 2)
                # ROE: 用净资产 (Total Stockholders Equity) 计算
                equity = _get(bs, "Stockholders Equity", col_date) or _get(bs, "Common Stock Equity", col_date)
                if equity and equity > 0:
                    avg_equity = equity
                    roe = round((np_val * 4.0) / avg_equity * 100.0, 2)
                else:
                    roe = None
            else:
                roa, roe = None, None

            # 最新期用 info 年度 ROA/ROE 补充 (权威值优先)
            if is_latest:
                if info_roa is not None: roa = info_roa
                if info_roe is not None: roe = info_roe

            reports.append(FinancialReportItem(
                report_date=d_str,
                announcement_date=None,
                revenue=rev,
                net_profit=np_val,
                total_assets=assets,
                total_liabilities=liabilities,
                operating_cash_flow=ocf,
                gross_margin_pct=gross_margin,
                net_margin_pct=net_margin,
                debt_to_asset_pct=debt_ratio,
                roa=roa,
                roe=roe,
                raw_details=None
            ))

        return FinancialResponse(
            symbol=clean_symbol,
            ticker=ticker,
            market=market_str,
            currency="USD" if market_str == Market.US.value else "HKD",
            as_of=as_of_fmt,
            pit_status="ESTIMATED" if as_of_fmt else "UNAVAILABLE",
            count=len(reports),
            reports=reports
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch overseas financials: {str(e)}")

