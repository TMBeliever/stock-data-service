<script setup lang="ts">
import { ref, computed, shallowRef, onMounted, onUnmounted, watch } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { autocompletion, type CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import type { EditorView } from '@codemirror/view'
import { useStrategyStore, type UserStrategyItem } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const strategyStore = useStrategyStore()
const authStore = useAuthStore()

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

  // A. 匹配 self.context. 或 context.
  if (/self\.context\.\w*$/.test(lineText) || /(^|\s)context\.\w*$/.test(lineText)) {
    const match = lineText.match(/(?:self\.)?context\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      options: [
        { label: 'get_closes', type: 'method', detail: '(symbol, n=50)', info: '获取最近 N 根收盘价列表 (List[float])' },
        { label: 'get_highs', type: 'method', detail: '(symbol, n=50)', info: '获取最近 N 根最高价列表 (List[float])' },
        { label: 'get_lows', type: 'method', detail: '(symbol, n=50)', info: '获取最近 N 根最低价列表 (List[float])' },
        { label: 'get_volumes', type: 'method', detail: '(symbol, n=50)', info: '获取最近 N 根成交量列表 (List[float])' },
        { label: 'get_opens', type: 'method', detail: '(symbol, n=50)', info: '获取最近 N 根开盘价列表 (List[float])' },
        { label: 'portfolio', type: 'property', detail: 'Portfolio', info: '账户组合对象 (包含 cash, total_equity, total_market_value)' },
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
      options: [
        { label: 'order_target_percent', type: 'method', detail: '(symbol, pct, reason="")', info: '【核心调仓】调整目标仓位占比 (0.0~1.0)' },
        { label: 'close_position', type: 'method', detail: '(symbol, reason="")', info: '【一键平仓】全仓清空该标的持仓' },
        { label: 'buy', type: 'method', detail: '(symbol, quantity, price=None, reason="")', info: '【按手买入】买入指定股数' },
        { label: 'sell', type: 'method', detail: '(symbol, quantity, price=None, reason="")', info: '【按手卖出】卖出指定股数' },
        { label: 'get_position', type: 'method', detail: '(symbol)', info: '【持仓查询】获取 Position (quantity, avg_cost, available_quantity)' },
        { label: 'context', type: 'property', detail: 'StrategyContext', info: '【上下文】获取历史行情序列与账户信息' },
      ],
      validFor: /^\w*$/,
    }
  }

  // C. 匹配 bar.
  if (/bar\.\w*$/.test(lineText)) {
    const match = lineText.match(/bar\.(\w*)$/)
    const from = context.pos - (match ? match[1].length : 0)
    return {
      from,
      options: [
        { label: 'close', type: 'property', detail: 'float', info: '当前 K 线切片最新收盘价' },
        { label: 'open', type: 'property', detail: 'float', info: '当前 K 线开盘价' },
        { label: 'high', type: 'property', detail: 'float', info: '当前 K 线最高价' },
        { label: 'low', type: 'property', detail: 'float', info: '当前 K 线最低价' },
        { label: 'volume', type: 'property', detail: 'float', info: '当前 K 线成交量' },
        { label: 'symbol', type: 'property', detail: 'str', info: '当前标的代码 (如 510300.SH.ETF)' },
        { label: 'date_str', type: 'property', detail: 'str', info: '当前日期字符串 (YYYY-MM-DD)' },
        { label: 'amount', type: 'property', detail: 'float', info: '当前成交金额' },
        { label: 'timestamp', type: 'property', detail: 'int', info: '当前 UTC 毫秒时间戳' },
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
      options: [
        { label: 'quantity', type: 'property', detail: 'float', info: '当前持仓总股数' },
        { label: 'available_quantity', type: 'property', detail: 'float', info: 'A 股 T+1 可卖出股数' },
        { label: 'avg_cost', type: 'property', detail: 'float', info: '持仓均价成本' },
        { label: 'current_price', type: 'property', detail: 'float', info: '最新市价' },
        { label: 'market_value', type: 'property', detail: 'float', info: '持仓总市值' },
      ],
      validFor: /^\w*$/,
    }
  }

  // E. 全局通用指标函数智能提示
  const word = context.matchBefore(/\w+/)
  if (!word || (word.from === word.to && !context.explicit)) return null

  return {
    from: word.from,
    options: [
      { label: 'sma', type: 'function', detail: '(prices, period)', info: '简单移动平均线: sma(closes, 20)' },
      { label: 'ema', type: 'function', detail: '(prices, period)', info: '指数移动平均线: ema(closes, 12)' },
      { label: 'rsi', type: 'function', detail: '(prices, period=14)', info: '相对强弱指标 (0~100): rsi(closes, 14)' },
      { label: 'macd', type: 'function', detail: '(prices, 12, 26, 9)', info: 'MACD 指标: dif, dea, hist = macd(closes, 12, 26, 9)' },
      { label: 'bollinger_bands', type: 'function', detail: '(prices, 20, 2.0)', info: '布林带: upper, mid, lower = bollinger_bands(closes, 20, 2.0)' },
      { label: 'atr', type: 'function', detail: '(highs, lows, closes, 14)', info: '真实波幅均值: atr_val = atr(highs, lows, closes, 14)' },
      { label: 'self', type: 'keyword', detail: 'BaseStrategy 策略实例' },
      { label: 'bar', type: 'variable', detail: 'Bar 行情切片' },
      { label: 'order_target_percent', type: 'method', detail: 'self.order_target_percent(symbol, pct)' },
      { label: 'close_position', type: 'method', detail: 'self.close_position(symbol)' },
    ],
  }
}

const extensions = [
  python(),
  oneDark,
  autocompletion({
    override: [quantCompletionSource],
    activateOnTyping: true,
  }),
]

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

// 常用 API 片段速查表
const apiCheatSheet = [
  {
    category: '📊 常用技术指标函数 (沙箱内置，直接调用)',
    items: [
      { name: 'sma(prices, period)', desc: '简单移动平均 (SMA)', code: 'ma20 = sma(closes, 20)' },
      { name: 'ema(prices, period)', desc: '指数移动平均 (EMA)', code: 'ema12 = ema(closes, 12)' },
      { name: 'rsi(prices, period=14)', desc: '相对强弱指标 (RSI 0~100)', code: 'rsi_val = rsi(closes, 14)' },
      { name: 'macd(prices, 12, 26, 9)', desc: 'MACD (返回 DIF, DEA, 柱)', code: 'dif, dea, hist = macd(closes, 12, 26, 9)' },
      { name: 'bollinger_bands(prices, 20, 2.0)', desc: '布林带 (返回 上轨, 中轨, 下轨)', code: 'upper, mid, lower = bollinger_bands(closes, 20, 2.0)' },
      { name: 'atr(highs, lows, closes, 14)', desc: '真实波幅均值 (ATR)', code: 'atr_val = atr(highs, lows, closes, 14)' },
    ],
  },
  {
    category: '📈 行情切片与历史数据获取 (self.context)',
    items: [
      { name: 'self.context.get_closes(symbol, n)', desc: '获取最近 N 根收盘价列表 (List[float])', code: 'closes = self.context.get_closes(bar.symbol, n=50)' },
      { name: 'self.context.get_highs(symbol, n)', desc: '获取最近 N 根最高价列表 (List[float])', code: 'highs = self.context.get_highs(bar.symbol, n=50)' },
      { name: 'self.context.get_lows(symbol, n)', desc: '获取最近 N 根最低价列表 (List[float])', code: 'lows = self.context.get_lows(bar.symbol, n=50)' },
      { name: 'self.context.get_volumes(symbol, n)', desc: '获取最近 N 根成交量列表 (List[float])', code: 'vols = self.context.get_volumes(bar.symbol, n=50)' },
      { name: 'bar.close / open / high / low / volume', desc: '当前 K 线切片原始字段', code: 'curr_price = bar.close\ncurr_vol = bar.volume' },
    ],
  },
  {
    category: '🛒 下单与仓位控制助手',
    items: [
      { name: 'self.order_target_percent(symbol, pct)', desc: '将标的调至占总资产比例 (如 0.8=80%)', code: 'self.order_target_percent(bar.symbol, 0.8, reason="建仓")' },
      { name: 'self.close_position(symbol)', desc: '将标的所有可用持仓全仓平仓', code: 'self.close_position(bar.symbol, reason="止损出场")' },
      { name: 'self.buy(symbol, qty, price=...)', desc: '指定数量买入 (A股1手=100股)', code: 'self.buy(bar.symbol, 1000, price=bar.close, reason="加仓")' },
      { name: 'self.sell(symbol, qty, price=...)', desc: '指定数量卖出', code: 'self.sell(bar.symbol, 1000, price=bar.close, reason="减仓")' },
      { name: 'self.get_position(symbol)', desc: '获取当前标的持仓对象', code: 'pos = self.get_position(bar.symbol)\n# pos.quantity, pos.available_quantity, pos.avg_cost' },
      { name: 'self.context.portfolio.cash', desc: '当前账户可用剩余现金 (CNY)', code: 'avail_cash = self.context.portfolio.cash' },
    ],
  },
]

function copyCode() {
  navigator.clipboard.writeText(strategyStore.code)
  showToast('📋 代码已复制到剪贴板')
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

        <!-- 快捷新建空白策略按钮 -->
        <button
          @click="handleCreateBlankStrategy"
          title="新建一份空白策略"
          class="px-2 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-xs text-zinc-300 hover:text-white transition-all flex items-center space-x-1 cursor-pointer"
        >
          <span>➕</span>
          <span class="hidden sm:inline">新建策略</span>
        </button>

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

      <!-- 右侧：API 速查、代码操作与运行回测 -->
      <div class="flex items-center space-x-2">
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
