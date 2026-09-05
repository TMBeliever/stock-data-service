import os
import glob
import datetime
from typing import Optional, List, Dict, Any
import polars as pl
import httpx
from quant_core.config import quant_config
from quant_core.core.models import Bar, Snapshot

class DataClient:
    """
    双模数据客户端 (Dual-Mode Data Client)：
    1. 优先从 Monorepo 本地 packages/stock-data/data/ 零拷贝秒级读取本地 Parquet；
    2. 本地不存在时自动降级向基础数据服务 (http://43.155.186.45:8000) 发起 HTTP 请求。
    """
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or quant_config.DATA_SERVICE_HTTP).rstrip("/")

    def _try_get_local_parquet(
        self,
        symbol: str,
        period: str = "1d",
        start: Optional[str] = None,
        end: Optional[str] = None,
        adjust: str = "raw"
    ) -> Optional[pl.DataFrame]:
        """尝试从本地 stock-data 存储目录零拷贝读取 Parquet，并支持动态 QFQ/HFQ 复权"""
        possible_dirs = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../stock-data/data")),
            os.path.abspath("packages/stock-data/data"),
            os.path.abspath("../stock-data/data"),
        ]
        base_dir = next((d for d in possible_dirs if os.path.exists(d)), None)
        if not base_dir:
            return None

        code = symbol.split(".")[0]
        matches = glob.glob(f"{base_dir}/**/{code}*.parquet", recursive=True)
        if not matches:
            return None

        try:
            df = pl.read_parquet(matches[0])
            if "timestamp" not in df.columns:
                return None

            # 动态复权处理 (QFQ 前复权 / HFQ 后复权)
            if "factor" in df.columns and adjust.lower() in ("qfq", "hfq"):
                valid_factors = df["factor"].drop_nulls()
                if len(valid_factors) > 0:
                    latest_factor = float(valid_factors[-1]) if valid_factors[-1] is not None and valid_factors[-1] > 0 else 1.0
                    
                    # 异常因子防御校验：防止历史因子未拉取 (全部为 1.0) 导致前复权历史价格失真断崖
                    is_corrupted = False
                    if len(valid_factors) > 20 and abs(latest_factor - 1.0) > 0.1:
                        ones_ratio = (valid_factors == 1.0).sum() / len(valid_factors)
                        if ones_ratio > 0.90:
                            is_corrupted = True

                    if is_corrupted:
                        # 本地因子历史存在严重缺陷，降级放弃本地缓存，触发从远程/适配器重拉
                        return None

                    filled_factor = pl.col("factor").forward_fill().backward_fill()
                    if adjust.lower() == "qfq":
                        ratio = filled_factor / latest_factor
                    else:  # hfq
                        ratio = filled_factor

                    df = df.with_columns([
                        (pl.col("open") * ratio).cast(pl.Float32).alias("open"),
                        (pl.col("high") * ratio).cast(pl.Float32).alias("high"),
                        (pl.col("low") * ratio).cast(pl.Float32).alias("low"),
                        (pl.col("close") * ratio).cast(pl.Float32).alias("close"),
                    ])

            if start:
                try:
                    s_dt = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                    s_ts = int(s_dt.timestamp() * 1000)
                    df = df.filter(pl.col("timestamp") >= s_ts)
                except Exception:
                    pass
            if end:
                try:
                    e_dt = datetime.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                    e_ts = int(e_dt.timestamp() * 1000) + 86400000
                    df = df.filter(pl.col("timestamp") <= e_ts)
                except Exception:
                    pass

            return df
        except Exception:
            return None

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
        """优先本地读取，回落 HTTP 服务 (若设置 FORCE_REMOTE 则直连线上中台)"""
        # 1. 尝试本地 Parquet 直读 (在未开启 FORCE_REMOTE 时，0.001s 极速直通，支持 QFQ)
        if not quant_config.FORCE_REMOTE:
            local_df = self._try_get_local_parquet(symbol, period=period, start=start, end=end, adjust=adjust)
            if local_df is not None and not local_df.is_empty():
                return local_df

        # 2. 回落 HTTP 远程请求
        url = f"{self.base_url}/api/v1/kline"
        params: Dict[str, Any] = {"symbol": symbol, "period": period, "adjust": adjust}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = limit

        try:
            with httpx.Client(timeout=90.0) as client:
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
        adjust: str = "qfq"
    ) -> List[Bar]:
        """从基础数据服务或本地存储拉取并转换为标准的 Bar 对象列表 (默认采用 QFQ 前复权保证连续性)"""
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
