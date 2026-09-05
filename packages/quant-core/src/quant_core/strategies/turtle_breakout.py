"""
策略名称: 海龟通道突破策略 (Turtle Channel Breakout)
策略类型: 趋势跟踪 / CTA 经典鼻祖
核心思想:
    1) 入场: 价格突破 N 日最高价 (Donchian Channel 上轨) 时做多;
            价格跌破 N 日最低价 (Donchian Channel 下轨) 时做空 (A 股 ETF 默认仅做多)。
    2) 加仓: 入场后, 若价格继续向有利方向突破, 按 0.5N 间隔加仓, 最多 4 仓。
    3) 止损: 以最近一次入场价/加仓价 - 2N (N = ATR20) 作为硬性止损。
    4) 退出: 价格跌破 10 日最低价 (短线退出) 或 55 日最低价 (长线退出)。

适用标的: ETF (如 510300, 510500), 高流动性趋势品种
回测建议周期: 日线
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from quant_core import BaseStrategy, Bar


class TurtleBreakoutStrategy(BaseStrategy):
    """海龟交易法则 (A 股 ETF 做多版本)"""

    # ===== 默认可调参数 =====
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

    def __init__(self, params: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        merged = dict(self.DEFAULT_PARAMS)
        if params and isinstance(params, dict):
            merged.update(params)
        merged.update(kwargs)
        super().__init__(name="TurtleBreakout", params=merged)

        # ----- 内部状态跟踪 -----
        self.entry_price: float = 0.0          # 最近一次入场/加仓价
        self.stop_price: float = 0.0           # 当前止损价
        self.current_units: int = 0            # 当前持仓加仓次数
        self.high_since_entry: float = 0.0     # 入场后最高价 (用于加仓判断)
        self.last_add_price: float = 0.0       # 上次加仓触发价

    # ---------- 主回调: 每根 K 线切片调用一次 ----------
    def on_bar(self, bar: Bar) -> None:
        p = self.params
        warmup = max(p.get("entry_period", 20), p.get("long_exit_period", 55)) + 5

        # 预热期未满，不进行信号判断
        if len(self.bars) < warmup:
            return

        # 1. 利用 QuantCore 2.0 内置指标快速计算唐奇安通道与 ATR
        entry_high = self.highest(p["entry_period"], include_current=False)
        short_exit = self.lowest(p["exit_period"], include_current=False)
        long_exit = self.lowest(p["long_exit_period"], include_current=False)
        atr_val = self.atr(p["atr_period"])

        if atr_val <= 0 or entry_high <= 0:
            return

        # ============= 1) 已有多头持仓: 止损 / 加仓 / 退出 =============
        if self.position > 0:
            self.high_since_entry = max(self.high_since_entry, bar.high)

            # --- 加仓逻辑: 价格继续上涨突破，且间隔 >= 0.5N ---
            if self.current_units < p["max_units"]:
                if self.high_since_entry >= self.last_add_price + p["add_atr_multiple"] * atr_val:
                    self.buy(100, reason="turtle_add_unit")
                    self.current_units += 1
                    self.last_add_price = self.high_since_entry
                    self.stop_price = self.last_add_price - p["stop_atr_multiple"] * atr_val

            # --- 硬性止损: 跌破入场价/加仓价下沿 2N ---
            if bar.low <= self.stop_price:
                self.close_position(reason="turtle_stop_loss")
                self._reset_state()
                return

            # --- 短线退出: 跌破 10 日唐奇安通道下轨 ---
            if bar.close < short_exit:
                self.close_position(reason="turtle_short_exit")
                self._reset_state()
                return

            # --- 长线退出: 跌破 55 日唐奇安通道下轨 ---
            if bar.close < long_exit:
                self.close_position(reason="turtle_long_exit")
                self._reset_state()
                return

        # ============= 2) 无持仓: 突破开仓信号 =============
        elif self.position == 0:
            # 多头入场: 突破 20 日唐奇安高点
            if bar.close > entry_high:
                self.buy(100, reason="turtle_entry_long")
                self.entry_price = bar.close
                self.last_add_price = bar.close
                self.high_since_entry = bar.high
                self.stop_price = bar.close - p["stop_atr_multiple"] * atr_val
                self.current_units = 1

    def _reset_state(self) -> None:
        """平仓后重置策略内部状态变量"""
        self.entry_price = 0.0
        self.stop_price = 0.0
        self.current_units = 0
        self.high_since_entry = 0.0
        self.last_add_price = 0.0
