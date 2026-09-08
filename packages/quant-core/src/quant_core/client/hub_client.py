"""Unified Data Hub Client for quant-core.

Enables calling 1000+ third-party financial datasets through our own central
stock-data-service hub. All calls are transparently cached and persisted as
Parquet files in the local lakehouse.
"""

from typing import Optional, Dict, Any, List
import httpx
import polars as pl
import pandas as pd
from quant_core.config import quant_config


class _ProviderProxy:
    """Dynamic proxy delegating attribute access to hub API invocations."""

    def __init__(self, client: "DataHubClient", provider: str):
        self._client = client
        self._provider = provider

    def __getattr__(self, api_name: str):
        def _callable(**kwargs):
            return self._client.invoke(self._provider, api_name, **kwargs)
        return _callable


class DataHubClient:
    """Client for the Universal Financial Data Hub."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or quant_config.DATA_SERVICE_HTTP).rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=30.0)

    @property
    def akshare(self) -> _ProviderProxy:
        return _ProviderProxy(self, "akshare")

    @property
    def baostock(self) -> _ProviderProxy:
        return _ProviderProxy(self, "baostock")

    def search_apis(
        self,
        q: Optional[str] = None,
        provider: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """全文检索中台已内置的所有第三方金融 API 资产目录"""
        params = {}
        if q: params["q"] = q
        if provider: params["provider"] = provider
        if category: params["category"] = category
        params["limit"] = limit

        resp = self._http.get("/v1/hub/catalog", params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    def get_api_doc(self, provider: str, api_name: str) -> Dict[str, Any]:
        """获取具体某个 API 的详细参数类型与中文说明文档"""
        resp = self._http.get(f"/v1/hub/catalog/{provider}/{api_name}")
        resp.raise_for_status()
        return resp.json()

    def print_catalog(
        self,
        q: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> None:
        """在终端快速格式化打印已接入的三方金融接口清单"""
        items = self.search_apis(q=q, category=category, limit=limit)
        print(f"\n{'='*80}")
        print(f"{'接口名 (API Name)':<36} | {'分类':<10} | {'说明 (Summary)'}")
        print(f"{'-'*80}")
        for it in items:
            print(f"{it['api_name']:<36} | {it.get('category', ''):<10} | {it.get('summary', '')}")
        print(f"{'='*80}\n共展示 {len(items)} 个接口。如需查看参数请调用 data_hub.get_api_doc('akshare', '<api_name>')\n")

    def get_valuation_analysis(
        self,
        symbol: str,
        window: str = "3y",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """获取标的全量多维估值与通道分析数据 (PE/PB/分位数/安全边际通道全量出齐)"""
        params = {"symbol": symbol, "window": window, "force_refresh": force_refresh}
        endpoints = [
            "/api/v1/stock/valuation/analysis",
            "api/v1/stock/valuation/analysis",
            "/v1/stock/valuation/analysis",
        ]
        last_err = None
        for ep in endpoints:
            try:
                resp = self._http.get(ep, params=params)
                if resp.status_code == 404 and ep != endpoints[-1]:
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        return {}



    def invoke(
        self,
        provider: str,
        api_name: str,
        force_refresh: bool = False,
        bypass_cache: bool = False,
        as_polars: bool = True,
        limit: int = 5000,
        **params,
    ) -> Any:
        """调用中台动态接口 (本地湖仓优先秒出，未命中自动穿透抓取并落库 Parquet；若 bypass_cache=True 则纯实时穿透不缓存)"""
        payload = {
            "params": params,
            "force_refresh": force_refresh,
            "bypass_cache": bypass_cache,
            "limit": limit,
        }


        # 智能适配不同 Nginx 反向代理前缀 (/v1/hub 或 /api/v1/hub)
        endpoints = [
            f"/v1/hub/invoke/{provider}/{api_name}",
            f"api/v1/hub/invoke/{provider}/{api_name}",
        ]

        
        last_err = None
        res_json = None
        for ep in endpoints:
            try:
                resp = self._http.post(ep, json=payload)
                if resp.status_code == 404 and ep != endpoints[-1]:
                    continue
                resp.raise_for_status()
                res_json = resp.json()
                break
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code == 404 and ep != endpoints[-1]:
                    continue
                raise
            except httpx.RequestError as e:
                last_err = e
                raise RuntimeError(
                    f"无法连接数据中台 ({self.base_url}): 请检查数据服务是否已启动或环境变量 QUANT_DATA_SERVICE_HTTP 是否配置正确。详情: {e}"
                ) from e

        if not res_json:
            if last_err:
                raise last_err
            return pl.DataFrame() if as_polars else pd.DataFrame()


        data_list = res_json.get("data", [])
        if not data_list:
            return pl.DataFrame() if as_polars else pd.DataFrame()

        if as_polars:
            return pl.DataFrame(data_list)
        return pd.DataFrame(data_list)


# 全局单例方便各模块开箱即用
data_hub = DataHubClient()
