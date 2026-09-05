from typing import Any, Dict, List, Optional
from quant_core.core.models import Bar, Snapshot, Portfolio

class StrategyContext:
    """策略运行上下文与状态存储"""
    def __init__(self, portfolio: Portfolio, params: Optional[Dict[str, Any]] = None):
        self.portfolio = portfolio
        self.params: Dict[str, Any] = params or {}
        
        # 缓存当前切片数据
        self.current_bars: Dict[str, Bar] = {}
        self.current_snapshots: Dict[str, Snapshot] = {}
        
        # 历史切片序列 (用于技术指标滚动计算)
        self.bar_history: Dict[str, List[Bar]] = {}
        
        # 共享用户自定义变量池
        self.user_data: Dict[str, Any] = {}

    def record_bar(self, bar: Bar):
        bar.bind_context(self)
        self.current_bars[bar.symbol] = bar
        if bar.symbol not in self.bar_history:
            self.bar_history[bar.symbol] = []
        self.bar_history[bar.symbol].append(bar)

    def get_history(self, symbol: str, n: int = 50) -> List[Bar]:
        """获取最近 N 根 Bar"""
        bars = self.bar_history.get(symbol, [])
        return bars[-n:] if n > 0 else bars

    def get_closes(self, symbol: str, n: int = 50) -> List[float]:
        """获取最近 N 根收盘价列表"""
        return [b.close for b in self.get_history(symbol, n)]

    def get_opens(self, symbol: str, n: int = 50) -> List[float]:
        """获取最近 N 根开盘价列表"""
        return [b.open for b in self.get_history(symbol, n)]

    def get_highs(self, symbol: str, n: int = 50) -> List[float]:
        """获取最近 N 根最高价列表"""
        return [b.high for b in self.get_history(symbol, n)]

    def get_lows(self, symbol: str, n: int = 50) -> List[float]:
        """获取最近 N 根最低价列表"""
        return [b.low for b in self.get_history(symbol, n)]

    def get_volumes(self, symbol: str, n: int = 50) -> List[float]:
        """获取最近 N 根成交量列表"""
        return [b.volume for b in self.get_history(symbol, n)]

