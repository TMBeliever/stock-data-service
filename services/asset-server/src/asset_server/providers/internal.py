import time
import logging
from typing import List, Dict, Tuple
import httpx
from asset_server.providers.base import BaseMarketDataProvider, QuoteSnapshot

logger = logging.getLogger("asset_server.providers.internal")


class InternalStockDataProvider(BaseMarketDataProvider):
    """
    基于内部 stock-data 服务的行情适配器
    通过 HTTP POST /api/v1/snapshot/batch 批量拉取跨市场实时快照，并附带短缓存防击穿。
    """

    def __init__(self, base_url: str, timeout: float = 5.0, cache_ttl: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        # 内存短缓存: symbol -> (QuoteSnapshot, cache_timestamp)
        self._cache: Dict[str, Tuple[QuoteSnapshot, float]] = {}
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                trust_env=False,
            )
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        clean_symbols = list(set(s.strip() for s in symbols if s and s.strip()))
        if not clean_symbols:
            return {}

        now = time.time()
        result: Dict[str, QuoteSnapshot] = {}
        missing_symbols: List[str] = []

        # 1. 优先命中本地短缓存
        for sym in clean_symbols:
            cached = self._cache.get(sym)
            if cached and (now - cached[1]) < self.cache_ttl:
                result[sym] = cached[0]
            else:
                missing_symbols.append(sym)

        if not missing_symbols:
            return result

        # 2. 向 stock-data 发起批量快照请求
        url = f"{self.base_url}/api/v1/snapshot/batch"
        client = self._get_client()
        try:
            resp = await client.post(url, json={"symbols": missing_symbols})
            if resp.status_code == 200:
                payload = resp.json()
                items = payload.get("data", [])
                for item in items:
                    sym = item.get("symbol")
                    ticker = item.get("ticker")
                    raw_price = item.get("latest_price") if item.get("latest_price") is not None else item.get("price")
                    raw_prev_close = item.get("pre_close") if item.get("pre_close") is not None else item.get("prev_close")
                    raw_change_pct = item.get("pct_change") if item.get("pct_change") is not None else item.get("change_percent")

                    prev_close = float(raw_prev_close) if raw_prev_close is not None else 0.0
                    if raw_price is not None and float(raw_price) > 0:
                        price = float(raw_price)
                    elif prev_close > 0:
                        price = prev_close
                    else:
                        price = 0.0

                    change_pct = float(raw_change_pct) if raw_change_pct is not None else 0.0

                    snap = QuoteSnapshot(
                        symbol=sym,
                        price=price,
                        prev_close=prev_close,
                        change_pct=change_pct,
                        source="stock-data",
                    )
                    if sym:
                        result[sym] = snap
                        self._cache[sym] = (snap, now)
                        if "." in sym:
                            prefix = sym.rsplit(".", 1)[0]
                            self._cache[prefix] = (snap, now)
                    if ticker:
                        self._cache[ticker] = (snap, now)
            else:
                logger.warning(f"调用内部行情服务失败 (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.warning(f"请求内部行情服务异常: {url} -> {e}")

        # 补全别名匹配
        for s in clean_symbols:
            if s not in result:
                cached = self._cache.get(s)
                if cached:
                    result[s] = cached[0]
                else:
                    for k, (cached_snap, _) in self._cache.items():
                        if k.upper() == s.upper() or k.startswith(f"{s.upper()}.") or s.upper().startswith(f"{k.upper()}."):
                            result[s] = cached_snap
                            break

        return result
