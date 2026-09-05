<script setup lang="ts">
import { ref, computed, shallowRef, onMounted, onUnmounted, watch } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { autocompletion, type CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import { EditorView } from '@codemirror/view'
import { useStrategyStore, type UserStrategyItem } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'
import { useAiStore } from '@/stores/ai'
import { copyToClipboard } from '@/utils/clipboard'

const strategyStore = useStrategyStore()
const authStore = useAuthStore()
const aiStore = useAiStore()

const editorView = shallowRef<EditorView | null>(null)
const showCheatSheet = ref(false)
const showSaveModal = ref(false)
const showMyStrategies = ref(false)
const insertToast = ref('')

// 保存策略弹窗状态
const saveMode = ref<'create' | 'update'>('create')
const saveNameInput = ref('')
const saveDescInput = ref('')

// 判断当前是否在编辑已有的云端策略 (id > 0)
const canUpdateCurrent = computed(() => {
  return !!strategyStore.activeStrategyId && strategyStore.activeStrategyId > 0
})

// 1. 量化专有智能代码补全 (Quant Intellisense Source)
function quantCompletionSource(context: CompletionContext): CompletionResult | null {
  const line = context.state.doc.lineAt(context.pos)
  const lineText = line.text.slice(0, context.pos - line.from)

  // 辅助：获取光标后紧邻的单词字符以精准确定替换结束点 to，避免补全后残留杂散字符
  const afterMatch = context.state.sliceDoc(context.pos, context.pos + 50).match(/^\w*/)
  const to = context.pos + (afterMatch ? afterMatch[0].length : 0)

  // A. 匹配 self.context. 或 context.
  if (/self\.context\.\w*$/.test(lineText) || /(^|\s)context\.\w*$/.test(lineText)) {
    const match = lineText.match(/(?:self\.)?context\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      to,
      options: [
        { label: 'get_closes', type: 'method', detail: '历史收盘序列 · closes(sym, n)', info: '【历史收盘】获取指定标的最近 N 根收盘价 List[float]' },
        { label: 'get_highs', type: 'method', detail: '历史最高序列 · highs(sym, n)', info: '【历史最高】获取指定标的最近 N 根最高价 List[float]' },
        { label: 'get_lows', type: 'method', detail: '历史最低序列 · lows(sym, n)', info: '【历史最低】获取指定标的最近 N 根最低价 List[float]' },
        { label: 'get_volumes', type: 'method', detail: '历史成交序列 · volumes(sym, n)', info: '【历史成交】获取指定标的最近 N 根成交量 List[float]' },
        { label: 'get_opens', type: 'method', detail: '历史开盘序列 · opens(sym, n)', info: '【历史开盘】获取指定标的最近 N 根开盘价 List[float]' },
        { label: 'portfolio', type: 'property', detail: '账户总线组合 · Portfolio', info: '【账户组合】总线组合对象 (包含 cash, total_equity, positions)' },
      ],
      validFor: /^\w*$/,
    }
  }

  // B. 匹配 self.
  if (/self\.\w*$/.test(lineText)) {
    const match = lineText.match(/self\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      to,
      options: [
        { label: 'position', type: 'property', detail: '当前标的持仓 · Position', info: '【当前持仓】当前标的持仓对象，直接支持 if self.position > 0: 或 if not self.position:' },
        { label: 'cash', type: 'property', detail: '可用现金余额 · float', info: '【可用现金】当前可用现金余额 (CNY)' },
        { label: 'equity', type: 'property', detail: '账户总资产 · float', info: '【动态权益】账户总动态资产 (现金 + 持仓总市值)' },
        { label: 'order_target_percent', type: 'method', detail: '智能调仓 · (pct, reason)', info: '【智能调仓】调至总资产目标比例 (0.0~1.0)，单标的自动省略 symbol' },
        { label: 'close_position', type: 'method', detail: '一键清仓平仓 · (reason)', info: '【一键平仓】清空当前标的所有可用持仓' },
        { label: 'buy', type: 'method', detail: '智能买入 · (qty, price)', info: '【智能买入】按当前市价或限价买入指定股数' },
        { label: 'sell', type: 'method', detail: '智能卖出 · (qty, price)', info: '【智能卖出】按当前市价或限价卖出指定股数' },
        { label: 'positions', type: 'property', detail: '全仓持仓字典 · Dict[str, Pos]', info: '【全仓持仓】所有标的持仓字典 {symbol: Position}' },
        { label: 'bars', type: 'property', detail: '历史Bar序列 · List[Bar]', info: '【历史切片】当前标的接收到的所有历史 Bar 序列' },
        { label: 'sma', type: 'method', detail: '标的移动均线 · sma(20)', info: '【移动均线】当前标的简单移动平均: self.sma(20)' },
        { label: 'cross_over', type: 'method', detail: '均线金叉 · (fast, slow)', info: '【均线金叉】自动判断当前标的均线金叉: self.cross_over(5, 20)' },
        { label: 'cross_under', type: 'method', detail: '均线死叉 · (fast, slow)', info: '【均线死叉】自动判断当前标的均线死叉: self.cross_under(5, 20)' },
        { label: 'closes', type: 'method', detail: '历史收盘序列 · closes(50)', info: '【历史收盘】获取当前标的最近 N 根收盘价 List[float]' },
        { label: 'get_position', type: 'method', detail: '查询指定持仓 · (symbol)', info: '【指定持仓】获取指定 symbol 的 Position 对象' },
        { label: 'context', type: 'property', detail: '底层上下文 · StrategyContext', info: '【底层上下文】StrategyContext 核心状态总线' },
      ],
      validFor: /^\w*$/,
    }
  }

  // C. 匹配 bar. (标的行情、估值、指标与历史序列)
  if (/bar\.\w*$/.test(lineText)) {
    const match = lineText.match(/bar\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      to,
      options: [
        // 1. 基础行情与价格切片
        { label: 'close', type: 'property', detail: '最新收盘价 · float', info: '【核心价格】当前 K 线最新收盘价 (如 3.850)' },
        { label: 'open', type: 'property', detail: '今日开盘价 · float', info: '【核心价格】当前 K 线开盘价' },
        { label: 'high', type: 'property', detail: '最高价格 · float', info: '【核心价格】当前 K 线最高价' },
        { label: 'low', type: 'property', detail: '最低价格 · float', info: '【核心价格】当前 K 线最低价' },
        { label: 'volume', type: 'property', detail: '成交量(股) · float', info: '【成交数据】当前 K 线成交量 (股)' },
        { label: 'prev_close', type: 'property', detail: '昨日收盘价 · float', info: '【昨日收盘】上一交易日收盘价' },
        { label: 'change', type: 'property', detail: '涨跌额(元) · float', info: '【价格涨跌】最新涨跌额 (close - prev_close)' },
        { label: 'change_pct', type: 'property', detail: '涨跌幅比例 · float', info: '【涨跌比例】最新涨跌幅比例 (如 +0.03 代表 +3.0%)' },
        { label: 'amplitude', type: 'property', detail: '日内振幅 · float', info: '【日内振幅】(high - low) / prev_close 振幅比例' },
        { label: 'is_up', type: 'property', detail: '收阳线判定 · bool', info: '【阳线判定】今日是否收阳 (close >= open)' },
        { label: 'is_down', type: 'property', detail: '收阴线判定 · bool', info: '【阴线判定】今日是否收阴 (close < open)' },

        // 2. 估值与基本面指标
        { label: 'pe', type: 'property', detail: '动态市盈率 · TTM', info: '【市盈率】标的当前动态 PE (TTM 估值)' },
        { label: 'pb', type: 'property', detail: '市净率 · PB', info: '【市净率】标的当前市净率 PB' },
        { label: 'ps', type: 'property', detail: '市销率 · PS', info: '【市销率】标的当前市销率 PS' },
        { label: 'turnover_rate', type: 'property', detail: '换手率比例 · %', info: '【换手率】今日实际换手率比例 (%)' },
        { label: 'percentile', type: 'method', detail: '估值分位数 · percentile(250)', info: '【估值分位】过去 N 日价格滚动历史分位数 (0.0~1.0)' },
        { label: 'is_undervalued', type: 'property', detail: '深度低估信号 · bool', info: '【深度低估】过去 250 日分位数 <= 20% 或 PE < 15' },
        { label: 'is_overvalued', type: 'property', detail: '高估泡沫信号 · bool', info: '【高估泡沫】过去 250 日分位数 >= 80% 或 PE > 50' },

        // 3. 高频技术指标与形态算子
        { label: 'sma', type: 'method', detail: '简单移动均线 · sma(20)', info: '【移动均线】简单移动平均 SMA: bar.sma(20)' },
        { label: 'ema', type: 'method', detail: '指数移动均线 · ema(20)', info: '【指数均线】指数移动平均 EMA: bar.ema(20)' },
        { label: 'rsi', type: 'method', detail: '相对强弱指标 · rsi(14)', info: '【强弱指标】相对强弱指标 RSI (0~100): bar.rsi(14)' },
        { label: 'macd', type: 'method', detail: '平滑异同均线 · macd()', info: '【MACD】平滑异同移动平均: dif, dea, hist = bar.macd()' },
        { label: 'atr', type: 'method', detail: '真实波幅 · atr(14)', info: '【真实波幅】平均真实波幅 ATR: bar.atr(14)' },
        { label: 'highest', type: 'method', detail: '区间最高价 · highest(20)', info: '【区间极高】唐奇安通道上轨 (过去 N 日最高价)' },
        { label: 'lowest', type: 'method', detail: '区间最低价 · lowest(20)', info: '【区间极低】唐奇安通道下轨 (过去 N 日最低价)' },
        { label: 'cross_over', type: 'method', detail: '均线金叉上穿 · bool', info: '【均线金叉】快捷金叉判断: bar.cross_over(5, 20)' },
        { label: 'cross_under', type: 'method', detail: '均线死叉下穿 · bool', info: '【均线死叉】快捷死叉判断: bar.cross_under(5, 20)' },

        // 4. 标的历史行情切片序列
        { label: 'closes', type: 'method', detail: '收盘价序列 · closes(50)', info: '【收盘序列】获取当前标的最近 N 根收盘价 List[float]' },
        { label: 'highs', type: 'method', detail: '最高价序列 · highs(50)', info: '【最高序列】获取当前标的最近 N 根最高价 List[float]' },
        { label: 'lows', type: 'method', detail: '最低价序列 · lows(50)', info: '【最低序列】获取当前标的最近 N 根最低价 List[float]' },
        { label: 'opens', type: 'method', detail: '开盘价序列 · opens(50)', info: '【开盘序列】获取当前标的最近 N 根开盘价 List[float]' },
        { label: 'volumes', type: 'method', detail: '成交量序列 · volumes(50)', info: '【成交序列】获取当前标的最近 N 根成交量 List[float]' },
        { label: 'history', type: 'method', detail: '历史Bar序列 · history(50)', info: '【切片历史】获取当前标的最近 N 根 Bar 对象序列' },

        // 5. 标的元信息
        { label: 'symbol', type: 'property', detail: '标的代码 · str', info: '【标的代码】当前标的代码 (如 510300.SH.ETF)' },
        { label: 'date_str', type: 'property', detail: '日期切片 · str', info: '【日期切片】当前切片日期字符串 (YYYY-MM-DD)' },
        { label: 'dt', type: 'property', detail: '时间对象 · datetime', info: '【时间对象】当前切片标准 UTC datetime 对象' },
      ],
      validFor: /^\w*$/,
    }
  }

  // D. 匹配 pos. (持仓对象)
  if (/pos\.\w*$/.test(lineText)) {
    const match = lineText.match(/pos\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      to,
      options: [
        { label: 'quantity', type: 'property', detail: '持仓总股数 · float', info: '【持仓股数】当前标的持仓总股数' },
        { label: 'available_quantity', type: 'property', detail: '可用股数(T+1) · float', info: '【可用股数】A 股 T+1 交易制度下当前可卖出的股数' },
        { label: 'avg_cost', type: 'property', detail: '持仓均价成本 · float', info: '【持仓成本】当前标的持仓均价 (CNY)' },
        { label: 'current_price', type: 'property', detail: '最新收盘市价 · float', info: '【最新市价】当前标的最新收盘价格' },
        { label: 'market_value', type: 'property', detail: '持仓总市值 · float', info: '【持仓市值】当前标的持仓总市值 (股数 * 最新价)' },
      ],
      validFor: /^\w*$/,
    }
  }

  // E. 全局通用指标函数智能提示
  const word = context.matchBefore(/\w+/)
  if (!word || (word.from === word.to && !context.explicit)) return null

  return {
    from: word.from,
    to,
    options: [
      { label: 'bar', type: 'variable', detail: 'K线行情切片 · Bar', info: '【行情切片】当前触发 on_bar 的 K 线对象，包含估值与指标' },
      { label: 'self', type: 'keyword', detail: '当前策略实例 · BaseStrategy', info: '【策略实例】当前 BaseStrategy 实例，管理持仓与交易' },
      { label: 'sma', type: 'function', detail: '简单移动均线 · sma(c, 20)', info: '【内置算子】简单移动平均线: sma(closes, 20)' },
      { label: 'ema', type: 'function', detail: '指数移动均线 · ema(c, 12)', info: '【内置算子】指数移动平均线: ema(closes, 12)' },
      { label: 'rsi', type: 'function', detail: '相对强弱指标 · rsi(c, 14)', info: '【内置算子】相对强弱指标 (0~100): rsi(closes, 14)' },
      { label: 'macd', type: 'function', detail: 'MACD指标 · macd(closes)', info: '【内置算子】平滑异同移动平均: dif, dea, hist = macd(closes)' },
      { label: 'bollinger_bands', type: 'function', detail: '布林带轨道 · (closes, 20)', info: '【内置算子】布林带: upper, mid, lower = bollinger_bands(closes)' },
      { label: 'atr', type: 'function', detail: '真实波幅 · atr(h, l, c, 14)', info: '【内置算子】真实波幅均值: atr_val = atr(highs, lows, closes, 14)' },
      { label: 'order_target_percent', type: 'method', detail: '智能调仓指令 · (pct, reason)', info: '【调仓指令】self.order_target_percent(0.8, reason="开仓")' },
      { label: 'close_position', type: 'method', detail: '一键平仓指令 · (reason)', info: '【平仓指令】self.close_position(reason="止损平仓")' },
    ],
  }
}

// 极客暗黑 CodeMirror 补全弹窗与对齐主题 (Raycast / Cursor 风格)
const quantEditorTheme = EditorView.theme({
  '.cm-tooltip': {
    border: '1px solid rgba(255, 255, 255, 0.12) !important',
    backgroundColor: '#16171d !important',
    borderRadius: '10px !important',
    boxShadow: '0 20px 48px -10px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.08) !important',
  },
  '.cm-tooltip.cm-tooltip-autocomplete': {
    overflow: 'visible !important',
    minWidth: '420px !important',
    maxWidth: '580px !important',
    padding: '4px !important',
  },
  '.cm-tooltip-autocomplete > ul': {
    maxHeight: '280px !important',
    padding: '2px !important',
    overflowY: 'auto !important',
    overflowX: 'hidden !important',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important',
    fontSize: '12px !important',
  },
  '.cm-tooltip-autocomplete > ul > li': {
    display: 'flex !important',
    alignItems: 'center !important',
    justifyContent: 'space-between !important',
    height: '28px !important',
    lineHeight: '28px !important',
    padding: '0 8px !important',
    borderRadius: '6px !important',
    margin: '1px 0 !important',
    color: '#d1d5db !important',
    cursor: 'pointer !important',
  },
  '.cm-tooltip-autocomplete > ul > li[aria-selected="true"]': {
    background: 'linear-gradient(90deg, rgba(255, 95, 61, 0.25) 0%, rgba(255, 95, 61, 0.10) 100%) !important',
    borderLeft: '2px solid #ff5f3d !important',
    color: '#ffffff !important',
    fontWeight: '600 !important',
  },
  '.cm-completionIcon': {
    width: '18px !important',
    height: '18px !important',
    marginRight: '8px !important',
    display: 'inline-flex !important',
    alignItems: 'center !important',
    justifyContent: 'center !important',
    fontSize: '10px !important',
    borderRadius: '4px !important',
    background: 'rgba(255, 255, 255, 0.06) !important',
    color: '#94a3b8 !important',
    flexShrink: '0 !important',
  },
  '.cm-completionIcon-property': {
    color: '#38bdf8 !important',
    background: 'rgba(56, 189, 248, 0.15) !important',
  },
  '.cm-completionIcon-method, .cm-completionIcon-function': {
    color: '#c084fc !important',
    background: 'rgba(192, 132, 252, 0.15) !important',
  },
  '.cm-completionIcon-keyword': {
    color: '#fbbf24 !important',
    background: 'rgba(251, 191, 36, 0.15) !important',
  },
  '.cm-completionIcon-variable': {
    color: '#34d399 !important',
    background: 'rgba(52, 211, 153, 0.15) !important',
  },
  '.cm-completionLabel': {
    fontWeight: '500 !important',
    color: '#f3f4f6 !important',
    marginRight: '12px !important',
    flexShrink: '0 !important',
  },
  '.cm-completionMatchedText': {
    textDecoration: 'none !important',
    color: '#ff5f3d !important',
    fontWeight: '700 !important',
    background: 'rgba(255, 95, 61, 0.2) !important',
    borderRadius: '2px !important',
    padding: '0 2px !important',
  },
  '.cm-completionDetail': {
    marginLeft: 'auto !important',
    textAlign: 'right !important',
    color: '#9ca3af !important',
    fontSize: '11px !important',
    fontStyle: 'normal !important',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", monospace !important',
    opacity: '0.9 !important',
    whiteSpace: 'nowrap !important',
  },
  '.cm-tooltip-autocomplete > ul > li[aria-selected="true"] .cm-completionDetail': {
    color: '#fed7aa !important',
    opacity: '1 !important',
    fontWeight: '500 !important',
  },
  '.cm-tooltip.cm-completionInfo': {
    background: 'rgba(20, 21, 27, 0.98) !important',
    backdropFilter: 'blur(20px) !important',
    border: '1px solid rgba(255, 255, 255, 0.14) !important',
    borderRadius: '10px !important',
    boxShadow: '0 20px 48px rgba(0, 0, 0, 0.75) !important',
    padding: '10px 14px !important',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif !important',
    fontSize: '12px !important',
    lineHeight: '1.6 !important',
    color: '#e4e4e7 !important',
    maxWidth: '380px !important',
    zIndex: '10001 !important',
  },
})

const extensions = Object.freeze([
  python(),
  oneDark,
  quantEditorTheme,
  autocompletion({
    override: [quantCompletionSource],
    activateOnTyping: true,
  }),
])

function handleReady(payload: { view: EditorView }) {
  editorView.value = payload.view
}

// 2. 将代码精准插入当前编辑器光标所在行
function insertSnippet(codeToInsert: string) {
  if (editorView.value) {
    const view = editorView.value
    const { from, to } = view.state.selection.main
    const snippetWithNewline = codeToInsert.trim() + '\n'
    view.dispatch({
      changes: { from, to, insert: snippetWithNewline },
      selection: { anchor: from + snippetWithNewline.length },
      scrollIntoView: true,
    })
    view.focus()
  } else {
    strategyStore.code += `\n        ${codeToInsert}\n`
  }

  showCheatSheet.value = false
  showToast('✅ 已成功插入代码到光标处！')
}

function showToast(msg: string) {
  insertToast.value = msg
  setTimeout(() => {
    insertToast.value = ''
  }, 2800)
}

const lineCount = computed(() => strategyStore.code.split('\n').length)
const charCount = computed(() => strategyStore.code.length)

// 常用 API 片段速查表 (QuantCore 2.0 极简范式)
const apiCheatSheet = [
  {
    category: '📊 常用技术指标与形态算子 (直接在 bar 或 self 上调用)',
    items: [
      { name: 'bar.sma(20)', desc: '简单移动平均 (SMA)', code: 'ma20 = bar.sma(20)' },
      { name: 'bar.ema(12)', desc: '指数移动平均 (EMA)', code: 'ema12 = bar.ema(12)' },
      { name: 'bar.rsi(14)', desc: '相对强弱指标 (0~100)', code: 'rsi_val = bar.rsi(14)' },
      { name: 'bar.macd()', desc: 'MACD (返回 DIF, DEA, 柱)', code: 'dif, dea, hist = bar.macd()' },
      { name: 'bar.atr(14)', desc: '真实波幅均值 (ATR)', code: 'atr_val = bar.atr(14)' },
      { name: 'bar.highest(20) / lowest(20)', desc: '唐奇安通道高低轨 (前20日极值)', code: 'entry_high = bar.highest(20, include_current=False)' },
      { name: 'bar.cross_over(5, 20)', desc: '均线金叉上穿判断', code: 'if bar.cross_over(5, 20):' },
      { name: 'bar.cross_under(5, 20)', desc: '均线死叉下穿判断', code: 'elif bar.cross_under(5, 20):' },
    ],
  },
  {
    category: '📈 行情切片与估值分析 (bar)',
    items: [
      { name: 'bar.close / open / high / low', desc: '当前 K 线切片原始价格', code: 'curr_price = bar.close' },
      { name: 'bar.change_pct / amplitude', desc: '涨跌幅比例 (如 +0.03) / 振幅', code: 'pct = bar.change_pct' },
      { name: 'bar.pe / bar.pb', desc: '动态市盈率 / 市净率估值', code: 'if bar.pe and bar.pe < 15:' },
      { name: 'bar.is_undervalued', desc: '是否低估 (分位<=20%或PE<15)', code: 'if bar.is_undervalued:' },
      { name: 'bar.is_overvalued', desc: '是否高估 (分位>=80%或PE>50)', code: 'if bar.is_overvalued:' },
      { name: 'bar.percentile(250)', desc: '过去 N 日价格历史分位数 (0.0~1.0)', code: 'pct = bar.percentile(250)' },
      { name: 'bar.closes(50)', desc: '获取最近 N 根收盘价列表 (List[float])', code: 'closes = bar.closes(50)' },
    ],
  },
  {
    category: '🛒 账户资金与交易指令 (self)',
    items: [
      { name: 'self.order_target_percent(0.8)', desc: '调仓至总资产目标比例 (0.0~1.0)', code: 'self.order_target_percent(0.8, reason="建仓")' },
      { name: 'self.close_position()', desc: '一键全仓清空当前标的持仓', code: 'self.close_position(reason="止损出场")' },
      { name: 'self.buy(100) / sell(100)', desc: '智能买入/卖出指定股数 (自动取市价)', code: 'self.buy(100, reason="加仓")' },
      { name: 'self.position', desc: '当前标的持仓 (支持 if self.position > 0:)', code: 'if not self.position:' },
      { name: 'self.cash / self.equity', desc: '当前可用现金 / 动态总资产 (CNY)', code: 'if self.cash > 10000:' },
    ],
  },
]

async function copyCode() {
  const ok = await copyToClipboard(strategyStore.code)
  if (ok) {
    showToast('📋 代码已复制到剪贴板')
  } else {
    showToast('⚠️ 复制失败，请尝试手动选中文本复制')
  }
}

// 快速新建空白策略
function handleCreateBlankStrategy() {
  strategyStore.createBlankStrategy()
  showMyStrategies.value = false
  showToast('✨ 已创建空白策略模板，编写后点击保存即可存入策略库')
}

// 打开保存弹窗：允许选择“修改原策略”或“另存为新策略”
function openSaveModal() {
  if (!authStore.isLoggedIn) {
    authStore.openLogin()
    return
  }

  if (canUpdateCurrent.value) {
    saveMode.value = 'update'
    saveNameInput.value = strategyStore.activeStrategyName
  } else {
    saveMode.value = 'create'
    saveNameInput.value = strategyStore.activeStrategyName.includes('未保存')
      ? '我的新量化策略'
      : strategyStore.activeStrategyName
  }
  saveDescInput.value = ''
  showSaveModal.value = true
}

// 切换保存模式
function setSaveMode(mode: 'create' | 'update') {
  saveMode.value = mode
  if (mode === 'create') {
    if (saveNameInput.value === strategyStore.activeStrategyName) {
      saveNameInput.value = `${strategyStore.activeStrategyName} (副本)`
    }
  } else {
    saveNameInput.value = strategyStore.activeStrategyName
  }
}

// 确认保存
async function confirmSaveStrategy() {
  if (!saveNameInput.value.trim()) {
    showToast('⚠️ 策略名称不能为空')
    return
  }
  const res = await strategyStore.saveStrategy(
    saveNameInput.value.trim(),
    saveDescInput.value.trim(),
    saveMode.value
  )
  if (res.success) {
    showSaveModal.value = false
    showToast(res.message)
  } else {
    alert(res.message)
  }
}

// 载入已有策略
function handleSelectUserStrategy(strat: UserStrategyItem) {
  strategyStore.loadUserStrategy(strat)
  showMyStrategies.value = false
  showToast(`📂 已载入策略: ${strat.name}`)
}

// 删除已有策略
async function handleDeleteUserStrategy(strat: UserStrategyItem, e: Event) {
  e.stopPropagation()
  if (confirm(`确定要彻底删除策略「${strat.name}」吗？`)) {
    const ok = await strategyStore.deleteUserStrategy(strat.id)
    if (ok) {
      showToast('🗑️ 策略已删除')
    }
  }
}

// 键盘快捷键监听 (⌘+Enter 运行回测, ⌘+S 保存策略)
function handleKeyDown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    strategyStore.runBacktest()
  } else if ((e.metaKey || e.ctrlKey) && e.key === 's') {
    e.preventDefault()
    openSaveModal()
  }
}

watch(
  () => authStore.isLoggedIn,
  (logged) => {
    if (logged) {
      strategyStore.fetchUserStrategies()
      strategyStore.fetchUserBacktests()
    }
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl relative">
    <!-- 提示气泡 Toast -->
    <div
      v-if="insertToast"
      class="absolute top-14 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-emerald-500/90 text-white font-medium text-xs shadow-xl backdrop-blur-sm animate-bounce"
    >
      {{ insertToast }}
    </div>

    <!-- 1. 顶部操作栏 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-2 shrink-0">
      <!-- 左侧：策略名称、我的策略库下拉与新建策略 -->
      <div class="flex items-center space-x-2">
        <!-- 策略名称徽标 -->
        <div class="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono text-zinc-300">
          <span class="text-amber-400">🐍</span>
          <span class="font-semibold text-white truncate max-w-[150px] sm:max-w-[200px]">
            {{ strategyStore.activeStrategyName }}
          </span>
          <span
            v-if="strategyStore.activeStrategyId && strategyStore.activeStrategyId > 0"
            class="px-1.5 py-0.2 rounded text-[9px] bg-emerald-500/20 text-emerald-400 font-sans"
          >
            云端已同步
          </span>
          <span
            v-else
            class="px-1.5 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-400 font-sans"
          >
            本地草稿
          </span>
        </div>

        <!-- 我的云端策略库下拉按钮 -->
        <div class="relative">
          <button
            @click="showMyStrategies = !showMyStrategies"
            class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs text-zinc-300 hover:text-white transition-all flex items-center space-x-1.5 cursor-pointer"
          >
            <span>📂</span>
            <span>我的策略库</span>
            <span
              class="px-1.5 py-0.2 rounded-full bg-red-500/20 text-red-400 text-[10px] font-bold font-mono"
            >
              {{ strategyStore.userStrategies.length }}
            </span>
          </button>

          <!-- 策略库下拉浮层 -->
          <div
            v-if="showMyStrategies"
            class="absolute top-9 left-0 z-40 w-80 bg-[#18191e] border border-white/[0.12] rounded-xl shadow-2xl p-2.5 space-y-2 animate-fadeIn"
          >
            <div class="flex items-center justify-between px-1 pb-1.5 border-b border-white/[0.06] text-xs">
              <span class="font-bold text-white">个人专属策略库</span>
              <span class="text-[10px] text-zinc-400">
                {{ authStore.isVip ? '👑 VIP 无限配额' : `已存 ${strategyStore.userStrategies.length} / 10 套` }}
              </span>
            </div>

            <!-- 未登录提示条 -->
            <div v-if="!authStore.isLoggedIn" class="p-2.5 rounded-lg bg-white/[0.02] border border-white/[0.06] text-center space-y-1.5 text-xs text-zinc-400">
              <p class="text-[11px]">当前为本地离线体验，登录后可永久同步至云端</p>
              <button
                @click="authStore.openLogin(); showMyStrategies = false"
                class="w-full py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 text-white font-bold text-xs"
              >
                立即登录 / 注册
              </button>
            </div>

            <!-- 策略列表 -->
            <div class="max-h-64 overflow-y-auto space-y-1 text-xs">
              <div
                v-for="strat in strategyStore.userStrategies"
                :key="strat.id"
                @click="handleSelectUserStrategy(strat)"
                :class="strategyStore.activeStrategyId === strat.id ? 'bg-red-500/15 border-red-500/40 text-white' : 'hover:bg-white/[0.04] text-zinc-300 border-transparent'"
                class="p-2 rounded-lg border flex items-center justify-between cursor-pointer transition-colors group"
              >
                <div class="truncate mr-2">
                  <div class="font-semibold text-xs truncate flex items-center space-x-1.5">
                    <span>{{ strat.name }}</span>
                    <span
                      v-if="strategyStore.activeStrategyId === strat.id"
                      class="text-[9px] px-1 py-0.2 rounded bg-red-500/30 text-red-300 font-normal"
                    >
                      正在编辑
                    </span>
                  </div>
                  <div class="text-[10px] text-zinc-500 truncate mt-0.5">
                    {{ strat.description || '默认标的: ' + strat.symbol }}
                  </div>
                </div>

                <button
                  @click="handleDeleteUserStrategy(strat, $event)"
                  title="删除策略"
                  class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-all text-[11px]"
                >
                  ✕
                </button>
              </div>
            </div>

            <!-- 底部：快速新建空白策略 -->
            <div class="pt-1.5 border-t border-white/[0.06]">
              <button
                @click="handleCreateBlankStrategy"
                class="w-full py-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-all text-xs flex items-center justify-center space-x-1.5 cursor-pointer"
              >
                <span>➕</span>
                <span>新建空白策略</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 保存策略按钮 -->
        <button
          @click="openSaveModal"
          :disabled="strategyStore.isSavingStrategy"
          class="px-2.5 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] border border-white/[0.1] text-xs text-zinc-200 hover:text-white transition-all flex items-center space-x-1 cursor-pointer"
        >
          <span>💾</span>
          <span>{{ strategyStore.isSavingStrategy ? '保存中...' : '保存策略' }}</span>
        </button>
      </div>

      <!-- 右侧：AI 助手、API 速查、代码操作与运行回测 -->
      <div class="flex items-center space-x-2">
        <!-- ✨ AI 助手唤醒按钮 -->
        <button
          @click="aiStore.toggleOpen()"
          :class="aiStore.isOpen ? 'bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border-amber-500/40 shadow-sm' : 'bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 border-white/[0.08]'"
          class="px-2.5 py-1 rounded-lg border text-xs transition-all flex items-center space-x-1.5 cursor-pointer group"
          title="唤出全站 AI 策略助手 (⌘+J)"
        >
          <span>✨</span>
          <span>AI 助手</span>
          <span class="text-[10px] text-zinc-500 font-mono hidden md:inline">⌘J</span>
        </button>

        <!-- 常用 API 片段速查表按钮 -->
        <button
          @click="showCheatSheet = true"
          class="px-2.5 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-300 transition-all text-xs flex items-center space-x-1 cursor-pointer"
        >
          <span>📖</span>
          <span class="hidden sm:inline">API 速查</span>
        </button>

        <!-- 复制代码 -->
        <button
          @click="copyCode"
          class="px-2 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-zinc-400 hover:text-zinc-200 transition-all text-xs flex items-center space-x-1 cursor-pointer"
        >
          <span>📋</span>
          <span class="hidden sm:inline">复制</span>
        </button>

        <!-- 运行回测主按钮 -->
        <button
          @click="strategyStore.runBacktest"
          :disabled="strategyStore.isBacktesting"
          class="px-3.5 py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-50 text-white font-semibold text-xs flex items-center space-x-1.5 shadow-md shadow-red-500/20 transition-all cursor-pointer"
        >
          <span v-if="!strategyStore.isBacktesting">▶</span>
          <span v-else class="w-3 h-3 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
          <span>{{ strategyStore.isBacktesting ? '撮合中...' : '运行回测' }}</span>
          <span class="hidden sm:inline text-[10px] text-white/60 font-mono font-normal">(⌘+Enter)</span>
        </button>
      </div>
    </div>

    <!-- 2. CodeMirror 编辑器主体 -->
    <div class="flex-1 relative overflow-hidden bg-[#1e1e1e]">
      <Codemirror
        v-model="strategyStore.code"
        :extensions="extensions"
        :style="{ height: '100%', width: '100%', fontSize: '13px' }"
        @ready="handleReady"
      />
    </div>

    <!-- 3. 底部状态栏 -->
    <div class="px-4 py-1.5 bg-black/40 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-500 font-mono shrink-0">
      <div class="flex items-center space-x-4">
        <span>行数: {{ lineCount }}</span>
        <span>字符: {{ charCount }}</span>
        <span class="hidden sm:inline">编码: UTF-8</span>
      </div>
      <div class="flex items-center space-x-2">
        <span class="text-zinc-400">按「⌘+S」打开保存对话框</span>
        <span>·</span>
        <span class="text-zinc-400">打字自动弹出 quant 代码补全</span>
      </div>
    </div>

    <!-- 4. API 速查抽屉 Modal -->
    <div
      v-if="showCheatSheet"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-2xl bg-[#18191e] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        <!-- 弹窗头部 -->
        <div class="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
          <div class="flex items-center space-x-2">
            <span class="text-base">📖</span>
            <h3 class="text-sm font-bold text-white">量化 API 与内置指标速查</h3>
          </div>
          <button
            @click="showCheatSheet = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <!-- 弹窗内容：分类展示常用 API -->
        <div class="flex-1 overflow-y-auto p-5 space-y-5 text-xs">
          <div v-for="(cat, idx) in apiCheatSheet" :key="idx" class="space-y-2.5">
            <div class="font-bold text-zinc-300 text-xs flex items-center space-x-1.5 border-b border-white/[0.06] pb-1">
              <span>{{ cat.category }}</span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div
                v-for="(item, i) in cat.items"
                :key="i"
                class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-amber-500/40 transition-colors space-y-1.5"
              >
                <div class="flex items-center justify-between">
                  <span class="font-mono font-bold text-amber-300 text-[11px]">{{ item.name }}</span>
                  <button
                    @click="insertSnippet(item.code)"
                    class="px-2 py-0.5 rounded bg-amber-500/15 hover:bg-amber-500/30 text-amber-300 text-[10px] font-semibold transition-all cursor-pointer"
                  >
                    + 插入光标处
                  </button>
                </div>
                <div class="text-[11px] text-zinc-400 leading-tight">{{ item.desc }}</div>
                <pre class="bg-black/40 p-1.5 rounded text-[10px] font-mono text-zinc-300 overflow-x-auto select-all">{{ item.code }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. 保存策略弹窗 Modal (支持新增或修改原策略) -->
    <div
      v-if="showSaveModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#18191e] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2">
            <span class="text-amber-400 text-base">💾</span>
            <h3 class="text-sm font-bold text-white">保存策略至云端策略库</h3>
          </div>
          <button
            @click="showSaveModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <div class="space-y-3.5 text-xs">
          <!-- 保存模式切换（仅在当前正在编辑已有云端策略时展示） -->
          <div v-if="canUpdateCurrent" class="space-y-1.5">
            <label class="block text-zinc-400 font-medium">请选择保存目标：</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                type="button"
                @click="setSaveMode('update')"
                :class="saveMode === 'update' ? 'bg-amber-500/15 border-amber-500/60 text-white shadow-sm ring-1 ring-amber-500/30' : 'bg-black/30 border-white/[0.08] text-zinc-400 hover:text-zinc-200'"
                class="p-2.5 rounded-xl border text-left cursor-pointer transition-all flex flex-col justify-between"
              >
                <div class="flex items-center space-x-1.5 font-bold text-xs text-amber-300">
                  <span>📝 修改覆盖原策略</span>
                </div>
                <p class="text-[10px] text-zinc-400 mt-1 truncate">直接更新当前「{{ strategyStore.activeStrategyName }}」</p>
              </button>

              <button
                type="button"
                @click="setSaveMode('create')"
                :class="saveMode === 'create' ? 'bg-emerald-500/15 border-emerald-500/60 text-white shadow-sm ring-1 ring-emerald-500/30' : 'bg-black/30 border-white/[0.08] text-zinc-400 hover:text-zinc-200'"
                class="p-2.5 rounded-xl border text-left cursor-pointer transition-all flex flex-col justify-between"
              >
                <div class="flex items-center space-x-1.5 font-bold text-xs text-emerald-400">
                  <span>➕ 另存为全新策略</span>
                </div>
                <p class="text-[10px] text-zinc-400 mt-1">创建一份独立新档案，原策略不变</p>
              </button>
            </div>
          </div>

          <!-- 策略名称输入 -->
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">策略名称</label>
            <input
              v-model="saveNameInput"
              type="text"
              placeholder="如: 沪深300双均线金叉策略"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/50"
            />
          </div>

          <!-- 策略描述输入 -->
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">策略简述 (可选)</label>
            <textarea
              v-model="saveDescInput"
              placeholder="如: 适用于大盘宽基 ETF 震荡与趋势行情的自动仓位调节策略"
              rows="2"
              class="w-full resize-none bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/50"
            ></textarea>
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button
            @click="showSaveModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmSaveStrategy"
            :disabled="strategyStore.isSavingStrategy"
            class="px-4 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-50 text-white font-bold text-xs shadow-lg shadow-red-500/20 transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>{{ strategyStore.isSavingStrategy ? '正在保存...' : (saveMode === 'update' ? '确认更新原策略' : '确认新建并保存') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* CodeMirror 智能补全列表排版与高亮对齐系统 */
.cm-tooltip.cm-tooltip-autocomplete {
  background: rgba(22, 23, 29, 0.98) !important;
  backdrop-filter: blur(24px) !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
  border-radius: 10px !important;
  box-shadow: 0 20px 48px -8px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
  min-width: 420px !important;
  max-width: 580px !important;
  overflow: visible !important;
  padding: 4px !important;
  z-index: 10000 !important;
}

.cm-tooltip-autocomplete > ul {
  max-height: 280px !important;
  padding: 2px !important;
  margin: 0 !important;
  list-style: none !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
  font-size: 12px !important;
}

.cm-tooltip-autocomplete > ul > li {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  height: 28px !important;
  line-height: 28px !important;
  padding: 0 10px !important;
  border-radius: 6px !important;
  margin: 1px 0 !important;
  color: #d1d5db !important;
  cursor: pointer !important;
  transition: all 0.08s ease !important;
}

.cm-tooltip-autocomplete > ul > li:hover {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #ffffff !important;
}

.cm-tooltip-autocomplete > ul > li[aria-selected="true"] {
  background: linear-gradient(90deg, rgba(255, 95, 61, 0.28) 0%, rgba(255, 95, 61, 0.12) 100%) !important;
  border-left: 2.5px solid #ff5f3d !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  box-shadow: inset 0 0 0 1px rgba(255, 95, 61, 0.2) !important;
}

.cm-completionIcon {
  width: 18px !important;
  height: 18px !important;
  margin-right: 8px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  font-size: 10px !important;
  font-weight: 700 !important;
  border-radius: 4px !important;
  background: rgba(255, 255, 255, 0.06) !important;
  color: #94a3b8 !important;
  flex-shrink: 0 !important;
}

.cm-completionIcon-property {
  color: #38bdf8 !important;
  background: rgba(56, 189, 248, 0.15) !important;
}

.cm-completionIcon-method,
.cm-completionIcon-function {
  color: #c084fc !important;
  background: rgba(192, 132, 252, 0.15) !important;
}

.cm-completionIcon-keyword {
  color: #fbbf24 !important;
  background: rgba(251, 191, 36, 0.15) !important;
}

.cm-completionIcon-variable {
  color: #34d399 !important;
  background: rgba(52, 211, 153, 0.15) !important;
}

.cm-completionLabel {
  font-weight: 500 !important;
  color: #f3f4f6 !important;
  margin-right: 12px !important;
  flex-shrink: 0 !important;
}

.cm-completionMatchedText {
  text-decoration: none !important;
  color: #ff5f3d !important;
  font-weight: 700 !important;
  background: rgba(255, 95, 61, 0.25) !important;
  border-radius: 3px !important;
  padding: 0 2px !important;
}

.cm-completionDetail {
  margin-left: auto !important;
  text-align: right !important;
  color: #9ca3af !important;
  font-size: 11px !important;
  font-style: normal !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", monospace !important;
  opacity: 0.9 !important;
  white-space: nowrap !important;
}

.cm-tooltip-autocomplete > ul > li[aria-selected="true"] .cm-completionDetail {
  color: #fed7aa !important;
  opacity: 1 !important;
  font-weight: 500 !important;
}

.cm-tooltip.cm-completionInfo {
  margin-left: 8px !important;
  background: rgba(20, 21, 27, 0.98) !important;
  backdrop-filter: blur(24px) !important;
  border: 1px solid rgba(255, 255, 255, 0.16) !important;
  border-radius: 10px !important;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.8) !important;
  padding: 10px 14px !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif !important;
  font-size: 12px !important;
  line-height: 1.6 !important;
  color: #e4e4e7 !important;
  max-width: 380px !important;
  z-index: 10001 !important;
}
</style>
