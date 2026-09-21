from typing import List, Dict
from asset_server.providers.base import BaseMarketDataProvider, QuoteSnapshot


class MockMarketDataProvider(BaseMarketDataProvider):
    """
    Mock 行情提供商
    用于单元测试与离线隔离测试，提供确定性的标的行情价格。
    """

    DEFAULT_PRESET_PRICES = {
        "510300.SH.ETF": {"price": 4.582, "prev_close": 4.532, "change_pct": 1.10},
        "510880.SH.ETF": {"price": 3.339, "prev_close": 3.347, "change_pct": -0.24},
        "511010.SH.ETF": {"price": 140.67, "prev_close": 140.63, "change_pct": 0.03},
        "518880.SH.ETF": {"price": 9.009, "prev_close": 8.856, "change_pct": 1.73},
        "600519.SH": {"price": 1560.00, "prev_close": 1540.00, "change_pct": 1.30},
        "0700.HK": {"price": 380.00, "prev_close": 375.00, "change_pct": 1.33},
        "AAPL.US": {"price": 225.00, "prev_close": 220.00, "change_pct": 2.27},
        "BTCUSDT": {"price": 64500.0, "prev_close": 63000.0, "change_pct": 2.38},
    }

    def __init__(self, custom_prices: Dict[str, Dict[str, float]] | None = None):
        self.prices = dict(self.DEFAULT_PRESET_PRICES)
        if custom_prices:
            self.prices.update(custom_prices)

    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        result: Dict[str, QuoteSnapshot] = {}
        for sym in symbols:
            info = self.prices.get(sym)
            if info:
                result[sym] = QuoteSnapshot(
                    symbol=sym,
                    price=float(info["price"]),
                    prev_close=float(info.get("prev_close", info["price"])),
                    change_pct=float(info.get("change_pct", 0.0)),
                    source="mock",
                )
            else:
                # 默认保底兜底价格
                result[sym] = QuoteSnapshot(
                    symbol=sym,
                    price=10.0,
                    prev_close=10.0,
                    change_pct=0.0,
                    source="mock-fallback",
                )
        return result
