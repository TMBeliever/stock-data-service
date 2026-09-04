import { defineStore } from 'pinia'
import { ref } from 'vue'

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

export const STRATEGY_TEMPLATES: Record<string, { name: string; desc: string; code: string }> = {
  ma: {
    name: '经典双均线趋势策略 (Dual MA)',
    desc: '短期均线金叉做多，死叉平仓避险，经典趋势跟踪范式',
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class DualMAStrategy(BaseStrategy):
    """
    经典双均线交叉策略 (Dual Moving Average Cross)：
    - MA(5) 上穿 MA(20) 金叉：以 80% 目标仓位买入建仓；
    - MA(5) 下穿 MA(20) 死叉：全部平仓落袋为安。
    """
    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        super().__init__(name="DualMA", params={"fast": fast_period, "slow": slow_period})
        self.fast = fast_period
        self.slow = slow_period

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.slow + 2)
        if len(closes) < self.slow + 1:
            return

        ma_fast_prev = sum(closes[-self.fast - 1 : -1]) / self.fast
        ma_fast_curr = sum(closes[-self.fast :]) / self.fast

        ma_slow_prev = sum(closes[-self.slow - 1 : -1]) / self.slow
        ma_slow_curr = sum(closes[-self.slow :]) / self.slow

        pos = self.get_position(symbol)

        # 1. 金叉买入 (Golden Cross)
        if ma_fast_prev <= ma_slow_prev and ma_fast_curr > ma_slow_curr:
            if pos.quantity == 0:
                self.order_target_percent(symbol, 0.8, reason="金叉开仓")

        # 2. 死叉卖出 (Death Cross)
        elif ma_fast_prev >= ma_slow_prev and ma_fast_curr < ma_slow_curr:
            if pos.available_quantity > 0:
                self.close_position(symbol, reason="死叉平仓")
`
  },
  dividend_dca: {
    name: '动态估值分位数定投 (Smart DCA)',
    desc: '按历史价格分位数动态调权，极度低估时加倍定投，估值过高主动止盈',
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class SmartDividendDCAStrategy(BaseStrategy):
    """
    智能估值分位数定投策略：
    - 在 250 日滚动窗口中计算价格历史分位数；
    - 分位数 <= 20% (极度低估): 加码 2.0 倍基准金额买入；
    - 分位数 >= 85% (严重高估): 减仓 20% 主动止盈防回撤。
    """
    def __init__(self, base_amount: float = 2000.0, window: int = 250):
        super().__init__(name="SmartDCA", params={"base_amount": base_amount, "window": window})
        self.base_amount = base_amount
        self.window = window
        self.bar_counter = 0

    def on_bar(self, bar: Bar):
        self.bar_counter += 1
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=self.window)
        if len(closes) < 30:
            return

        # 每 5 个交易日评估一次定投
        if self.bar_counter % 5 != 0:
            return

        curr_price = bar.close
        # 计算历史分位数
        less_count = sum(1 for c in closes if c < curr_price)
        pct = less_count / len(closes)

        pos = self.get_position(symbol)
        portfolio = self.context.portfolio

        if pct <= 0.20 and portfolio.cash >= self.base_amount * 2:
            qty = int((self.base_amount * 2.0) / curr_price // 100) * 100
            if qty > 0:
                self.buy(symbol, qty, price=curr_price, reason=f"低估加倍定投(分位{pct:.1%})")
        elif pct <= 0.50 and portfolio.cash >= self.base_amount:
            qty = int(self.base_amount / curr_price // 100) * 100
            if qty > 0:
                self.buy(symbol, qty, price=curr_price, reason=f"合理估值定投(分位{pct:.1%})")
        elif pct >= 0.85 and pos.available_quantity >= 500:
            sell_qty = min(pos.available_quantity, int(pos.available_quantity * 0.2 // 100) * 100)
            if sell_qty > 0:
                self.sell(symbol, sell_qty, price=curr_price, reason=f"高估主动止盈(分位{pct:.1%})")
`
  },
  grid: {
    name: '动态网格波动套利 (Grid Trading)',
    desc: '在震荡市中利用均价带上下挂单，高抛低吸捕捉微观波动利润',
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class GridTradingStrategy(BaseStrategy):
    """
    动态自适应网格策略：
    - 以 60 日均线为中枢基准；
    - 价格下跌超 2.5% 触及下轨分批加仓；
    - 价格上涨超 2.5% 触及上轨获利止盈。
    """
    def __init__(self, step_pct: float = 0.025, base_shares: int = 1000):
        super().__init__(name="GridTrading", params={"step": step_pct})
        self.step_pct = step_pct
        self.base_shares = base_shares
        self.last_trade_price = 0.0

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=60)
        if len(closes) < 30:
            return

        ma_center = sum(closes) / len(closes)
        curr_price = bar.close
        pos = self.get_position(symbol)

        # 初始建底仓
        if self.last_trade_price == 0.0:
            self.order_target_percent(symbol, 0.4, reason="网格初始化底仓")
            self.last_trade_price = curr_price
            return

        # 下跌触及网格下轨加仓
        if curr_price <= self.last_trade_price * (1.0 - self.step_pct):
            if self.context.portfolio.cash >= curr_price * self.base_shares:
                self.buy(symbol, self.base_shares, price=curr_price, reason="网格低吸加仓")
                self.last_trade_price = curr_price

        # 上涨触及网格上轨止盈
        elif curr_price >= self.last_trade_price * (1.0 + self.step_pct):
            if pos.available_quantity >= self.base_shares:
                self.sell(symbol, self.base_shares, price=curr_price, reason="网格高抛止盈")
                self.last_trade_price = curr_price
`
  },
  dip_heavy: {
    name: '极端急跌重仓抄底 (Extreme Dip)',
    desc: '大盘或核心资产年内极端暴跌 15% 以上时果断重仓介入，反弹至均线平仓',
    code: `from quant_core.core.base_strategy import BaseStrategy
from quant_core.core.models import Bar

class ExtremeDipHeavyStrategy(BaseStrategy):
    """
    极端急跌重仓抄底策略：
    - 监控 120 日内最高价的高位回撤幅度；
    - 当自高点回撤超过 15% 且触底阳线反弹时，果断调仓至 90% 仓位重仓抄底；
    - 当价格重回 60 日均线之上时，分批结利降低风险暴露。
    """
    def __init__(self, dip_threshold: float = 0.15, ma_period: int = 60):
        super().__init__(name="ExtremeDip", params={"dip": dip_threshold, "ma": ma_period})
        self.dip_threshold = dip_threshold
        self.ma_period = ma_period

    def on_bar(self, bar: Bar):
        symbol = bar.symbol
        closes = self.context.get_closes(symbol, n=120)
        if len(closes) < 60:
            return

        max_close = max(closes)
        curr_price = bar.close
        drawdown_from_peak = (max_close - curr_price) / max_close
        pos = self.get_position(symbol)

        ma_val = sum(closes[-self.ma_period :]) / self.ma_period

        # 触发极端超跌：一次性重仓建仓
        if drawdown_from_peak >= self.dip_threshold and pos.quantity == 0:
            self.order_target_percent(symbol, 0.90, reason=f"暴跌{drawdown_from_peak:.1%}极端抄底")

        # 均线修复出场
        elif curr_price > ma_val and pos.available_quantity > 0:
            self.order_target_percent(symbol, 0.20, reason="价格回归均线减仓止盈")
`
  }
}

const STORAGE_CODE_KEY = 'quantscope_custom_strategy_code'

export const useStrategyStore = defineStore('strategy', () => {
  // 1. 代码编辑器状态
  const savedCode = localStorage.getItem(STORAGE_CODE_KEY)
  const code = ref(savedCode || STRATEGY_TEMPLATES.ma.code)
  const selectedTemplate = ref('ma')

  // 2. 回测参数状态
  const symbol = ref('510300.SH.ETF')
  const startDate = ref('2023-01-01')
  const endDate = ref('')
  const initialCash = ref(100000)

  // 3. 回测运行状态与结果
  const isBacktesting = ref(false)
  const backtestError = ref<string | null>(null)
  const backtestResult = ref<BacktestResultData | null>(null)

  // 4. AI Copilot 对话状态
  const aiModel = ref<'gemini-flash-lite-latest' | 'claude'>('gemini-flash-lite-latest')
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

  // 切换预设模板
  function applyTemplate(key: string) {
    if (STRATEGY_TEMPLATES[key]) {
      selectedTemplate.value = key
      code.value = STRATEGY_TEMPLATES[key].code
      localStorage.setItem(STORAGE_CODE_KEY, code.value)
    }
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
      // 携带量化系统规范系统提示词
      const systemPrompt = `你是一位精通 A 股与 ETF 交易的顶尖量化架构师，为 QuantScope 平台服务。
平台策略继承 BaseStrategy，核心方法包括：
- on_bar(self, bar: Bar)
- self.context.get_closes(symbol, n)
- self.order_target_percent(symbol, target_pct, reason)
- self.close_position(symbol, reason)
- self.buy(symbol, quantity, price, reason)
- self.sell(symbol, quantity, price, reason)
- self.get_position(symbol)
要求：
1. 策略代码必须完整规范，包含类定义与继承。
2. 避免未来函数，注意除零保护与历史数据长度检查。
3. 如果生成代码，请始终用 \`\`\`python ... \`\`\` 包裹，便于前端一键识别应用。`

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
              // 容忍非 JSON delta
              assistantMsg.content += rawData
            }
          }
        }
      }

      // 提取代码块供一键应用
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
    selectedTemplate,
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
    applyTemplate,
    updateCode,
    applyCodeToEditor,
    runBacktest,
    sendAiMessage,
    extractPythonCode,
  }
})
