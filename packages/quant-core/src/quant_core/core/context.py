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
        bars = self.get_history(symbol, n)
        return [b.close for b in bars]
