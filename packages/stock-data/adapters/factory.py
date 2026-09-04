from typing import Optional
from core.models import SymbolInfo, Market
from adapters.base import BaseDataSource
from adapters.cn_akshare import AkShareAdapter
from adapters.global_yfinance import YFinanceAdapter

class AdapterFactory:
    def __init__(self):
        self._cn_adapter = AkShareAdapter()
        self._yf_adapter = YFinanceAdapter()

    def get_adapter(self, market: Market) -> BaseDataSource:
        if market in [Market.SH, Market.SZ, Market.BJ]:
            return self._cn_adapter
        elif market in [Market.US, Market.HK]:
            return self._yf_adapter
        else:
            return self._yf_adapter

adapter_factory = AdapterFactory()
