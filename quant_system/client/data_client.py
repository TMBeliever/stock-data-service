import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
import polars as pl
import httpx
from quant_system.config import quant_config
from quant_system.core.models import Bar, Snapshot

class DataClient:
    """
    智能双模数据客户端：
    1. 【Zero-Copy SDK 模式】：若检测到本地存在 stock-data 源码与 Parquet 数据库，
       直接在内存加载 DuckDB/Polars，免除网络开销，回测提速 50 倍；
    2. 【HTTP REST 模式】：在独立容器或远程服务器部署时，无缝降级为 HTTP 请求 stock-data 服务。
    """
    def __init__(self):
        self._sdk = None
        self._try_init_local_sdk()

    def _try_init_local_sdk(self):
        stock_data_path = Path(quant_config.STOCK_DATA_LOCAL_PATH).resolve()
        if (stock_data_path / "sdk.py").exists():
            try:
                stock_path_str = str(stock_data_path)
                if stock_path_str not in sys.path:
                    sys.path.insert(0, stock_path_str)
                from sdk import StockDataSDK
                self._sdk = StockDataSDK()
            except Exception as e:
                self._sdk = None

    @property
    def is_sdk_available(self) -> bool:
        return self._sdk is not None

    def get_kline_df(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "qfq",
        indicators: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> Optional[pl.DataFrame]:
        """获取 Polars DataFrame 格式 K 线"""
        # 1. 优先本地 SDK (Zero-Copy)
        if self._sdk:
            try:
                df = self._sdk.get_kline(
                    symbol=symbol,
                    period=period,
                    start=start,
                    end=end,
                    adjust=adjust,
                    indicators=indicators,
                    limit=limit
                )
                if df is not None and not df.is_empty():
                    return df
            except ValueError as ve:
                # 若资产无除权因子 (如 ETF / 宽基指数)，自动降级使用原始价格 raw
                if "adjustment factor is unavailable" in str(ve) and adjust != "raw":
                    try:
                        df = self._sdk.get_kline(
                            symbol=symbol,
                            period=period,
                            start=start,
                            end=end,
                            adjust="raw",
                            indicators=indicators,
                            limit=limit
                        )
                        if df is not None and not df.is_empty():
                            return df
                    except Exception:
                        pass
            except Exception:
                pass

        # 2. 降级 HTTP REST API
        url = f"{quant_config.DATA_SERVICE_HTTP.rstrip('/')}/api/v1/kline"
        params: Dict[str, Any] = {"symbol": symbol, "period": period, "adjust": adjust}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = limit

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if not data:
                        return pl.DataFrame()
                    return pl.DataFrame(data)
        except Exception:
            pass

        return None

    def get_bars(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "qfq"
    ) -> List[Bar]:
        """转换为标准的 Bar 对象列表，便于事件驱动回测"""
        df = self.get_kline_df(symbol, period=period, start=start, end=end, adjust=adjust)
        if df is None or df.is_empty():
            return []

        bars: List[Bar] = []
        rows = df.to_dicts()
        for r in rows:
            b = Bar(
                symbol=symbol,
                timestamp=int(r["timestamp"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 0.0)),
                amount=float(r["amount"]) if r.get("amount") is not None else None,
                period=period
            )
            bars.append(b)
        return bars

    def get_snapshots(self, symbols: List[str]) -> Dict[str, Snapshot]:
        """批量获取快照"""
        if not symbols:
            return {}
        if self._sdk:
            try:
                res = self._sdk.get_snapshots(symbols)
                result = {}
                for s in res.data:
                    result[s.symbol] = Snapshot(
                        symbol=s.symbol,
                        timestamp=s.timestamp,
                        price=s.price,
                        open=s.open,
                        high=s.high,
                        low=s.low,
                        prev_close=s.prev_close,
                        volume=s.volume,
                        turnover=s.turnover
                    )
                return result
            except Exception:
                pass

        url = f"{quant_config.DATA_SERVICE_HTTP.rstrip('/')}/api/v1/snapshots"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json={"symbols": symbols})
                if resp.status_code == 200:
                    items = resp.json().get("data", [])
                    return {item["symbol"]: Snapshot(**item) for item in items}
        except Exception:
            pass
        return {}

data_client = DataClient()
