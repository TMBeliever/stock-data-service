from abc import ABC, abstractmethod
from typing import List, Optional
import polars as pl
from core.models import SymbolInfo, KlinePeriod

class BaseDataSource(ABC):
    """
    通用数据源抽象基类。
    所有具体市场的适配器（A股、美股、港股、加密货币等）都必须继承该类，
    并保证输出标准化的 Polars DataFrame。
    """
    
    # 标准 Parquet 输出 Schema:
    # timestamp: INT64 (UTC 毫秒)
    # open: FLOAT32
    # high: FLOAT32
    # low: FLOAT32
    # close: FLOAT32
    # volume: FLOAT64
    # amount: FLOAT64
    # factor: FLOAT32 (除权除息因子, 默认 1.0)
    # nav: FLOAT32 (仅 ETF 单位净值, 否则 null)
    
    @abstractmethod
    def fetch_daily(self, info: SymbolInfo, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        """抓取日K线真实数据"""
        pass

    @abstractmethod
    def fetch_minute(self, info: SymbolInfo, period: KlinePeriod, start_date: str, end_date: str) -> Optional[pl.DataFrame]:
        """抓取分钟K线真实数据 (如 1m, 5m)"""
        pass

    @abstractmethod
    def fetch_snapshot(self, market: str) -> Optional[pl.DataFrame]:
        """抓取当日全市场截面快照 (供全市场选股)"""
        pass

    @abstractmethod
    def fetch_calendar(self, market: str, year: int) -> List[dict]:
        """抓取市场交易日历"""
        pass

    @abstractmethod
    def fetch_symbols(self, market: str) -> List[SymbolInfo]:
        """抓取市场标的代码元数据列表"""
        pass
