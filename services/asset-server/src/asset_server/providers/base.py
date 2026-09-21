from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from pydantic import BaseModel


class QuoteSnapshot(BaseModel):
    """标准盘口/估值快照数据模型"""
    symbol: str
    price: float                  # 最新现价
    prev_close: float = 0.0       # 昨收价
    change_pct: float = 0.0       # 涨跌幅 (%)
    source: str = "internal"      # 数据源说明


class BaseMarketDataProvider(ABC):
    """
    行情数据提供商抽象基类 (Market Data Provider Interface)
    业务层仅依赖该抽象，实现真正的依赖倒置，支持热插拔切换外部数据源。
    """

    @abstractmethod
    async def get_batch_quotes(self, symbols: List[str]) -> Dict[str, QuoteSnapshot]:
        """批量获取多个标的的盘口快照"""
        pass

    async def get_latest_price(self, symbol: str) -> Optional[float]:
        """获取单个标的最新价"""
        res = await self.get_batch_quotes([symbol])
        snap = res.get(symbol)
        return snap.price if snap else None
