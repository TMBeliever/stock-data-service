import logging
from typing import List, Dict, Optional
import httpx
from asset_server.providers.base import BaseMarketDataProvider, QuoteSnapshot

logger = logging.getLogger("asset_server.providers.external")


class ExternalMarketDataProvider(BaseMarketDataProvider):
    """
    通用外部第三方行情适配器骨架
    支持通过配置外部 API URL 和 Key 随时接入外部开放数据商 (如券商 Open API、TuShare、商业数据总线等)。
    """

    def __init__(self, base_url: Optional[str], api_key: Optional[str] = None, timeout: float = 5.0):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        if not self.base_url or not symbols:
            return {}

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        result: Dict[str, QuoteSnapshot] = {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/quotes/batch",
                    json={"symbols": symbols},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("quotes", []):
                        sym = item.get("symbol")
                        result[sym] = QuoteSnapshot(
                            symbol=sym,
                            price=float(item.get("price", 0.0)),
                            prev_close=float(item.get("prev_close", 0.0)),
                            change_pct=float(item.get("change_pct", 0.0)),
                            source="external",
                        )
        except Exception as e:
            logger.error(f"外部行情数据源请求失败: {e}")

        return result
