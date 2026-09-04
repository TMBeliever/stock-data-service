<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { useStrategyStore, STRATEGY_TEMPLATES } from '@/stores/strategy'

const strategyStore = useStrategyStore()

const extensions = [python(), oneDark]

const showCheatSheet = ref(false)

const lineCount = computed(() => {
  return strategyStore.code.split('\n').length
})

const charCount = computed(() => {
  return strategyStore.code.length
})

// 常用 API 片段速查表
const apiCheatSheet = [
  {
    category: '📊 常用技术指标函数 (内置直接可用)',
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
      { name: 'self.get_position(symbol)', desc: '获取当前标的持仓对象', code: 'pos = self.get_position(bar.symbol)\n# 属性: pos.quantity, pos.available_quantity, pos.avg_cost' },
      { name: 'self.context.portfolio.cash', desc: '当前账户可用剩余现金 (CNY)', code: 'avail_cash = self.context.portfolio.cash' },
    ],
  },
]

function insertSnippet(code: string) {
  strategyStore.code += `\n        # API 速查插入\n        ${code}\n`
  showCheatSheet.value = false
}

function handleTemplateChange(e: Event) {
  const target = e.target as HTMLSelectElement
  if (target && target.value) {
    strategyStore.applyTemplate(target.value)
  }
}

function handleResetTemplate() {
  if (confirm('确定要重置为当前选中模板的初始代码吗？未保存的修改将被覆盖。')) {
    strategyStore.applyTemplate(strategyStore.selectedTemplate)
  }
}

function copyCode() {
  navigator.clipboard.writeText(strategyStore.code)
}

function handleKeyDown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    strategyStore.runBacktest()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl relative">
    <!-- 1. 顶部操作栏 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-2">
      <!-- 左侧：文件名与模板选择器 -->
      <div class="flex items-center space-x-2.5">
        <div class="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono text-zinc-300">
          <span class="text-amber-400">🐍</span>
          <span class="font-semibold text-white">custom_strategy.py</span>
        </div>

        <!-- 预设模板选择器 -->
        <div class="flex items-center space-x-1.5">
          <span class="text-[11px] text-zinc-400">预设模板:</span>
          <select
            :value="strategyStore.selectedTemplate"
            @change="handleTemplateChange"
            class="bg-black/50 border border-white/[0.1] rounded-lg px-2.5 py-1 text-xs text-zinc-200 hover:text-white focus:outline-none focus:border-amber-500/50 cursor-pointer"
          >
            <option v-for="(tpl, key) in STRATEGY_TEMPLATES" :key="key" :value="key">
              {{ tpl.name }}
            </option>
          </select>
        </div>
      </div>

      <!-- 右侧：API速查、重置、复制与运行回测按钮 -->
      <div class="flex items-center space-x-2">
        <!-- API 文档与指标速查按钮 -->
        <button
          @click="showCheatSheet = !showCheatSheet"
          title="量化 API 与内置指标速查手册"
          class="px-2.5 py-1 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-300 hover:text-amber-200 transition-all text-xs flex items-center space-x-1 cursor-pointer"
        >
          <span>📖</span>
          <span class="font-semibold text-[11px]">API 速查</span>
        </button>

        <button
          @click="handleResetTemplate"
          title="重置为模板初始代码"
          class="p-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-zinc-400 hover:text-white transition-all text-xs cursor-pointer"
        >
          🔄
        </button>

        <button
          @click="copyCode"
          title="复制当前源码"
          class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-zinc-400 hover:text-white transition-all text-xs flex items-center space-x-1 cursor-pointer"
        >
          <span>📋</span>
          <span class="hidden sm:inline text-[11px]">复制</span>
        </button>

        <!-- 运行回测主按钮 -->
        <button
          @click="strategyStore.runBacktest()"
          :disabled="strategyStore.isBacktesting"
          class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-red-500 via-rose-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1.5 shadow-lg shadow-red-500/20 transition-all cursor-pointer group"
        >
          <span v-if="strategyStore.isBacktesting" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span v-else class="text-sm group-hover:scale-110 transition-transform">▶</span>
          <span>{{ strategyStore.isBacktesting ? '沙箱撮合中...' : '运行回测' }}</span>
          <span class="hidden md:inline text-[10px] opacity-70 font-mono bg-black/20 px-1 py-0.5 rounded">⌘↵</span>
        </button>
      </div>
    </div>

    <!-- 2. CodeMirror 编辑器主体 -->
    <div class="flex-1 relative overflow-hidden bg-[#0d0e11] font-mono text-[13px]">
      <Codemirror
        v-model="strategyStore.code"
        :extensions="extensions"
        :autofocus="true"
        :indent-with-tab="true"
        :tab-size="4"
        style="height: 100%; width: 100%;"
      />

      <!-- 4. API 速查浮动抽屉 -->
      <div
        v-if="showCheatSheet"
        class="absolute inset-0 z-30 bg-[#121316]/95 backdrop-blur-md p-5 flex flex-col space-y-4 animate-fadeIn overflow-y-auto"
      >
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2">
            <span class="text-lg">📖</span>
            <div>
              <h3 class="text-sm font-bold text-white">QuantScope 策略 API 与内置指标速查手册</h3>
              <p class="text-[11px] text-zinc-400">所有指标函数与上下文助手均已注入沙箱，直接调用即可使用</p>
            </div>
          </div>
          <button
            @click="showCheatSheet = false"
            class="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white flex items-center justify-center text-sm cursor-pointer"
          >
            ✕
          </button>
        </div>

        <div class="space-y-4 text-xs font-mono">
          <div
            v-for="(cat, cIdx) in apiCheatSheet"
            :key="cIdx"
            class="space-y-2 p-3.5 rounded-xl bg-white/[0.02] border border-white/[0.06]"
          >
            <div class="text-xs font-bold text-amber-300 font-sans flex items-center space-x-1.5">
              <span>{{ cat.category }}</span>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div
                v-for="(item, iIdx) in cat.items"
                :key="iIdx"
                class="p-2.5 rounded-lg bg-black/40 border border-white/[0.04] flex flex-col justify-between space-y-1.5"
              >
                <div>
                  <div class="text-zinc-200 font-semibold text-[11px]">{{ item.name }}</div>
                  <div class="text-zinc-500 text-[10px] font-sans">{{ item.desc }}</div>
                </div>
                <div class="flex items-center justify-between pt-1 border-t border-white/[0.04]">
                  <code class="text-[10px] text-red-300 truncate max-w-[260px]">{{ item.code }}</code>
                  <button
                    @click="insertSnippet(item.code)"
                    class="px-2 py-0.5 rounded bg-white/[0.06] hover:bg-white/[0.12] text-zinc-300 hover:text-white text-[10px] cursor-pointer"
                  >
                    + 插入
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 底部状态栏 -->
    <div class="px-3 py-1.5 border-t border-white/[0.08] bg-white/[0.02] flex items-center justify-between text-[11px] text-zinc-400 font-mono">
      <div class="flex items-center space-x-3">
        <span class="flex items-center space-x-1 text-emerald-400">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          <span>AST 安全沙箱防护开启</span>
        </span>
        <span>·</span>
        <span>Python 3.12</span>
      </div>

      <div class="flex items-center space-x-3 text-zinc-500">
        <span>{{ lineCount }} 行</span>
        <span>{{ charCount }} 字符</span>
        <span>UTF-8</span>
      </div>
    </div>
  </div>
</template>

<style>
/* 针对 CodeMirror 深度定制暗黑透明风格与行号居中对齐 */
.cm-editor {
  height: 100% !important;
  background-color: #0d0e11 !important;
}
.cm-scroller {
  font-family: 'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace !important;
  line-height: 1.6 !important;
}
.cm-gutters {
  background-color: #0d0e11 !important;
  border-right: 1px solid rgba(255, 255, 255, 0.06) !important;
  color: rgba(255, 255, 255, 0.25) !important;
}
</style>
