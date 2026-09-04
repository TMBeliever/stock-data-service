import datetime
from typing import List, Optional
import polars as pl
import pandas as pd
import akshare as ak
from adapters.base import BaseDataSource
from core.models import SymbolInfo, KlinePeriod, AssetType, Market

def _beijing_to_utc_ms(date_str: str, time_str: str = "15:00:00") -> int:
    """将北京时间 (UTC+8) 转换为 UTC 毫秒时间戳"""
    dt_str = f"{date_str} {time_str}"
    # Python 3.11+
    dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    tz_beijing = datetime.timezone(datetime.timedelta(hours=8))
    dt_bj = dt.replace(tzinfo=tz_beijing)
    return int(dt_bj.timestamp() * 1000)

class AkShareAdapter(BaseDataSource):
    """A股、指数与国内 ETF 适配器 (基于 AkShare 真实数据)"""

    def fetch_daily(self, info: SymbolInfo, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        start_clean = start_date.replace("-", "")
        end_clean = end_date.replace("-", "")
        ticker = info.ticker
        market_code = "sh" if info.market == Market.SH else ("sz" if info.market == Market.SZ else "bj")
        full_code = f"{market_code}{ticker}"

        # 格式化日期为 YYYY-MM-DD
        if len(start_date) == 8:
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        else:
            start_fmt = start_date
            end_fmt = end_date

        try:
            df_raw: Optional[pd.DataFrame] = None
            
            if info.asset_type == AssetType.STOCK:
                # 采用新浪源，不受本地代理阻断
                try:
                    df_raw = ak.stock_zh_a_daily(symbol=full_code, start_date=start_clean, end_date=end_clean)
                except Exception:
                    # 备用东方财富
                    df_raw = ak.stock_zh_a_hist(symbol=ticker, period="daily", start_date=start_clean, end_date=end_clean, adjust="")
            elif info.asset_type == AssetType.INDEX:
                # 宽基指数日K (新浪源)
                try:
                    df_raw = ak.stock_zh_index_daily(symbol=full_code)
                except Exception:
                    df_raw = ak.stock_zh_index_daily_em(symbol=full_code)
            elif info.asset_type == AssetType.ETF:
                # ETF 日K (新浪源)
                try:
                    df_raw = ak.fund_etf_hist_sina(symbol=full_code)
                except Exception:
                    df_raw = ak.fund_etf_hist_em(symbol=ticker, period="daily", start_date=start_clean, end_date=end_clean, adjust="")

            if df_raw is None or df_raw.empty:
                return None

            date_col = "date" if "date" in df_raw.columns else ("日期" if "日期" in df_raw.columns else None)
            open_col = "open" if "open" in df_raw.columns else ("开盘" if "开盘" in df_raw.columns else None)
            high_col = "high" if "high" in df_raw.columns else ("最高" if "最高" in df_raw.columns else None)
            low_col = "low" if "low" in df_raw.columns else ("最低" if "最低" in df_raw.columns else None)
            close_col = "close" if "close" in df_raw.columns else ("收盘" if "收盘" in df_raw.columns else None)
            vol_col = "volume" if "volume" in df_raw.columns else ("成交量" if "成交量" in df_raw.columns else None)
            amt_col = "amount" if "amount" in df_raw.columns else ("成交额" if "成交额" in df_raw.columns else None)

            if not date_col or not close_col:
                return None

            # 过滤日期区间
            df_raw[date_col] = df_raw[date_col].astype(str)
            if "-" not in start_date:
                start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            else:
                start_fmt = start_date
                end_fmt = end_date

            df_raw = df_raw[(df_raw[date_col] >= start_fmt) & (df_raw[date_col] <= end_fmt)]
            if df_raw.empty:
                return None

            timestamps = [_beijing_to_utc_ms(d) for d in df_raw[date_col]]

            # 获取真实复权因子 (基于后复权真实价格 / 原始价格，缺失或未知时为 None，严禁静默填 1.0)
            factors = [None] * len(df_raw)
            if info.asset_type == AssetType.STOCK:
                try:
                    df_hfq = ak.stock_zh_a_daily(symbol=full_code, adjust="hfq", start_date=start_clean, end_date=end_clean)
                    if df_hfq is not None and not df_hfq.empty:
                        hfq_date_col = "date" if "date" in df_hfq.columns else ("日期" if "日期" in df_hfq.columns else None)
                        hfq_close_col = "close" if "close" in df_hfq.columns else ("收盘" if "收盘" in df_hfq.columns else None)
                        if hfq_date_col and hfq_close_col:
                            df_hfq[hfq_date_col] = df_hfq[hfq_date_col].astype(str)
                            hfq_map = dict(zip(df_hfq[hfq_date_col], df_hfq[hfq_close_col].astype(float)))
                            computed_factors = []
                            for idx, r_date in enumerate(df_raw[date_col]):
                                raw_c = float(df_raw[close_col].iloc[idx])
                                hfq_c = hfq_map.get(str(r_date))
                                if hfq_c is not None and raw_c > 0:
                                    computed_factors.append(round(hfq_c / raw_c, 6))
                                else:
                                    computed_factors.append(None)
                            factors = computed_factors
                except Exception as e:
                    print(f"[AkShareAdapter] Warning: failed to fetch hfq factor for {info.symbol}: {e}")
            elif info.asset_type == AssetType.ETF:
                try:
                    df_acc = ak.fund_open_fund_info_em(symbol=ticker, indicator="累计净值走势")
                    df_unit = ak.fund_open_fund_info_em(symbol=ticker, indicator="单位净值走势")
                    if df_acc is not None and df_unit is not None and not df_acc.empty and not df_unit.empty:
                        df_acc["净值日期"] = df_acc["净值日期"].astype(str)
                        df_unit["净值日期"] = df_unit["净值日期"].astype(str)
                        m_nav = pd.merge(df_acc[["净值日期", "累计净值"]], df_unit[["净值日期", "单位净值"]], on="净值日期")
                        m_nav["factor"] = m_nav["累计净值"] / m_nav["单位净值"]
                        nav_map = dict(zip(m_nav["净值日期"], m_nav["factor"]))
                        factors = [nav_map.get(str(d), None) for d in df_raw[date_col]]
                except Exception as e:
                    print(f"[AkShareAdapter] Warning: failed to fetch ETF nav factor for {info.symbol}: {e}")


            # 组织为标准 Polars DataFrame
            pldf = pl.DataFrame({
                "timestamp": pl.Series(timestamps, dtype=pl.Int64),
                "open": pl.Series(df_raw[open_col].astype(float), dtype=pl.Float32),
                "high": pl.Series(df_raw[high_col].astype(float), dtype=pl.Float32),
                "low": pl.Series(df_raw[low_col].astype(float), dtype=pl.Float32),
                "close": pl.Series(df_raw[close_col].astype(float), dtype=pl.Float32),
                "volume": pl.Series(df_raw[vol_col].astype(float), dtype=pl.Float64),
                "amount": pl.Series(df_raw[amt_col].astype(float) if amt_col in df_raw.columns else [0.0]*len(df_raw), dtype=pl.Float64),
                "factor": pl.Series(factors, dtype=pl.Float32),
                "nav": pl.Series([None] * len(df_raw), dtype=pl.Float32)
            })

            return pldf.sort("timestamp")

        except Exception as e:
            # 记录日志并返回 None
            print(f"[AkShareAdapter] Error fetching daily for {info.symbol}: {e}")
            return None

    def fetch_minute(self, info: SymbolInfo, period: KlinePeriod, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        """抓取分钟K线 (如 1m, 5m)，支持严格日期过滤与对齐日频真实复权因子"""
        ticker = info.ticker
        period_str = period.value.replace("m", "") # "1", "5"
        try:
            if info.asset_type == AssetType.STOCK:
                df_raw = ak.stock_zh_a_hist_min_em(symbol=ticker, period=period_str, adjust="")
            elif info.asset_type == AssetType.ETF:
                df_raw = ak.fund_etf_hist_min_em(symbol=ticker, period=period_str, adjust="")
            else:
                return None

            if df_raw is None or df_raw.empty:
                return None

            # 严格日期区间过滤 (基于 A 股本地自然交易日 YYYY-MM-DD)
            df_raw["时间_str"] = df_raw["时间"].astype(str)
            df_raw["trading_date"] = df_raw["时间_str"].str[:10]
            df_filtered = df_raw[(df_raw["trading_date"] >= start_date) & (df_raw["trading_date"] <= end_date)].copy()

            if df_filtered.empty:
                return None

            # 若为个股，拉取对应日期的真实日度复权因子并对齐到分钟 bar
            factor_map = {}
            if info.asset_type == AssetType.STOCK:
                try:
                    df_daily = self.fetch_daily(info, start_date, end_date)
                    if df_daily is not None and not df_daily.is_empty():
                        for row in df_daily.iter_rows(named=True):
                            ts = row["timestamp"]
                            d_str = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")
                            factor_map[d_str] = row["factor"]
                except Exception as e:
                    print(f"[AkShareAdapter] Notice: failed to map daily factor to minute for {info.symbol}: {e}")

            # 列名: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额
            timestamps = []
            factors = []
            for _, r in df_filtered.iterrows():
                t_str = r["时间_str"]
                d_str = r["trading_date"]
                dt = datetime.datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S")
                dt_bj = dt.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
                timestamps.append(int(dt_bj.timestamp() * 1000))
                factors.append(factor_map.get(d_str))

            pldf = pl.DataFrame({
                "timestamp": pl.Series(timestamps, dtype=pl.Int64),
                "open": pl.Series(df_filtered["开盘"].astype(float), dtype=pl.Float32),
                "high": pl.Series(df_filtered["最高"].astype(float), dtype=pl.Float32),
                "low": pl.Series(df_filtered["最低"].astype(float), dtype=pl.Float32),
                "close": pl.Series(df_filtered["收盘"].astype(float), dtype=pl.Float32),
                "volume": pl.Series(df_filtered["成交量"].astype(float), dtype=pl.Float64),
                "amount": pl.Series(df_filtered["成交额"].astype(float), dtype=pl.Float64),
                "factor": pl.Series(factors, dtype=pl.Float32),
                "nav": pl.Series([None] * len(df_filtered), dtype=pl.Float32)
            })

            return pldf.sort("timestamp")
        except Exception as e:
            print(f"[AkShareAdapter] Error fetching minute for {info.symbol}: {e}")
            return None

    def fetch_snapshot(self, market: str) -> Optional[pl.DataFrame]:
        """抓取全市场今日最新快照"""
        try:
            df_raw = ak.stock_zh_a_spot_em()
            if df_raw is None or df_raw.empty:
                return None
            # 提取关键字段: 代码, 名称, 最新价, 涨跌幅, 换手率, 成交量, 成交额, 市盈率-动态, 市净率
            pldf = pl.DataFrame({
                "ticker": pl.Series(df_raw["代码"].astype(str)),
                "name": pl.Series(df_raw["名称"].astype(str)),
                "latest_price": pl.Series(df_raw["最新价"].astype(float), dtype=pl.Float32),
                "pct_change": pl.Series(df_raw["涨跌幅"].astype(float), dtype=pl.Float32),
                "turnover_rate": pl.Series(df_raw["换手率"].astype(float), dtype=pl.Float32),
                "volume": pl.Series(df_raw["成交量"].astype(float), dtype=pl.Float64),
                "amount": pl.Series(df_raw["成交额"].astype(float), dtype=pl.Float64),
                "pe_dynamic": pl.Series(df_raw["市盈率-动态"].astype(float), dtype=pl.Float32),
                "pb": pl.Series(df_raw["市净率"].astype(float), dtype=pl.Float32),
            })
            return pldf
        except Exception as e:
            print(f"[AkShareAdapter] Error fetching snapshot: {e}")
            return None

    def fetch_calendar(self, market: str, year: int) -> List[dict]:
        try:
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                # 列为 trade_date
                dates = df["trade_date"].astype(str).tolist()
                return [{"market": market, "trade_date": d, "is_open": True} for d in dates if d.startswith(str(year))]
        except Exception as e:
            print(f"[AkShareAdapter] Error fetching calendar: {e}")
        return []

    def fetch_symbols(self, market: str) -> List[SymbolInfo]:
        """抓取 A股基础股票列表"""
        results = []
        try:
            df = ak.stock_info_a_code_name()
            for _, row in df.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                m = Market.SH if code.startswith("6") or code.startswith("688") else (Market.BJ if code.startswith("8") or code.startswith("4") or code.startswith("9") else Market.SZ)
                if m.value == market:
                    sym = f"{code}.{m.value}.STK"
                    results.append(SymbolInfo(
                        symbol=sym,
                        ticker=code,
                        market=m,
                        asset_type=AssetType.STOCK,
                        name=name,
                        currency="CNY"
                    ))
        except Exception as e:
            print(f"[AkShareAdapter] Error fetching symbols: {e}")
        return results
