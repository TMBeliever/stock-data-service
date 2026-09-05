import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

export interface UserStrategyItem {
  id: number
  user_id: number
  name: string
  description?: string | null
  code: string
  symbol: string
  created_at: string
  updated_at: string
}

export interface UserBacktestItem {
  id: number
  user_id: number
  strategy_id?: number | null
  strategy_name: string
  symbol: string
  start_date: string
  end_date?: string | null
  initial_cash: number
  final_equity: number
  total_return: number
  annualized_return: number
  max_drawdown: number
  sharpe_ratio: number
  win_rate: number
  total_trades: number
  created_at: string
}

export interface BacktestSummary {
  initial_cash: number
  final_equity: number
  total_return: number
  annualized_return: number
  max_drawdown: number
  sharpe_ratio: number
  sortino_ratio: number
  calmar_ratio: number
  win_rate: number
  profit_factor: number
  total_trades: number
}

export interface DailyRecord {
  date: string
  timestamp: number
  cash: number
  market_value: number
  total_equity: number
}

export interface BenchmarkRecord {
  date: string
  timestamp: number
  close: number
  return_pct: number
}

export interface TradeRecord {
  trade_id: string
  symbol: string
  side: string
  price: number
  quantity: number
  commission: number
  timestamp: number
  datetime_str: string
}

export interface BacktestResultData {
  summary: BacktestSummary
  daily_records: DailyRecord[]
  benchmark_records: BenchmarkRecord[]
  trades: TradeRecord[]
}

export interface AiChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  codeBlock?: string
}

// 4 套标准经典策略（直接内置在用户的初始策略库中）
export const DEFAULT_INITIAL_STRATEGIES: UserStrategyItem[] = [
  {
    id: -1,
    user_id: 0,
    name: '经典双均线趋势策略 (Dual MA)',
    description: '短期均线金叉做多，死叉平仓避险，经典趋势跟踪范式',
    symbol: '510300.SH.ETF',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class DualMAStrategy(BaseStrategy):
    """
    经典双均线交叉策略 (Dual Moving Average Cross - QuantCore 2.0 极简范式)：
    - MA(5) 上穿 MA(20) 金叉：以 80% 目标仓位买入建仓；
    - MA(5) 下穿 MA(20) 死叉：全部平仓落袋为安。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        # 1. 均线金叉开仓 (Golden Cross)
        if self.cross_over(self.fast, self.slow) and not self.position:
            self.order_target_percent(0.8, reason="金叉开仓")

        # 2. 均线死叉平仓 (Death Cross)
        elif self.cross_under(self.fast, self.slow) and self.position:
            self.close_position(reason="死叉平仓")
`
  },
  {
    id: -2,
    user_id: 0,
    name: '动态估值分位数定投 (Smart DCA)',
    description: '按历史价格分位数动态调权，极度低估时加倍定投，估值过高主动止盈',
    symbol: '510880.SH.ETF',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class SmartDividendDCAStrategy(BaseStrategy):
    """
    智能估值分位数定投策略 (QuantCore 2.0 极简范式)：
    - 利用 bar.percentile(250) 计算价格历史分位数；
    - 分位数 <= 20% (bar.is_undervalued): 加码 2.0 倍基准金额买入；
    - 分位数 >= 80% (bar.is_overvalued): 减仓 20% 主动止盈防回撤。
    """
    def __init__(self, base_amount: float = 2000.0, window: int = 250):
        super().__init__(name="SmartDCA", params={"base_amount": base_amount, "window": window})
        self.base_amount = base_amount
        self.window = window
        self.bar_counter = 0

    def on_bar(self, bar: Bar):
        self.bar_counter += 1
        # 每 5 个交易日评估一次定投
        if self.bar_counter % 5 != 0:
            return

        pct = bar.percentile(self.window)

        # 1. 极度低估: 加倍定投抄底
        if bar.is_undervalued and self.cash >= self.base_amount * 2:
            qty = int((self.base_amount * 2.0) / bar.close // 100) * 100
            if qty > 0:
                self.buy(qty, reason=f"低估加倍定投(分位{pct:.1%})")

        # 2. 合理估值: 正常定投
        elif pct <= 0.50 and self.cash >= self.base_amount:
            qty = int(self.base_amount / bar.close // 100) * 100
            if qty > 0:
                self.buy(qty, reason=f"合理估值定投(分位{pct:.1%})")

        # 3. 严重高估泡沫: 主动止盈 20%
        elif bar.is_overvalued and self.position.available_quantity >= 500:
            sell_qty = min(self.position.available_quantity, int(self.position.available_quantity * 0.2 // 100) * 100)
            if sell_qty > 0:
                self.sell(sell_qty, reason=f"高估主动止盈(分位{pct:.1%})")
`
  },
  {
    id: -3,
    user_id: 0,
    name: '动态网格波动套利 (Grid Trading)',
    description: '在震荡市中利用均价带上下挂单，高抛低吸捕捉微观波动利润',
    symbol: '510500.SH.ETF',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class GridTradingStrategy(BaseStrategy):
    """
    动态自适应网格策略 (QuantCore 2.0 极简范式)：
    - 初始建立 40% 底仓；
    - 价格下跌超 2.5% 触及网格下轨低吸加仓；
    - 价格上涨超 2.5% 触及网格上轨高抛止盈。
    """
    def __init__(self, step_pct: float = 0.025, base_shares: int = 1000):
        super().__init__(name="GridTrading", params={"step": step_pct, "shares": base_shares})
        self.step_pct = step_pct
        self.base_shares = base_shares
        self.last_trade_price = 0.0

    def on_bar(self, bar: Bar):
        # 1. 初始建底仓
        if self.last_trade_price == 0.0:
            self.order_target_percent(0.4, reason="网格初始化底仓")
            self.last_trade_price = bar.close
            return

        # 2. 下跌触及网格下轨加仓
        if bar.close <= self.last_trade_price * (1.0 - self.step_pct):
            if self.cash >= bar.close * self.base_shares:
                self.buy(self.base_shares, reason="网格低吸加仓")
                self.last_trade_price = bar.close

        # 3. 上涨触及网格上轨高抛止盈
        elif bar.close >= self.last_trade_price * (1.0 + self.step_pct):
            if self.position.available_quantity >= self.base_shares:
                self.sell(self.base_shares, reason="网格高抛止盈")
                self.last_trade_price = bar.close
`
  },
  {
    id: -4,
    user_id: 0,
    name: '极端急跌重仓抄底 (Extreme Dip)',
    description: '大盘或核心资产年内极端暴跌 15% 以上时果断重仓介入，反弹至均线平仓',
    symbol: '510300.SH.ETF',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class ExtremeDipHeavyStrategy(BaseStrategy):
    """
    极端急跌重仓抄底策略 (QuantCore 2.0 极简范式)：
    - 监控 120 日内最高价的高位回撤幅度；
    - 当自高点回撤超过 15% 且当前无持仓时，果断调仓至 90% 仓位重仓抄底；
    - 当价格重回 60 日均线之上时，分批结利降低风险暴露。
    """
    def __init__(self, dip_threshold: float = 0.15, ma_period: int = 60):
        super().__init__(name="ExtremeDip", params={"dip": dip_threshold, "ma": ma_period})
        self.dip_threshold = dip_threshold
        self.ma_period = ma_period

    def on_bar(self, bar: Bar):
        peak_high = bar.highest(120)
        if peak_high <= 0:
            return

        drawdown_from_peak = (peak_high - bar.close) / peak_high

        # 1. 触发极端超跌：一次性 90% 仓位重仓建仓
        if drawdown_from_peak >= self.dip_threshold and not self.position:
            self.order_target_percent(0.90, reason=f"暴跌{drawdown_from_peak:.1%}极端抄底")

        # 2. 价格回归均线之上：减仓至 20% 止盈
        elif bar.close > bar.sma(self.ma_period) and self.position:
            self.order_target_percent(0.20, reason="价格回归均线减仓止盈")
`
  },
  {
    id: -5,
    user_id: 0,
    name: '达利欧全球全天候大类资产配置策略 (Ray Dalio All-Weather)',
    description: '全球经典风险平价多资产配置，按30%股票、40%长债、15%中债、7.5%黄金、7.5%商品定期动态再平衡，穿越宏观经济四象限',
    symbol: '510300.SH.ETF',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class AllWeatherStrategy(BaseStrategy):
    """
    达利欧全球全天候大类资产配置策略 (Ray Dalio All-Weather Portfolio - QuantCore 2.0)：
    - 股票权益 (30%): 捕捉经济繁荣增长红利 (如 510300 沪深300 / 标普500)
    - 长期债券 (40%): 抵御经济衰退通缩危机 (如 511010 国债ETF)
    - 中期纯债 (15%): 平滑组合净值波动与流动性
    - 黄金资产 (7.5%): 抵御货币超发与通胀风险 (如 518880 黄金ETF)
    - 大宗商品 (7.5%): 抵御恶性通货膨胀与供应链冲击
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
        sym_lower = symbol.lower()
        if any(kw in sym_lower for kw in ["518880", "159934", "gold", "黄金"]):
            return self.gold_weight
        elif any(kw in sym_lower for kw in ["511010", "511260", "bond", "国债"]):
            return self.long_bond_weight
        elif any(kw in sym_lower for kw in ["159981", "commodity", "豆粕", "商品"]):
            return self.commodity_weight
        elif any(kw in sym_lower for kw in ["510300", "510500", "stock", "etf", "300"]):
            return self.stock_weight
        return self.single_symbol_target

    def on_bar(self, bar: Bar):
        self.counter += 1
        # 每隔固定周期进行组合再平衡 (或首根 K 线初始建仓)
        if self.counter % self.rebalance_interval != 0 and self.counter != 1:
            return

        total_equity = self.equity
        if total_equity <= 0:
            return

        target_pct = self._determine_symbol_target_weight(bar.symbol)
        pos = self.positions.get(bar.symbol)
        current_mv = pos.market_value if pos else 0.0
        current_pct = current_mv / total_equity

        # 首次建仓或偏离度突破容忍带宽时触发再平衡
        if self.counter == 1 or abs(current_pct - target_pct) >= self.rebalance_band:
            action = "全天候初始建仓" if self.counter == 1 else ("止盈降权" if current_pct > target_pct else "低位补齐增配")
            self.order_target_percent(
                bar.symbol,
                target_pct,
                reason=f"All-Weather {action} ({current_pct:.1%} -> {target_pct:.1%})"
            )
`
  }
]

const STORAGE_CODE_KEY = 'quantscope_custom_strategy_code'

export const useStrategyStore = defineStore('strategy', () => {
  // 1. 用户专属云端策略库状态（默认为预置的 5 套初始策略）
  const userStrategies = ref<UserStrategyItem[]>([...DEFAULT_INITIAL_STRATEGIES])
  const activeStrategyId = ref<number | null>(DEFAULT_INITIAL_STRATEGIES[0].id)
  const activeStrategyName = ref<string>(DEFAULT_INITIAL_STRATEGIES[0].name)
  const userStrategiesLoading = ref(false)
  const isSavingStrategy = ref(false)

  // 2. 代码编辑器当前内容
  const savedCode = localStorage.getItem(STORAGE_CODE_KEY)
  const code = ref(savedCode || DEFAULT_INITIAL_STRATEGIES[0].code)

  // 3. 回测参数状态
  const symbol = ref(DEFAULT_INITIAL_STRATEGIES[0].symbol)
  const startDate = ref('2023-01-01')
  const endDate = ref('')
  const initialCash = ref(100000)

  // 4. 回测运行状态与结果
  const isBacktesting = ref(false)
  const backtestError = ref<string | null>(null)
  const backtestResult = ref<BacktestResultData | null>(null)
  const userBacktests = ref<UserBacktestItem[]>([])
  const isSavingBacktest = ref(false)
  const userBacktestsLoading = ref(false)

  // 5. AI Copilot 对话状态
  const aiModel = ref<'minimax/minimax-m3:free' | 'gemini-flash-lite-latest' | 'claude'>('minimax/minimax-m3:free')
  const isAiStreaming = ref(false)
  const aiMessages = ref<AiChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '👋 你好！我是你的 **QuantScope AI 策略研究助理**。\n\n我可以帮你：\n- 💡 **自然语言写策略**：描述你的想法，如「帮我写一个沪深300网格策略」\n- 🔍 **策略代码纠错**：检查逻辑死循环、越界或未考虑滑点\n- ⚡ **指标升级**：为策略增加移动止盈、止损或波动率过滤\n\n请在下方输入你的量化灵感，或直接点击预设指令开始！',
      timestamp: Date.now(),
    },
  ])

  // 辅助函数：从文本中提取 python 代码块
  function extractPythonCode(text: string): string | null {
    const match = text.match(/```(?:python)?\s*([\s\S]*?)```/i)
    return match ? match[1].trim() : null
  }

  // 更新代码并暂存
  function updateCode(newCode: string) {
    code.value = newCode
    localStorage.setItem(STORAGE_CODE_KEY, newCode)
  }

  // 将 AI 生成的代码直接覆盖至代码编辑器
  function applyCodeToEditor(targetCode: string) {
    updateCode(targetCode)
  }

  // 创建空白新策略
  function createBlankStrategy() {
    activeStrategyId.value = null
    activeStrategyName.value = '新自定策略 (未保存)'
    const blankCode = `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class MyCustomStrategy(BaseStrategy):
    """
    我的自定量化策略
    """
    def __init__(self):
        super().__init__(name="MyStrategy")

    def on_bar(self, bar: Bar):
        # 在此处编写您的交易撮合逻辑
        closes = self.context.get_closes(bar.symbol, n=20)
        if len(closes) < 20:
            return
        
        # 示例：以 80% 目标仓位买入
        pos = self.get_position(bar.symbol)
        if pos.quantity == 0:
            self.order_target_percent(bar.symbol, 0.8, reason="开仓信号")
`
    updateCode(blankCode)
  }

  // 载入云端策略到编辑器
  function loadUserStrategy(strat: UserStrategyItem) {
    activeStrategyId.value = strat.id
    activeStrategyName.value = strat.name
    code.value = strat.code
    symbol.value = strat.symbol || '510300.SH.ETF'
    localStorage.setItem(STORAGE_CODE_KEY, strat.code)
  }

  // 拉取用户的策略列表（若登录则向后端请求，后端无数据时会自动初始化）
  async function fetchUserStrategies() {
    const authStore = useAuthStore()
    if (!authStore.token) {
      userStrategies.value = [...DEFAULT_INITIAL_STRATEGIES]
      return
    }
    userStrategiesLoading.value = true
    try {
      const res = await fetch('/api/v1/user/strategies', {
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
      if (res.ok) {
        const data: UserStrategyItem[] = await res.json()
        if (data && data.length > 0) {
          userStrategies.value = data
          // 如果当前策略是本地临时策略，尝试对齐云端策略
          if (activeStrategyId.value === null || activeStrategyId.value < 0) {
            const matched = data.find((s) => s.name === activeStrategyName.value) || data[0]
            if (matched) {
              activeStrategyId.value = matched.id
              activeStrategyName.value = matched.name
            }
          }
        }
      }
    } finally {
      userStrategiesLoading.value = false
    }
  }

  // 保存策略：支持【修改原策略 (update)】与【另存为全新策略 (create)】
  async function saveStrategy(
    name: string,
    description?: string,
    mode: 'create' | 'update' = 'create'
  ): Promise<{ success: boolean; message: string }> {
    const authStore = useAuthStore()
    if (!authStore.isLoggedIn) {
      authStore.openLogin()
      return { success: false, message: '请先登录' }
    }

    isSavingStrategy.value = true
    try {
      let res: Response
      // 满足修改条件：显式选择 update 且当前已载入合法的云端策略 (id > 0)
      if (mode === 'update' && activeStrategyId.value && activeStrategyId.value > 0) {
        res = await fetch(`/api/v1/user/strategies/${activeStrategyId.value}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${authStore.token}`,
          },
          body: JSON.stringify({
            name: name.trim(),
            description: description || null,
            code: code.value,
            symbol: symbol.value,
          }),
        })
      } else {
        // 新增独立策略 (新建或另存为)
        res = await fetch('/api/v1/user/strategies', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${authStore.token}`,
          },
          body: JSON.stringify({
            name: name.trim(),
            description: description || null,
            code: code.value,
            symbol: symbol.value,
          }),
        })
      }

      const data = await res.json()
      if (!res.ok) {
        return { success: false, message: data.detail || '保存失败' }
      }

      activeStrategyId.value = data.id
      activeStrategyName.value = data.name
      await fetchUserStrategies()
      const actionText = mode === 'update' ? '已更新原策略' : '已保存为新策略'
      return { success: true, message: `🎉 ${actionText}「${data.name}」并同步至云端！` }
    } catch (err: any) {
      return { success: false, message: err.message || '网络连接异常' }
    } finally {
      isSavingStrategy.value = false
    }
  }

  // 删除云端策略
  async function deleteUserStrategy(id: number): Promise<boolean> {
    const authStore = useAuthStore()
    // 如果是前端预置策略（id < 0），直接从前端列表中过滤
    if (id < 0) {
      userStrategies.value = userStrategies.value.filter((s) => s.id !== id)
      if (activeStrategyId.value === id) {
        createBlankStrategy()
      }
      return true
    }

    if (!authStore.token) return false
    try {
      const res = await fetch(`/api/v1/user/strategies/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
      if (res.ok) {
        if (activeStrategyId.value === id) {
          createBlankStrategy()
        }
        await fetchUserStrategies()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  // 发起回测请求
  async function runBacktest() {
    if (isBacktesting.value) return
    isBacktesting.value = true
    backtestError.value = null

    try {
      const resp = await fetch('/api/v1/backtest/run-custom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol.value,
          code: code.value,
          start: startDate.value,
          end: endDate.value || null,
          initial_cash: initialCash.value,
        }),
      })

      const data = await resp.json()

      if (!resp.ok) {
        throw new Error(data.detail || '回测执行失败')
      }

      backtestResult.value = data
    } catch (err: any) {
      backtestError.value = err.message || '回测服务通信异常'
      backtestResult.value = null
    } finally {
      isBacktesting.value = false
    }
  }

  // 拉取用户历史回测记录
  async function fetchUserBacktests() {
    const authStore = useAuthStore()
    if (!authStore.token) {
      userBacktests.value = []
      return
    }
    userBacktestsLoading.value = true
    try {
      const res = await fetch('/api/v1/user/backtests', {
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
      if (res.ok) {
        userBacktests.value = await res.json()
      }
    } finally {
      userBacktestsLoading.value = false
    }
  }

  // 保存当前回测记录到用户名下
  async function saveBacktestRecord(customName?: string): Promise<{ success: boolean; message: string }> {
    const authStore = useAuthStore()
    if (!authStore.isLoggedIn) {
      authStore.openLogin()
      return { success: false, message: '请先登录后归档回测记录' }
    }
    if (!backtestResult.value) {
      return { success: false, message: '当前没有可归档的回测结果，请先运行回测' }
    }

    isSavingBacktest.value = true
    try {
      const sum = backtestResult.value.summary
      const res = await fetch('/api/v1/user/backtests', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authStore.token}`,
        },
        body: JSON.stringify({
          strategy_id: activeStrategyId.value && activeStrategyId.value > 0 ? activeStrategyId.value : null,
          strategy_name: customName || activeStrategyName.value,
          symbol: symbol.value,
          start_date: startDate.value,
          end_date: endDate.value || null,
          initial_cash: sum.initial_cash,
          final_equity: sum.final_equity,
          total_return: sum.total_return,
          annualized_return: sum.annualized_return,
          max_drawdown: sum.max_drawdown,
          sharpe_ratio: sum.sharpe_ratio,
          win_rate: sum.win_rate,
          total_trades: sum.total_trades,
        }),
      })

      const data = await res.json()
      if (!res.ok) {
        return { success: false, message: data.detail || '回测归档失败' }
      }

      await fetchUserBacktests()
      return { success: true, message: '🎉 回测绩效已永久归档到您的档案！' }
    } catch (err: any) {
      return { success: false, message: err.message || '网络连接异常' }
    } finally {
      isSavingBacktest.value = false
    }
  }

  // 删除历史回测记录
  async function deleteUserBacktest(id: number): Promise<boolean> {
    const authStore = useAuthStore()
    if (!authStore.token) return false
    try {
      const res = await fetch(`/api/v1/user/backtests/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authStore.token}` },
      })
      if (res.ok) {
        await fetchUserBacktests()
        return true
      }
      return false
    } catch {
      return false
    }
  }

  // 发送 AI 策略对话（流式 SSE）
  async function sendAiMessage(promptText: string) {
    if (!promptText.trim() || isAiStreaming.value) return

    // 1. 追加用户消息
    const userMsgId = `user_${Date.now()}`
    aiMessages.value.push({
      id: userMsgId,
      role: 'user',
      content: promptText.trim(),
      timestamp: Date.now(),
    })

    // 2. 准备助手流式消息
    const assistantMsgId = `ai_${Date.now()}`
    const assistantMsg: AiChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
    }
    aiMessages.value.push(assistantMsg)
    isAiStreaming.value = true

    try {
      const systemPrompt = `你是一位精通 A 股与 ETF 交易的顶尖量化架构师，为 QuantScope 平台服务。
平台策略继承 BaseStrategy (QuantCore 2.0 极简流式架构)，核心规范与内置 API 如下：

1. 标的行情与指标全部挂载在 bar 上 (自然流式语法，免去繁琐导入与计算):
   - 实时行情切片: bar.close, bar.open, bar.high, bar.low, bar.volume, bar.change_pct, bar.prev_close
   - 估值与基本面: bar.pe (市盈率), bar.pb (市净率), bar.ps, bar.turnover_rate (换手率)
   - 智能估值分析: bar.percentile(250) (过去N日分位数0.0~1.0), bar.is_undervalued (<=20%严重低估), bar.is_overvalued (>=80%严重泡沫)
   - 标的技术指标与算子 (直接在 bar 上调用):
     * bar.sma(period=20) / bar.ema(period=20)
     * bar.rsi(period=14)
     * bar.macd() -> 返回 (dif, dea, hist)
     * bar.atr(period=14)
     * bar.highest(period=20) / bar.lowest(period=20)
     * bar.cross_over(fast=5, slow=20) -> 金叉快捷判断 (支持周期整数或列表)
     * bar.cross_under(fast=5, slow=20) -> 死叉快捷判断
   - 标的历史切片列表: bar.closes(50), bar.highs(50), bar.lows(50), bar.history(50)

2. 账户资金、持仓与交易指令挂载在 self 上 (极简上下文感知):
   - self.cash: 当前可用现金 (float)
   - self.equity: 组合动态总资产 (float)
   - self.position: 当前标的持仓对象 (原生支持 if not self.position: 或 if self.position: 或 if self.position > 0:)
   - self.positions: 多标的持仓字典 {symbol: Position}
   - self.order_target_percent(0.8, reason="建仓") -> 调至目标仓位 (单标的省略 symbol，多标的传 symbol)
   - self.close_position(reason="平仓") -> 全仓清空当前标的持仓
   - self.buy(100, reason="买入") / self.sell(100, reason="卖出")

3. 标准策略代码模版骨架示例 (必须遵循此类结构与命名):
\`\`\`python
from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class MyStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="MyStrategy", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        # 1. 均线金叉且无持仓：以 80% 目标仓位买入
        if bar.cross_over(self.fast, self.slow) and not self.position:
            self.order_target_percent(0.8, reason="金叉开仓")

        # 2. 均线死叉且有持仓：全部平仓避险
        elif bar.cross_under(self.fast, self.slow) and self.position:
            self.close_position(reason="死叉平仓")
\`\`\`

代码生成要求：
1. 策略代码必须完整规范，包含类定义与 BaseStrategy 继承，可直接在沙箱执行。
2. 避免未来函数，必须做数据预热检查 (如 if len(self.bars) < 25: return 或 if bar.sma(20) == 0: return)。
3. 如果生成代码，必须使用 \`\`\`python ... \`\`\` 代码块包裹，以便用户一键载入编辑器。`

      const resp = await fetch('/api/v1/ai/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: promptText,
          model: aiModel.value,
          stream: true,
          system_prompt: systemPrompt,
        }),
      })

      if (!resp.ok) {
        throw new Error(`AI 服务异常 (${resp.status}): ${await resp.text()}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('无法创建流式读取器')

      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const rawData = line.slice(6).trim()
            if (rawData === '[DONE]') {
              break
            }
            try {
              const parsed = JSON.parse(rawData)
              if (parsed.delta) {
                assistantMsg.content += parsed.delta
              } else if (parsed.content) {
                assistantMsg.content = parsed.content
              }
            } catch {
              assistantMsg.content += rawData
            }
          }
        }
      }

      const codeBlock = extractPythonCode(assistantMsg.content)
      if (codeBlock) {
        assistantMsg.codeBlock = codeBlock
      }
    } catch (err: any) {
      assistantMsg.content += `\n\n> ⚠️ **调用异常**: ${err.message}`
    } finally {
      isAiStreaming.value = false
    }
  }

  return {
    code,
    symbol,
    startDate,
    endDate,
    initialCash,
    isBacktesting,
    backtestError,
    backtestResult,
    aiModel,
    isAiStreaming,
    aiMessages,
    userStrategies,
    userBacktests,
    activeStrategyId,
    activeStrategyName,
    isSavingStrategy,
    isSavingBacktest,
    userStrategiesLoading,
    userBacktestsLoading,
    updateCode,
    applyCodeToEditor,
    createBlankStrategy,
    runBacktest,
    sendAiMessage,
    extractPythonCode,
    fetchUserStrategies,
    saveStrategy,
    loadUserStrategy,
    deleteUserStrategy,
    fetchUserBacktests,
    saveBacktestRecord,
    deleteUserBacktest,
  }
})
