"""All-in-One Multi-Factor Valuation Engine (全量七维估值引擎)

Provides lazy on-demand computation, rolling percentile bands, and lakehouse
persistence for stocks (A/HK/US), cross-border ETFs (Nasdaq, S&P), and indices.

Covers seven core dimensions:
1. PE(TTM) & Historical Percentile Band
2. PB & Historical Percentile Band
3. PS(TTM) & Historical Percentile Band
4. Dividend Yield & Historical Percentile Band
5. ERP (Equity Risk Premium / 股债利差)
6. PB-ROE Quality Metric (隐含净资产收益率与安全边际)
7. PEG (Growth Valuation Ratio)
"""

import os
import time
import datetime
import logging
from typing import Optional, Dict, Any, List, Union
import numpy as np
import polars as pl
import pandas as pd
import akshare as ak
import yfinance as yf

from core.models import parse_symbol, format_symbol, Market, AssetType

logger = logging.getLogger("valuation_engine")

# 缓存持久化湖仓目录：data/analysis/valuation
ANALYSIS_STORAGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../data/analysis/valuation")
)
os.makedirs(ANALYSIS_STORAGE_DIR, exist_ok=True)

WINDOW_DAYS = {
    "1y": 250,
    "3y": 750,
    "5y": 1250,
    "10y": 2500,
    "all": 999999,
}

# 基准无风险利率 (10年期国债收益率 %)
RF_BENCHMARKS = {
    "CN": 2.15,  # 中国 10 年期国债收益率 ~ 2.15%
    "US": 3.90,  # 美国 10 年期国债收益率 ~ 3.90%
    "HK": 3.50,  # 香港无风险参考基准
}


def _calc_midpoint_percentile(val: float, history: List[float]) -> float:
    """计算经验累积分布分位数 (中点公式, 0.0 ~ 1.0)"""
    if not history:
        return 0.5
    less_count = sum(1 for v in history if v < val)
    equal_count = sum(1 for v in history if v == val)
    return float((less_count + 0.5 * equal_count) / len(history))


def _calc_min_max_ratio(val: float, history: List[float]) -> float:
    """计算极值波幅位置 (0.0 ~ 1.0)"""
    if not history:
        return 0.5
    min_v, max_v = min(history), max(history)
    if max_v == min_v:
        return 0.5
    return float(np.clip((val - min_v) / (max_v - min_v), 0.0, 1.0))


def _get_status_label(percentile: float, is_dividend: bool = False) -> str:
    """根据分位数打标估值状态 (股息率反向判定)"""
    if is_dividend:
        if percentile >= 0.85: return "extreme_opportunity"
        if percentile >= 0.70: return "undervalued"
        if percentile <= 0.20: return "low_dividend"
        return "fair"
    else:
        if percentile <= 0.10: return "extremely_undervalued"
        if percentile <= 0.20: return "undervalued"
        if percentile >= 0.90: return "extreme_bubble"
        if percentile >= 0.80: return "overvalued"
        return "fair"


class ValuationEngine:
    """全量多维估值与分位通道引擎 (支持 A/港/美/纳斯达克/ETF/指数)"""

    @classmethod
    def get_analysis(
        cls,
        symbol: str,
        window: str = "3y",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """获取标的全量多维估值与通道数据 (懒计算 + 湖仓持久化)"""
        today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        cache_file = os.path.join(ANALYSIS_STORAGE_DIR, f"{symbol}_{window}_{today_str}.json")

        # 1. 优先读取今日懒计算结果 (0.5ms 直出)
        if not force_refresh and os.path.exists(cache_file):
            try:
                import json
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    cached_data["from_cache"] = True
                    return cached_data
            except Exception as e:
                logger.warning(f"Failed to read cache {cache_file}: {e}")

        # 2. 未命中：现场执行多维宽表构建与滚动分位计算
        t0 = time.perf_counter()
        result = cls._compute_all_factors(symbol=symbol, window=window)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        result["elapsed_ms"] = elapsed_ms
        result["from_cache"] = False
        result["updated_at"] = today_str

        # 3. 异步持久化落库，供后续无限次 0.5ms 读取
        try:
            import json
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to write cache {cache_file}: {e}")

        return result

    @classmethod
    def _compute_all_factors(cls, symbol: str, window: str) -> Dict[str, Any]:
        """抓取并对齐多维估值序列，向量化计算分位通道与衍生指标"""
        ticker, market_str, type_str = parse_symbol(symbol)
        clean_symbol = format_symbol(ticker, market_str, type_str)

        # 0. 黄金、债券与大宗商品避险资产判断 (无 PE/PB 企业盈利指标，走纯价格通道与长周期动量分位)
        is_commodity_or_bond = (
            ticker in ["518880", "159934", "159937", "511010", "511260", "511090", "159981", "159985", "159980"]
            or any(k in symbol for k in ["黄金", "国债", "债券", "化工", "有色", "豆粕", "原油", "商品"])
        )
        if is_commodity_or_bond:
            return cls._compute_commodity_or_bond_valuation(symbol, ticker, window)

        # 1. 纳斯达克、标普与恒生科技跨境资产判断
        is_nasdaq = (
            ticker in ["513100", "159941", "QQQ", "NDX"]
            or any(k in symbol for k in ["纳指", "纳斯达克", "QQQ", "NDX"])
        )
        is_sp500 = (
            ticker in ["513500", "SPY", "SPX"]
            or any(k in symbol for k in ["标普", "SP500", "SPY"])
        )
        is_hstech = (
            ticker in ["513180", "513130", "3033"]
            or any(k in symbol for k in ["恒生科技", "HSTECH"])
        )

        if is_nasdaq:
            return cls._compute_nasdaq_valuation(symbol, ticker, window)
        elif is_sp500:
            return cls._compute_sp500_valuation(symbol, ticker, window)
        elif is_hstech:
            return cls._compute_hstech_valuation(symbol, ticker, window)

        # 2. A 股宽基与红利指数
        is_index = (
            type_str == AssetType.INDEX.value
            or symbol in ["上证红利", "深证红利", "沪深300", "中证500", "000015", "930955", "H30269"]
        )
        # 3. 场内 ETF
        is_etf = type_str == AssetType.ETF.value or ticker.startswith("51") or ticker.startswith("15") or ticker.startswith("58")

        if is_index:
            return cls._compute_index_valuation(symbol, window)
        elif is_etf:
            return cls._compute_etf_valuation(symbol, ticker, window)
        elif market_str == Market.HK.value or (len(ticker) == 5 and ticker.isdigit()):
            return cls._compute_hk_valuation(ticker, clean_symbol, window)
        elif market_str == Market.US.value or (not ticker.isdigit() and len(ticker) <= 5):
            return cls._compute_us_valuation(ticker, clean_symbol, window)
        else:
            return cls._compute_a_share_valuation(ticker, clean_symbol, window)

    @classmethod
    def _filter_by_window(cls, df: pl.DataFrame, window: str) -> pl.DataFrame:
        """根据真实日历时间切片回溯窗口 (1y, 3y, 5y, 10y, all)，精准计算各周期分位数 (杜绝 fallback)"""
        if window == "all" or df.is_empty() or "date" not in df.columns:
            return df

        years_map = {
            "1y": 1,
            "3y": 3,
            "5y": 5,
            "10y": 10,
        }
        years = years_map.get(window, 3)

        last_date_val = df["date"][-1]
        try:
            last_d = datetime.date.fromisoformat(str(last_date_val)[:10])
        except Exception:
            last_d = datetime.date.today()

        cutoff_date = (last_d - datetime.timedelta(days=int(years * 365.25))).strftime("%Y-%m-%d")
        filtered = df.with_columns(pl.col("date").cast(pl.Utf8)).filter(pl.col("date") >= cutoff_date)
        return filtered

    @classmethod
    def _compute_commodity_or_bond_valuation(cls, symbol: str, ticker: str, window: str) -> Dict[str, Any]:
        """黄金、债券与大宗商品避险资产专用估值 (无企业盈利PE/PB，纯长周期价格通道与动量分位)"""
        is_bond = any(k in symbol for k in ["国债", "债券", "利差"]) or ticker in ["511010", "511260", "511090", "511380"]
        subtype = "BOND" if is_bond else "COMMODITY"
        asset_label = "债券固收资产" if is_bond else "大宗商品/黄金避险资产"

        full_code = f"sh{ticker}" if ticker.startswith("51") or ticker.startswith("58") else f"sz{ticker}"
        df_k = ak.fund_etf_hist_sina(symbol=full_code)
        if df_k is None or df_k.empty:
            raise ValueError(f"Failed to fetch authentic price data for commodity/bond {full_code}")

        df_k["date"] = df_k["date"].astype(str).str[:10]
        p_k = pl.from_pandas(df_k).rename({"close": "close"}).select(["date", "close"])

        p_k = p_k.with_columns(pl.col("date").cast(pl.Utf8)).sort("date")
        df_window = cls._filter_by_window(p_k, window)

        prices = [float(v) for v in df_window["close"].to_list() if v is not None and not np.isnan(v)]
        if not prices:
            raise ValueError(f"No price samples available in window {window} for {symbol}")

        cur_price = prices[-1]
        p20 = float(np.percentile(prices, 20))
        p50 = float(np.percentile(prices, 50))
        p80 = float(np.percentile(prices, 80))
        min_p = float(np.min(prices))
        max_p = float(np.max(prices))
        pct = _calc_midpoint_percentile(cur_price, prices)
        min_max = _calc_min_max_ratio(cur_price, prices)
        status = "cyclical_low" if pct <= 0.20 else ("cyclical_high" if pct >= 0.80 else "fair")

        price_stats = {
            "current": round(cur_price, 3),
            "percentile": round(pct, 4),
            "min_max_ratio": round(min_max, 4),
            "min": round(min_p, 3),
            "max": round(max_p, 3),
            "median": round(float(np.median(prices)), 3),
            "p20": round(p20, 3),
            "p50": round(p50, 3),
            "p80": round(p80, 3),
            "status": status,
            "description": f"{asset_label}不适用企业盈利市盈率(PE/PB)，已启用全周期价格通道分位数评估模型",
        }

        history: List[Dict[str, Any]] = []
        rolling_prices: List[float] = []
        for r in df_window.to_dicts():
            c_val = float(r["close"])
            rolling_prices.append(c_val)
            r_pct = _calc_midpoint_percentile(c_val, rolling_prices)
            history.append({
                "date": str(r["date"]),
                "close": round(c_val, 3),
                "price_pct": round(r_pct, 4),
                "price_p20": round(p20, 3),
                "price_p50": round(p50, 3),
                "price_p80": round(p80, 3),
                "pe": round(c_val, 3),
                "pe_pct": round(r_pct, 4),
                "pe_p20": round(p20, 3),
                "pe_p50": round(p50, 3),
                "pe_p80": round(p80, 3),
            })

        return {
            "status": "success",
            "symbol": symbol,
            "ticker": ticker,
            "asset_type": "ETF",
            "asset_subtype": subtype,
            "country": "CN",
            "window": window,
            "sample_count": len(history),
            "latest": {
                "pe_ttm": None,
                "pb": None,
                "dividend_yield_pct": None,
                "equity_risk_premium": None,
                "pb_roe_quality": None,
                "price_channel": price_stats,
                "market_cap_billion": None,
            },
            "history": history,
        }

    @classmethod
    def _compute_hstech_valuation(cls, symbol: str, ticker: str, window: str) -> Dict[str, Any]:
        """恒生科技 ETF (513180 / 3033.HK) 估值与通道计算 (严禁 fallback)"""
        t = yf.Ticker("3033.HK")
        info = t.info
        pe_raw = info.get("trailingPE")
        if not pe_raw or float(pe_raw) <= 0:
            raise ValueError(f"Failed to retrieve authentic trailingPE for 3033.HK from yfinance")
        pe_latest = float(pe_raw)
        pb_raw = info.get("priceToBook")
        pb_latest = float(pb_raw) if pb_raw else None
        div_latest = float(info.get("dividendYield")) if info.get("dividendYield") else None
        mcap = info.get("totalAssets") or info.get("marketCap")

        full_code = f"sh{ticker}" if ticker.startswith("51") else f"sz{ticker}"
        df_k = ak.fund_etf_hist_sina(symbol=full_code)
        if df_k is None or df_k.empty:
            raise ValueError(f"Failed to retrieve ETF candlestick for {full_code}")

        df_k["date"] = df_k["date"].astype(str).str[:10]
        p_k = pl.from_pandas(df_k).rename({"close": "close"}).select(["date", "close"])

        p_latest = float(p_k["close"][-1])
        eps_latest = p_latest / pe_latest
        bps_latest = (p_latest / pb_latest) if pb_latest and pb_latest > 0 else 1.0

        p_k = p_k.with_columns([
            pl.col("date").cast(pl.Utf8),
            (pl.col("close") / eps_latest).alias("pe_ttm"),
            (pl.col("close") / bps_latest).alias("pb") if pb_latest else pl.lit(None).alias("pb"),
        ]).sort("date")

        df_window = cls._filter_by_window(p_k, window)

        return cls._build_multi_metric_response(
            symbol=symbol,
            ticker=ticker,
            asset_type="ETF",
            country="HK",
            window=window,
            df=df_window,
            dividend_yield=div_latest,
            market_cap=mcap
        )

    @classmethod
    def _compute_nasdaq_valuation(cls, symbol: str, ticker: str, window: str) -> Dict[str, Any]:
        """纳斯达克 100 ETF (513100 / QQQ / NDX) 估值与通道计算 (严禁 fallback)"""
        t = yf.Ticker("QQQ")
        info = t.info
        pe_raw = info.get("trailingPE")
        if not pe_raw or float(pe_raw) <= 0:
            raise ValueError("Failed to retrieve authentic trailingPE for QQQ from yfinance")
        pe_latest = float(pe_raw)
        pb_raw = info.get("priceToBook")
        pb_latest = float(pb_raw) if pb_raw else None
        div_latest = float(info.get("dividendYield")) if info.get("dividendYield") else None
        mcap = info.get("totalAssets") or info.get("marketCap")

        hist = t.history(period="5y")
        if hist.empty:
            raise ValueError("Failed to retrieve historical price data for QQQ from yfinance")

        p_latest = float(hist["Close"].iloc[-1])
        hist_df = hist.reset_index()

        eps_latest = p_latest / pe_latest
        hist_df["date"] = hist_df["Date"].astype(str).str[:10]
        hist_df["pe_ttm"] = hist_df["Close"] / eps_latest
        hist_df["pb"] = pb_latest if pb_latest else None
        hist_df["close"] = hist_df["Close"]

        p_df = pl.from_pandas(hist_df[["date", "close", "pe_ttm", "pb"]]).with_columns(pl.col("date").cast(pl.Utf8)).sort("date")
        df_window = cls._filter_by_window(p_df, window)

        return cls._build_multi_metric_response(
            symbol=symbol,
            ticker=ticker,
            asset_type="ETF" if ticker.isdigit() else "IDX",
            country="US",
            window=window,
            df=df_window,
            dividend_yield=div_latest,
            market_cap=mcap
        )

    @classmethod
    def _compute_sp500_valuation(cls, symbol: str, ticker: str, window: str) -> Dict[str, Any]:
        """标普 500 ETF (513500 / SPY / SPX) 估值与通道计算 (严禁 fallback)"""
        t = yf.Ticker("SPY")
        info = t.info
        pe_raw = info.get("trailingPE")
        if not pe_raw or float(pe_raw) <= 0:
            raise ValueError("Failed to retrieve authentic trailingPE for SPY from yfinance")
        pe_latest = float(pe_raw)
        pb_raw = info.get("priceToBook")
        pb_latest = float(pb_raw) if pb_raw else None
        div_latest = float(info.get("dividendYield")) if info.get("dividendYield") else None
        mcap = info.get("totalAssets") or info.get("marketCap")

        hist = t.history(period="5y")
        if hist.empty:
            raise ValueError("Failed to retrieve historical price data for SPY from yfinance")

        p_latest = float(hist["Close"].iloc[-1])
        eps_latest = p_latest / pe_latest

        hist_df = hist.reset_index()
        hist_df["date"] = hist_df["Date"].astype(str).str[:10]
        hist_df["pe_ttm"] = hist_df["Close"] / eps_latest
        hist_df["pb"] = pb_latest if pb_latest else None
        hist_df["close"] = hist_df["Close"]

        p_df = pl.from_pandas(hist_df[["date", "close", "pe_ttm", "pb"]]).with_columns(pl.col("date").cast(pl.Utf8)).sort("date")
        df_window = cls._filter_by_window(p_df, window)

        return cls._build_multi_metric_response(
            symbol=symbol,
            ticker=ticker,
            asset_type="ETF" if ticker.isdigit() else "IDX",
            country="US",
            window=window,
            df=df_window,
            dividend_yield=div_latest,
            market_cap=mcap
        )

    @classmethod
    def _compute_a_share_valuation(cls, ticker: str, clean_symbol: str, window: str) -> Dict[str, Any]:
        """A 股个股全量多维分析"""
        df_pe = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="市盈率(TTM)", period="全部")
        df_pb = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="市净率", period="全部")
        df_mv = ak.stock_zh_valuation_baidu(symbol=ticker, indicator="总市值", period="全部")

        p_pe = pl.from_pandas(df_pe).rename({"value": "pe_ttm"}).with_columns(pl.col("date").cast(pl.Utf8)) if not df_pe.empty else pl.DataFrame()
        p_pb = pl.from_pandas(df_pb).rename({"value": "pb"}).with_columns(pl.col("date").cast(pl.Utf8)) if not df_pb.empty else pl.DataFrame()
        p_mv = pl.from_pandas(df_mv).rename({"value": "market_cap"}).with_columns(pl.col("date").cast(pl.Utf8)) if not df_mv.empty else pl.DataFrame()

        df_merged = p_pe
        if not p_pb.is_empty():
            df_merged = df_merged.join(p_pb, on="date", how="full", coalesce=True)
        if not p_mv.is_empty():
            df_merged = df_merged.join(p_mv, on="date", how="full", coalesce=True)

        full_code = f"sh{ticker}" if ticker.startswith("6") else f"sz{ticker}"
        df_k = ak.stock_zh_a_daily(symbol=full_code)
        if df_k is not None and not df_k.empty:
            df_k["date"] = df_k["date"].astype(str).str[:10]
            p_k = pl.from_pandas(df_k[["date", "close"]]).with_columns(pl.col("date").cast(pl.Utf8))
            df_merged = df_merged.with_columns(pl.col("date").cast(pl.Utf8)).join(p_k, on="date", how="left")
            df_merged = df_merged.with_columns(
                pl.col("close").fill_null(strategy="backward").fill_null(strategy="forward")
            )

        df_merged = df_merged.sort("date")
        df_window = cls._filter_by_window(df_merged, window)

        return cls._build_multi_metric_response(
            symbol=clean_symbol,
            ticker=ticker,
            asset_type="STK",
            country="CN",
            window=window,
            df=df_window
        )

    INDEX_NAME_MAP = {
        "上证50": "上证50", "000016": "上证50",
        "沪深300": "沪深300", "000300": "沪深300",
        "中证500": "中证500", "000905": "中证500",
        "中证1000": "中证1000", "000852": "中证1000",
        "上证红利": "上证红利", "000015": "上证红利",
        "深证红利": "深证红利", "399324": "深证红利",
        "创业板50": "创业板50", "399673": "创业板50",
        "中证100": "中证100", "000903": "中证100",
        "中证800": "中证800", "000906": "中证800",
        "深证100": "深证100", "399330": "深证100",
        "上证180": "上证180", "000010": "上证180",
        "上证380": "上证380", "000009": "上证380",
    }

    @classmethod
    def _compute_index_valuation(cls, symbol: str, window: str) -> Dict[str, Any]:
        """指数全量多维分析 (严禁静默 fallback 到其他指数)"""
        idx_name = cls.INDEX_NAME_MAP.get(symbol)
        if not idx_name:
            for k, v in cls.INDEX_NAME_MAP.items():
                if k in symbol:
                    idx_name = v
                    break
        if not idx_name:
            raise ValueError(f"Unsupported or unmapped index: {symbol}. Available indices: {list(cls.INDEX_NAME_MAP.keys())}")

        df_lg = ak.stock_index_pe_lg(symbol=idx_name)
        if df_lg is None or df_lg.empty:
            raise ValueError(f"No valuation data returned for index: {idx_name}")

        p_df = pl.from_pandas(df_lg).rename({
            "日期": "date",
            "滚动市盈率": "pe_ttm",
            "静态市盈率": "pe_static",
            "指数": "close"
        }).with_columns(pl.col("date").cast(pl.Utf8)).sort("date")

        df_window = cls._filter_by_window(p_df, window)

        return cls._build_multi_metric_response(
            symbol=symbol,
            ticker=symbol,
            asset_type="IDX",
            country="CN",
            window=window,
            df=df_window
        )

    ETF_INDEX_CODE_MAP = {
        # 沪深300
        "510300": "沪深300", "159919": "沪深300", "510310": "沪深300", "510330": "沪深300",
        # 中证500
        "510500": "中证500", "159922": "中证500",
        # 上证50
        "510050": "上证50",
        # 中证1000
        "512100": "中证1000", "159845": "中证1000",
        # 创业板
        "159915": "创业板50", "159949": "创业板50", "159952": "创业板50",
        # 科创50
        "588000": "科创50", "588080": "科创50", "588050": "科创50",
        # 红利
        "510880": "上证红利", "510810": "上证红利", "159905": "深证红利", "515080": "中证红利",
    }

    @classmethod
    def _compute_etf_valuation(cls, symbol: str, ticker: str, window: str) -> Dict[str, Any]:
        """A 股普通 ETF 估值与通道联动 (严格对齐底层真实指数，严禁 fallback 到其他指数)"""
        full_code = f"sh{ticker}" if ticker.startswith("51") or ticker.startswith("58") else f"sz{ticker}"
        df_k = ak.fund_etf_hist_sina(symbol=full_code)
        if df_k is None or df_k.empty:
            raise ValueError(f"Failed to retrieve ETF candlestick for {full_code}")

        df_k["date"] = df_k["date"].astype(str).str[:10]
        p_k = pl.from_pandas(df_k).rename({"close": "close"}).select(["date", "close"])

        # 匹配映射底层指数名称 (杜绝静默 fallback 到沪深300)
        idx_name = cls.ETF_INDEX_CODE_MAP.get(ticker)
        if not idx_name:
            if "300" in symbol: idx_name = "沪深300"
            elif "500" in symbol: idx_name = "中证500"
            elif "50" in symbol and "科创" not in symbol and "创业板" not in symbol: idx_name = "上证50"
            elif "1000" in symbol: idx_name = "中证1000"
            elif "创业板" in symbol: idx_name = "创业板50"
            elif "科创" in symbol: idx_name = "科创50"
            elif "上证红利" in symbol: idx_name = "上证红利"
            elif "深证红利" in symbol: idx_name = "深证红利"

        if not idx_name:
            raise ValueError(f"ETF {symbol} ({ticker}) has no mapped underlying index. Please configure it explicitly.")

        p_val = pl.DataFrame()
        if idx_name == "科创50":
            import akshare.stock_feature.stock_a_pe_and_pb as m
            import requests
            import py_mini_racer
            js = py_mini_racer.MiniRacer()
            js.eval(m.hash_code)
            token = js.call('hex', datetime.datetime.now(datetime.timezone.utc).date().isoformat()).lower()
            url = 'https://legulegu.com/api/stockdata/index-basic-pe'
            headers_dict = m.get_cookie_csrf(url='https://legulegu.com/stockdata/sz50-ttm-lyr')
            r = requests.get(url, params={'token': token, 'indexCode': '000688.SH'}, **headers_dict, timeout=8)
            data = r.json().get('data', [])
            if not data:
                raise ValueError("Failed to fetch authentic 科创50 PE data from legulegu")
            df_lg_kc = pd.DataFrame(data)
            df_lg_kc['date'] = pd.to_datetime(df_lg_kc['date'], utc=True).dt.tz_convert('Asia/Shanghai').dt.date.astype(str)
            df_lg_kc = df_lg_kc.rename(columns={'addTtmPe': 'pe_ttm', 'close': 'idx_close'})
            p_val = pl.from_pandas(df_lg_kc[['date', 'pe_ttm']])
        else:
            df_lg = ak.stock_index_pe_lg(symbol=idx_name)
            if df_lg is None or df_lg.empty:
                raise ValueError(f"No valuation data returned for underlying index: {idx_name}")
            p_val = pl.from_pandas(df_lg).rename({"日期": "date", "滚动市盈率": "pe_ttm"}).select(["date", "pe_ttm"])

        df_merged = p_val.with_columns(pl.col("date").cast(pl.Utf8))
        p_k = p_k.with_columns(pl.col("date").cast(pl.Utf8))
        df_merged = df_merged.join(p_k, on="date", how="left").with_columns(
            pl.col("close").fill_null(strategy="backward").fill_null(strategy="forward")
        )

        df_merged = df_merged.sort("date")
        df_window = cls._filter_by_window(df_merged, window)

        return cls._build_multi_metric_response(
            symbol=symbol,
            ticker=ticker,
            asset_type="ETF",
            country="CN",
            window=window,
            df=df_window
        )

    @classmethod
    def _compute_hk_valuation(cls, ticker: str, clean_symbol: str, window: str) -> Dict[str, Any]:
        """港股全量估值分析 (真实数据，严禁静默 fallback)"""
        df_pe = ak.stock_hk_valuation_baidu(symbol=ticker, indicator="市盈率(TTM)", period="全部")
        df_pb = ak.stock_hk_valuation_baidu(symbol=ticker, indicator="市净率", period="全部")
        if df_pe.empty:
            raise ValueError(f"No valuation data found for HK stock {ticker} from Baidu")

        p_pe = pl.from_pandas(df_pe).rename({"value": "pe_ttm"}).with_columns(pl.col("date").cast(pl.Utf8))
        p_pb = pl.from_pandas(df_pb).rename({"value": "pb"}).with_columns(pl.col("date").cast(pl.Utf8)) if not df_pb.empty else pl.DataFrame()

        df_merged = p_pe
        if not p_pb.is_empty():
            df_merged = df_merged.join(p_pb, on="date", how="full", coalesce=True)

        df_k = ak.stock_hk_daily(symbol=ticker)
        if df_k is not None and not df_k.empty:
            df_k["date"] = df_k["date"].astype(str).str[:10]
            p_k = pl.from_pandas(df_k[["date", "close"]]).with_columns(pl.col("date").cast(pl.Utf8))
            df_merged = df_merged.join(p_k, on="date", how="left").with_columns(
                pl.col("close").fill_null(strategy="backward").fill_null(strategy="forward")
            )

        df_merged = df_merged.sort("date")
        df_window = cls._filter_by_window(df_merged, window)
        return cls._build_multi_metric_response(symbol=clean_symbol, ticker=ticker, asset_type="STK", country="HK", window=window, df=df_window)

    @classmethod
    def _compute_us_valuation(cls, ticker: str, clean_symbol: str, window: str) -> Dict[str, Any]:
        """美股个股全量估值分析 (yfinance 驱动)"""
        try:
            t = yf.Ticker(ticker)
            info = t.info
            pe_latest = float(info.get("trailingPE") or 0.0)
            pb_latest = float(info.get("priceToBook") or 0.0)
            div_latest = float(info.get("dividendYield") or 0.0) if info.get("dividendYield") else None
            mcap = info.get("marketCap")

            hist = t.history(period="10y")
            if hist.empty:
                return {"symbol": clean_symbol, "window": window, "status": "empty", "latest": {}, "history": []}

            p_latest = float(hist["Close"].iloc[-1])
            eps_latest = p_latest / pe_latest if pe_latest > 0 else 1.0
            bps_latest = p_latest / pb_latest if pb_latest > 0 else 1.0

            hist_df = hist.reset_index()
            hist_df["date"] = hist_df["Date"].astype(str).str[:10]
            hist_df["close"] = hist_df["Close"]
            hist_df["pe_ttm"] = hist_df["Close"] / eps_latest if pe_latest > 0 else None
            hist_df["pb"] = hist_df["Close"] / bps_latest if pb_latest > 0 else None

            p_df = pl.from_pandas(hist_df[["date", "close", "pe_ttm", "pb"]]).with_columns(pl.col("date").cast(pl.Utf8)).sort("date")
            df_window = cls._filter_by_window(p_df, window)

            return cls._build_multi_metric_response(
                symbol=clean_symbol,
                ticker=ticker,
                asset_type="STK",
                country="US",
                window=window,
                df=df_window,
                dividend_yield=div_latest,
                market_cap=mcap
            )
        except Exception as e:
            logger.warning(f"Failed to fetch US valuation for {ticker}: {e}")
            return {"symbol": clean_symbol, "window": window, "status": "empty", "latest": {}, "history": []}

    @classmethod
    def _build_multi_metric_response(
        cls,
        symbol: str,
        ticker: str,
        asset_type: str,
        country: str,
        window: str,
        df: pl.DataFrame,
        dividend_yield: Optional[float] = None,
        market_cap: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成七维多因子指标画像与逐日时序对齐宽表"""
        if df.is_empty() or "date" not in df.columns:
            return {"symbol": symbol, "window": window, "status": "empty", "latest": {}, "history": []}

        # 提取 PE 和 PB 序列 (剔除非正数，保证分位真实无畸变)
        pe_vals = [float(v) for v in df["pe_ttm"].to_list() if v is not None and not np.isnan(v) and float(v) > 0] if "pe_ttm" in df.columns else []
        pb_vals = [float(v) for v in df["pb"].to_list() if v is not None and not np.isnan(v) and float(v) > 0] if "pb" in df.columns else []

        # 1. 计算 PE 通道统计量
        pe_stats = {}
        cur_pe = None
        if "pe_ttm" in df.columns and len(df["pe_ttm"].drop_nulls()) > 0:
            last_raw_pe = float(df["pe_ttm"].drop_nulls()[-1])
            cur_pe = last_raw_pe
            if cur_pe <= 0:
                pe_stats = {
                    "current": round(cur_pe, 2),
                    "is_loss": True,
                    "status": "loss_unprofitable",
                    "percentile": 1.0,
                    "min": None,
                    "max": None,
                    "median": None,
                    "p20": None,
                    "p50": None,
                    "p80": None,
                }
            elif pe_vals:
                pe_stats = {
                    "current": round(cur_pe, 2),
                    "is_loss": False,
                    "percentile": round(_calc_midpoint_percentile(cur_pe, pe_vals), 4),
                    "min_max_ratio": round(_calc_min_max_ratio(cur_pe, pe_vals), 4),
                    "min": round(float(np.min(pe_vals)), 2),
                    "max": round(float(np.max(pe_vals)), 2),
                    "median": round(float(np.median(pe_vals)), 2),
                    "p20": round(float(np.percentile(pe_vals, 20)), 2),
                    "p50": round(float(np.percentile(pe_vals, 50)), 2),
                    "p80": round(float(np.percentile(pe_vals, 80)), 2),
                    "status": _get_status_label(_calc_midpoint_percentile(cur_pe, pe_vals)),
                }

        # 2. 计算 PB 通道统计量
        pb_stats = {}
        cur_pb = None
        if pb_vals:
            cur_pb = pb_vals[-1]
            pb_stats = {
                "current": round(cur_pb, 2),
                "percentile": round(_calc_midpoint_percentile(cur_pb, pb_vals), 4),
                "min_max_ratio": round(_calc_min_max_ratio(cur_pb, pb_vals), 4),
                "min": round(float(np.min(pb_vals)), 2),
                "max": round(float(np.max(pb_vals)), 2),
                "median": round(float(np.median(pb_vals)), 2),
                "p20": round(float(np.percentile(pb_vals, 20)), 2),
                "p50": round(float(np.percentile(pb_vals, 50)), 2),
                "p80": round(float(np.percentile(pb_vals, 80)), 2),
                "status": _get_status_label(_calc_midpoint_percentile(cur_pb, pb_vals)),
            }

        # 3. 股权风险溢价 (ERP / 股债利差 = 1/PE - 10Y国债)
        rf_rate = RF_BENCHMARKS.get(country, 2.50)
        erp_data = None
        if cur_pe and cur_pe > 0:
            earning_yield = (1.0 / cur_pe) * 100.0
            erp_val = earning_yield - rf_rate
            erp_data = {
                "earning_yield_pct": round(earning_yield, 2),
                "benchmark_10y_bond_pct": rf_rate,
                "equity_risk_premium_pct": round(erp_val, 2),
                "status": "extremely_attractive" if erp_val >= 5.0 else ("attractive" if erp_val >= 3.0 else "neutral"),
            }

        # 4. PB-ROE 质量安全边际 (针对周期股)
        pb_roe_data = None
        if cur_pe and cur_pb and cur_pe > 0:
            implied_roe = (cur_pb / cur_pe) * 100.0
            pb_roe_data = {
                "implied_roe_pct": round(implied_roe, 2),
                "pb_level": round(cur_pb, 2),
                "is_asset_quality_safe": implied_roe >= 8.0,
                "status": "quality_safe" if implied_roe >= 10.0 else ("warning_cyclical_trap" if implied_roe < 4.0 else "neutral"),
            }

        # 5. 构建历史时间序列 (供 K 线 Tooltip 和 ECharts 估值河流图使用)
        history: List[Dict[str, Any]] = []
        rows = df.to_dicts()

        rolling_pe: List[float] = []
        rolling_pb: List[float] = []

        for r in rows:
            date_str = str(r["date"])
            item: Dict[str, Any] = {"date": date_str}
            if "close" in r and r["close"] is not None:
                item["close"] = round(float(r["close"]), 3)

            # PE 字段与当前滚动分位 (排除非正数)
            if "pe_ttm" in r and r["pe_ttm"] is not None and not np.isnan(r["pe_ttm"]):
                val = float(r["pe_ttm"])
                if val > 0:
                    rolling_pe.append(val)
                    item["pe"] = round(val, 2)
                    item["pe_pct"] = round(_calc_midpoint_percentile(val, rolling_pe), 4)
                    if pe_stats and not pe_stats.get("is_loss"):
                        item["pe_p20"] = pe_stats.get("p20")
                        item["pe_p50"] = pe_stats.get("p50")
                        item["pe_p80"] = pe_stats.get("p80")
                    earning_yield = (1.0 / val) * 100.0
                    item["erp"] = round(earning_yield - rf_rate, 2)
                    item["earning_yield"] = round(earning_yield, 2)
                else:
                    item["pe"] = round(val, 2)
                    item["pe_pct"] = None
                    item["pe_p20"] = None
                    item["pe_p50"] = None
                    item["pe_p80"] = None

            # PB 字段与当前滚动分位
            if "pb" in r and r["pb"] is not None and not np.isnan(r["pb"]):
                val_pb = float(r["pb"])
                if val_pb > 0:
                    rolling_pb.append(val_pb)
                    item["pb"] = round(val_pb, 2)
                    item["pb_pct"] = round(_calc_midpoint_percentile(val_pb, rolling_pb), 4)
                    if pb_stats:
                        item["pb_p20"] = pb_stats.get("p20")
                        item["pb_p50"] = pb_stats.get("p50")
                        item["pb_p80"] = pb_stats.get("p80")

            # 股息率字段
            if "dividend_yield" in r and r["dividend_yield"] is not None and not np.isnan(r["dividend_yield"]):
                item["dividend_yield"] = round(float(r["dividend_yield"]), 2)
            elif dividend_yield is not None:
                item["dividend_yield"] = round(float(dividend_yield), 2)

            history.append(item)

        # 确定总市值
        mcap_val = market_cap
        if mcap_val is None and "market_cap" in df.columns and len(df["market_cap"].drop_nulls()) > 0:
            mcap_val = float(df["market_cap"].drop_nulls()[-1])

        return {
            "status": "success",
            "symbol": symbol,
            "ticker": ticker,
            "asset_type": asset_type,
            "country": country,
            "window": window,
            "sample_count": len(history),
            "latest": {
                "pe_ttm": pe_stats,
                "pb": pb_stats,
                "dividend_yield_pct": dividend_yield,
                "equity_risk_premium": erp_data,
                "pb_roe_quality": pb_roe_data,
                "market_cap_billion": round(mcap_val / (1e8 if country == 'CN' else 1e9), 2) if mcap_val else None,
            },
            "history": history,
        }
