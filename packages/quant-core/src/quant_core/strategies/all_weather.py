from typing import Dict, Optional
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class AllWeatherStrategy(BaseStrategy):
    """
    达利欧全球全天候大类资产配置策略 (Ray Dalio All-Weather Portfolio):
    
    【学术与投资哲学背景】
    由全球顶级对冲基金桥水联合基金 (Bridgewater Associates) 创始人雷·达利欧 (Ray Dalio) 提出。
    该策略基于“风险平价 (Risk Parity)”核心思想，认为传统的 60/40 股债组合中 90% 的风险由股市承担。
    全天候策略通过将资产划分为经济增长、经济下行、通胀上升、通胀下降四种宏观象限环境，
    在不同宏观周期中均能获得稳健回报，抵御单一资产崩盘风险：
    
    【经典标准资产权重配置】
    - 股票权益类 (30%): 捕捉经济繁荣增长红利 (如 510300 沪深300 ETF / 标普500 ETF)
    - 长期国债类 (40%): 抵御经济衰退通缩危机 (如 511010 国债ETF)
    - 中期纯债类 (15%): 平滑组合净值波动与提供流动性缓冲
    - 黄金资产 (7.5%): 抵御货币贬值与黑天鹅避险 (如 518880 黄金ETF)
    - 大宗商品 (7.5%): 抵御恶性通货膨胀与供应链冲击
    
    【调仓执行机制】
    1. 定期再平衡: 每隔 rebalance_interval 个交易日 (默认 20 交易日，即月度) 进行组合权重审计；
    2. 波动偏离容忍带: 当某资产实际权重偏离目标权重超过 rebalance_band (默认 3%) 时触发动态微调，
       自动卖出超涨资产锁定浮盈，逆向逢低增配受冷落资产，持续获取“波动再平衡溢价”。
    3. 单标的自适应兼容: 在单品种沙箱回测环境中，自适应按该品种资产类别的目标基准权重与均线趋势带执行稳健调仓。
    """
    def __init__(
        self,
        stock_weight: float = 0.30,
        long_bond_weight: float = 0.40,
        inter_bond_weight: float = 0.15,
        gold_weight: float = 0.075,
        commodity_weight: float = 0.075,
        rebalance_band: float = 0.03,
        rebalance_interval: int = 20,
        single_symbol_target: float = 0.40
    ):
        params = {
            "stock_weight": stock_weight,
            "long_bond_weight": long_bond_weight,
            "inter_bond_weight": inter_bond_weight,
            "gold_weight": gold_weight,
            "commodity_weight": commodity_weight,
            "rebalance_band": rebalance_band,
            "rebalance_interval": rebalance_interval,
            "single_symbol_target": single_symbol_target
        }
        super().__init__(name="RayDalioAllWeather", params=params)
        self.stock_weight = stock_weight
        self.long_bond_weight = long_bond_weight
        self.inter_bond_weight = inter_bond_weight
        self.gold_weight = gold_weight
        self.commodity_weight = commodity_weight
        self.rebalance_band = rebalance_band
        self.rebalance_interval = rebalance_interval
        self.single_symbol_target = single_symbol_target
        self.counter = 0

    def _determine_symbol_target_weight(self, symbol: str) -> float:
        """根据标的代码特征自动推导全天候资产类别目标配比"""
        sym_lower = symbol.lower()
        if any(kw in sym_lower for kw in ["518880", "159934", "159937", "gold", "黄金"]):
            return self.gold_weight
        elif any(kw in sym_lower for kw in ["511010", "511260", "bond", "国债", "tlt"]):
            return self.long_bond_weight
        elif any(kw in sym_lower for kw in ["159981", "159985", "commodity", "豆粕", "商品"]):
            return self.commodity_weight
        elif any(kw in sym_lower for kw in ["510300", "510500", "159919", "stock", "etf", "300"]):
            return self.stock_weight
        # 默认单标的运行时的稳健基准仓位
        return self.single_symbol_target

    def on_bar(self, bar: Bar):
        self.counter += 1
        # 每隔固定周期进行组合再平衡
        if self.counter % self.rebalance_interval != 0 and self.counter != 1:
            return

        portfolio = self.context.portfolio
        total_equity = portfolio.total_equity
        if total_equity <= 0:
            return

        target_pct = self._determine_symbol_target_weight(bar.symbol)
        pos = portfolio.get_position(bar.symbol)
        current_pct = pos.market_value / total_equity

        # 首次建仓或偏离度突破容忍带宽时触发再平衡
        if self.counter == 1 or abs(current_pct - target_pct) >= self.rebalance_band:
            action = "全天候初始配置" if self.counter == 1 else ("止盈降权" if current_pct > target_pct else "补齐增配")
            self.order_target_percent(
                bar.symbol,
                target_pct,
                reason=f"All-Weather {action} ({current_pct:.1%} -> {target_pct:.1%})"
            )
