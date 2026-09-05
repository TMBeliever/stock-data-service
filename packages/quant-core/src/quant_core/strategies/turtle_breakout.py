"""
策略名称: 海龟通道突破策略 (Turtle Channel Breakout)
策略类型: 趋势跟踪 / CTA 经典鼻祖
核心思想:
    1) 入场: 价格突破 N 日最高价 (Donchian Channel 上轨) 时做多;
            价格跌破 N 日最低价 (Donchian Channel 下轨) 时做空 (本策略为 A 股
            限制版本, 默认仅做多, 可选做空)。
    2) 加仓: 入场后, 若价格继续向有利方向突破 (N/2) 日高低点, 按 1N 风险
            比例加仓, 最多 N 次加仓 (海龟原版最多 4 仓)。
    3) 止损: 以最近一次入场价/加仓价 - 2N (N = ATR20) 作为硬性止损。
    4) 退出: 价格跌破 N/2 日最低价 (短线退出) 或 N 日最低价 (长线退出)。

参考:
    - Curtis Faith 《Way of the Turtle》 (2007)
    - Richard Dennis & William Eckhardt 1983 原始海龟实验
    - Donchian Channels (Donchian, 1960s)

适用标的: ETF (推荐 510300, 510500), 高流动性趋势品种
回测建议周期: 日线
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..base import BaseStrategy, Bar


class TurtleBreakoutStrategy(BaseStrategy):
    """海龟交易法则 (A 股做多版本)"""

    # ===== 可调参数 (回测时可在 params 中覆盖) =====
    DEFAULT_PARAMS: Dict[str, Any] = {
        "entry_period": 20,        # 入市通道周期 (海龟原版 S1=20)
        "exit_period": 10,         # 短线退出通道周期 (海龟原版 S2=10)
        "long_exit_period": 55,    # 长线退出通道周期 (海龟原版 S2=55)
        "atr_period": 20,          # ATR 周期
        "stop_atr_multiple": 2.0,  # 止损 = 入场价 - 2 * ATR
        "add_atr_multiple": 0.5,   # 加仓间隔 (单位: N 倍 ATR)
        "max_units": 4,            # 最大加仓次数 (海龟原版 4)
        "allow_short": False,      # A 股 ETF 默认仅做多
    }

    def __init__(self, params: Optional[Dict[str, Any]] = None) -> None:
        merged = dict(self.DEFAULT_PARAMS)
        if params:
            merged.update(params)
        super().__init__(merged)
        # ----- 内部状态 -----
        self.entry_price: float = 0.0          # 最近一次入场/加仓价
        self.stop_price: float = 0.0           # 当前止损价
        self.current_units: int = 0            # 当前持仓的加仓次数
        self.high_since_entry: float = 0.0     # 入场后最高价 (做加仓判断)
        self.last_add_price: float = 0.0       # 上次加仓触发价

    # ---------- 辅助函数: 计算 N 日通道 ----------
    @staticmethod
    def _donchian_high(bars: List[Bar], n: int) -> float:
        if len(bars) < n:
            return 0.0
        return max(b.high for b in bars[-n:])

    @staticmethod
    def _donchian_low(bars: List[Bar], n: int) -> float:
        if len(bars) < n:
            return float("inf")
        return min(b.low for b in bars[-n:])

    @staticmethod
    def _true_range(prev_close: float, bar: Bar) -> float:
        return max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )

    def _atr(self, bars: List[Bar], period: int) -> float:
        if len(bars) < period + 1:
            return 0.0
        trs: List[float] = []
        for i in range(-period, 0):
            prev_close = bars[i - 1].close
            trs.append(self._true_range(prev_close, bars[i]))
        return sum(trs) / period if trs else 0.0

    # ---------- 主回调: 每根 K 线调用一次 ----------
    def on_bar(self, bar: Bar, history: Optional[List[Bar]] = None) -> None:
        # 第一次调用时把历史数据预热进来 (沙箱通常会把首批 K 线一次性推过来)
        if history is not None and len(self.bars) == 0:
            for hb in history:
                self.bars.append(hb)

        self.bars.append(bar)

        # 至少需要 60 根 K 线才能稳定计算 55 日通道
        warmup = max(self.params["entry_period"], self.params["long_exit_period"]) + 5
        if len(self.bars) < warmup:
            return

        p = self.params
        bars = self.bars

        entry_high = self._donchian_high(bars[:-1], p["entry_period"])
        exit_low = self._donchian_high(bars[:-1], p["exit_period"])  # 注: short exit 高点
        short_exit = self._donchian_low(bars[:-1], p["exit_period"])
        long_exit = self._donchian_low(bars[:-1], p["long_exit_period"])
        atr = self._atr(bars, p["atr_period"])

        if atr <= 0 or entry_high <= 0:
            return

        price = bar.close

        # ============= 1) 已持仓: 止损 / 加仓 / 退出 =============
        if self.position > 0:
            self.high_since_entry = max(self.high_since_entry, bar.high)

            # --- 加仓逻辑: 价格创新高, 且与上次加仓间隔 >= 0.5N ---
            if self.current_units < p["max_units"]:
                if self.high_since_entry >= self.last_add_price + p["add_atr_multiple"] * atr:
                    self.buy(bar, reason="turtle_add_unit")
                    self.current_units += 1
                    self.last_add_price = self.high_since_entry
                    self.stop_price = self.last_add_price - p["stop_atr_multiple"] * atr

            # --- 硬性止损 ---
            if bar.low <= self.stop_price:
                self.close_position(bar, reason="turtle_stop_loss")
                self._reset_state()
                return

            # --- 短线退出 (10 日下轨) ---
            if bar.close < short_exit:
                self.close_position(bar, reason="turtle_short_exit")
                self._reset_state()
                return

            # --- 长线退出 (55 日下轨) ---
            if bar.close < long_exit:
                self.close_position(bar, reason="turtle_long_exit")
                self._reset_state()
                return

        # ============= 2) 持空仓 (默认关闭) =============
        if self.position < 0 and p["allow_short"]:
            # 简化处理: 价格突破 10 日高点就平空
            if bar.close > exit_low:
                self.close_position(bar, reason="turtle_short_cover")
                self._reset_state()
                return

        # ============= 3) 无仓 / 信号触发 =============
        if self.position == 0:
            # 多头入场: 突破 20 日高点
            if bar.close > entry_high:
                self.buy(bar, reason="turtle_entry_long")
                self.entry_price = bar.close
                self.last_add_price = bar.close
                self.high_since_entry = bar.high
                self.stop_price = bar.close - p["stop_atr_multiple"] * atr
                self.current_units = 1
                return

            # 空头入场 (可选)
            if p["allow_short"] and bar.close < self._donchian_low(bars[:-1], p["entry_period"]):
                self.sell(bar, reason="turtle_entry_short")
                self.entry_price = bar.close
                self.last_add_price = bar.close
                self.stop_price = bar.close + p["stop_atr_multiple"] * atr
                self.current_units = 1
                return

    def _reset_state(self) -> None:
        self.entry_price = 0.0
        self.stop_price = 0.0
        self.current_units = 0
        self.high_since_entry = 0.0
        self.last_add_price = 0.0
