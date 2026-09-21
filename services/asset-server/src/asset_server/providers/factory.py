from asset_server.config import settings
from asset_server.providers.base import BaseMarketDataProvider
from asset_server.providers.internal import InternalStockDataProvider
from asset_server.providers.external import ExternalMarketDataProvider
from asset_server.providers.mock import MockMarketDataProvider

_global_provider: BaseMarketDataProvider | None = None


def get_market_data_provider() -> BaseMarketDataProvider:
    """
    按全局配置获取行情数据提供商单例 (Factory Pattern)
    - "internal": 内部 stock-data 服务 (当前默认)
    - "external": 外部第三方服务
    - "mock": Mock 静态行情 (测试使用)
    """
    global _global_provider
    if _global_provider is not None:
        return _global_provider

    provider_type = settings.MARKET_DATA_PROVIDER.strip().lower()

    if provider_type == "internal":
        _global_provider = InternalStockDataProvider(
            base_url=settings.STOCK_DATA_URL,
            timeout=settings.REQUEST_TIMEOUT,
            cache_ttl=settings.QUOTE_CACHE_TTL,
        )
    elif provider_type == "external":
        _global_provider = ExternalMarketDataProvider(
            base_url=settings.EXTERNAL_MARKET_URL,
            api_key=settings.EXTERNAL_MARKET_KEY,
            timeout=settings.REQUEST_TIMEOUT,
        )
    elif provider_type == "mock":
        _global_provider = MockMarketDataProvider()
    else:
        # 默认回退为内部服务
        _global_provider = InternalStockDataProvider(
            base_url=settings.STOCK_DATA_URL,
            timeout=settings.REQUEST_TIMEOUT,
            cache_ttl=settings.QUOTE_CACHE_TTL,
        )

    return _global_provider


def set_market_data_provider(provider: BaseMarketDataProvider):
    """供单元测试或动态替换注入使用"""
    global _global_provider
    _global_provider = provider
