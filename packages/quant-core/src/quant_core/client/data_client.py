import os
from typing import Optional, List, Dict, Any
import polars as pl
import httpx
from quant_core.config import quant_config
from quant_core.core.models import Bar, Snapshot

class DataClient:
    """
    基础数据中台 HTTP 客户端：
    严格且永远仅从基础服务接口 (http://43.155.186.45:8000) 拉取行情与元数据。
    """
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or quant_config.DATA_SERVICE_HTTP).rstrip("/")

    def get_kline_df(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "raw",
        indicators: Optional[list[str]] = None,
        limit: Optional[int] = None
    ) -> Optional[pl.DataFrame]:
        """从基础数据服务获取 Polars DataFrame 格式 K 线"""
        url = f"{self.base_url}/api/v1/kline"
        params: Dict[str, Any] = {"symbol": symbol, "period": period, "adjust": adjust}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = limit

        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if not data:
                        return pl.DataFrame()
                    return pl.DataFrame(data)
                elif resp.status_code == 400 and adjust != "raw":
                    # 若资产无除权因子 (如 ETF / 指数)，自动降级请求 raw 原始行情
                    params["adjust"] = "raw"
                    retry_resp = client.get(url, params=params)
                    if retry_resp.status_code == 200:
                        data = retry_resp.json().get("data", [])
                        if not data:
                            return pl.DataFrame()
                        return pl.DataFrame(data)
                else:
                    print(f"[DataClient] HTTP Error {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[DataClient] Request failed for {url}: {e}")

        return None

    def get_bars(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "raw"
    ) -> List[Bar]:
        """从基础数据服务拉取并转换为标准的 Bar 对象列表，供事件驱动回测使用"""
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
        """批量获取股票实时行情快照"""
        if not symbols:
            return {}

        url = f"{self.base_url}/api/v1/snapshots"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json={"symbols": symbols})
                if resp.status_code == 200:
                    items = resp.json().get("data", [])
                    return {item["symbol"]: Snapshot(**item) for item in items}
        except Exception as e:
            print(f"[DataClient] Snapshot request failed: {e}")
        return {}

    def get_symbols(self, market: Optional[str] = None, asset_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取基础数据服务中注册的全资产元数据"""
        url = f"{self.base_url}/api/v1/meta/symbols"
        params = {}
        if market:
            params["market"] = market
        if asset_type:
            params["type"] = asset_type
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.json().get("symbols", [])
        except Exception as e:
            print(f"[DataClient] Symbols meta request failed: {e}")
        return []

    def check_health(self) -> bool:
        """检查基础数据服务的健康状态与存储水位"""
        url = f"{self.base_url}/api/v1/system/storage"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                return resp.status_code == 200 and resp.json().get("is_safe", False)
        except Exception:
            return False

data_client = DataClient()
