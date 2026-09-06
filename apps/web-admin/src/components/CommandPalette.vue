<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMarketStore, type SymbolItem } from '@/stores/market'
import { useStrategyStore } from '@/stores/strategy'
import { useAiStore } from '@/stores/ai'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const router = useRouter()
const marketStore = useMarketStore()
const strategyStore = useStrategyStore()
const aiStore = useAiStore()

const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const selectedIndex = ref(0)
const isSearchingSymbols = ref(false)
const listContainer = ref<HTMLDivElement | null>(null)

interface SystemCommandItem {
  id: string
  type: 'command'
  category: string
  title: string
  subtitle: string
  icon: string
  badge?: string
  action: () => void
}

interface PaletteSymbolItem {
  id: string
  type: 'symbol'
  category: string
  symbolData: SymbolItem
}

type PaletteItem = SystemCommandItem | PaletteSymbolItem

// 1. 系统核心功能指令
const systemCommands: SystemCommandItem[] = [
  {
    id: 'cmd-ai-copilot',
    type: 'command',
    category: 'AI 投研',
    title: '唤起 Alpha Copilot 智能助手',
    subtitle: '全站全局 AI 助手，自然语言推演策略、行情异动归因与代码生成',
    icon: '🤖',
    badge: '⌘J',
    action: () => aiStore.open(),
  },
  {
    id: 'cmd-backtest-cockpit',
    type: 'command',
    category: '量化回测',
    title: '呼出量化回测工作舱',
    subtitle: '事件驱动回测引擎、多因子持仓透视与毫秒级沙箱模拟撮合',
    icon: '⚡',
    badge: '⌘B',
    action: () => strategyStore.openBacktestCockpit(),
  },
  {
    id: 'nav-market',
    type: 'command',
    category: '全站导航',
    title: '市场看板',
    subtitle: '全市场大盘核心指标、宽基走势、行业热点与估值分位数',
    icon: '📊',
    badge: 'Home',
    action: () => router.push('/'),
  },
  {
    id: 'nav-strategy',
    type: 'command',
    category: '全站导航',
    title: '策略工作台 (AI + Python)',
    subtitle: '沉浸式宽屏 Python 策略代码编辑器、实时运行诊断与事件撮合',
    icon: '💻',
    badge: 'Strategy',
    action: () => router.push('/strategy'),
  },
  {
    id: 'nav-portfolio',
    type: 'command',
    category: '全站导航',
    title: '组合持仓与风控',
    subtitle: '动态多策略资产配置、收益归因与风控最大回撤监控',
    icon: '💼',
    badge: 'Portfolio',
    action: () => router.push('/portfolio'),
  },
  {
    id: 'act-reload',
    type: 'command',
    category: '操作',
    title: '刷新当前看板',
    subtitle: '重新拉取行情源数据与页面状态',
    icon: '🔄',
    badge: 'Reload',
    action: () => window.location.reload(),
  },
]

// 2. 热门宽基与核心蓝筹推荐
const POPULAR_SYMBOLS: SymbolItem[] = [
  { symbol: '510300.SH.ETF', ticker: '510300', name: '沪深300 ETF', market: 'SH', asset_type: 'ETF', pct_change: 0.85, latest_price: 3.785 },
  { symbol: '600519.SH.STK', ticker: '600519', name: '贵州茅台', market: 'SH', asset_type: 'STK', pct_change: 2.40, latest_price: 1330.0 },
  { symbol: '000001.SZ.STK', ticker: '000001', name: '平安银行', market: 'SZ', asset_type: 'STK', pct_change: 0.35, latest_price: 11.20 },
  { symbol: '300750.SZ.STK', ticker: '300750', name: '宁德时代', market: 'SZ', asset_type: 'STK', pct_change: -1.12, latest_price: 215.6 },
  { symbol: '513100.SH.ETF', ticker: '513100', name: '纳指100 ETF', market: 'SH', asset_type: 'ETF', pct_change: 1.15, latest_price: 1.820 },
  { symbol: '600030.SH.STK', ticker: '600030', name: '中信证券', market: 'SH', asset_type: 'STK', pct_change: 1.68, latest_price: 27.50 },
]

// 3. 动态标的查询与结果
const searchSymbolResults = ref<SymbolItem[]>([])

let searchTimer: any = null
watch(query, (val) => {
  selectedIndex.value = 0
  const q = val.trim()
  if (!q) {
    searchSymbolResults.value = []
    isSearchingSymbols.value = false
    return
  }

  clearTimeout(searchTimer)
  isSearchingSymbols.value = true
  searchTimer = setTimeout(async () => {
    try {
      const results = await marketStore.searchSymbols(q, 'all', 12)
      searchSymbolResults.value = results || []
    } catch {
      searchSymbolResults.value = []
    } finally {
      isSearchingSymbols.value = false
    }
  }, 120)
})

// 4. 计算当前展示的全部候选项 (标的 + 匹配的系统指令)
const unifiedItems = computed<PaletteItem[]>(() => {
  const q = query.value.trim().toLowerCase()

  if (!q) {
    // 空输入：展示系统快捷指令 + 最近搜索 / 热门推荐标的
    const list: PaletteItem[] = [...systemCommands]

    const pool = marketStore.recentSearches.length > 0
      ? marketStore.recentSearches.slice(0, 5)
      : POPULAR_SYMBOLS

    const categoryLabel = marketStore.recentSearches.length > 0 ? '最近浏览' : '热门标的'
    pool.forEach((s) => {
      list.push({
        id: `sym-${s.symbol}`,
        type: 'symbol',
        category: categoryLabel,
        symbolData: s,
      })
    })

    return list
  }

  // 有输入：先放搜索出的标的，再放匹配的系统指令
  const list: PaletteItem[] = []

  // 4.1 标的结果
  searchSymbolResults.value.forEach((s) => {
    list.push({
      id: `sym-${s.symbol}`,
      type: 'symbol',
      category: s.asset_type === 'ETF' ? 'ETF 基金' : (s.market === 'SH' ? '沪市 A 股' : (s.market === 'SZ' ? '深市 A 股' : '市场标的')),
      symbolData: s,
    })
  })

  // 4.2 过滤系统指令
  const matchedCmds = systemCommands.filter((c) =>
    c.title.toLowerCase().includes(q) ||
    c.subtitle.toLowerCase().includes(q) ||
    c.category.toLowerCase().includes(q)
  )
  list.push(...matchedCmds)

  return list
})

// 5. 选中或回车触发动作
function executeItem(item: PaletteItem) {
  if (item.type === 'command') {
    item.action()
    emit('close')
    return
  }

  if (item.type === 'symbol') {
    marketStore.addRecentSearch(item.symbolData)
    router.push(`/symbol/${encodeURIComponent(item.symbolData.symbol)}`)
    emit('close')
  }
}

// 6. 快捷对选中标的发起量化回测
function runBacktestForSymbol(item: SymbolItem, e?: Event) {
  if (e) e.stopPropagation()
  marketStore.addRecentSearch(item)
  strategyStore.openBacktestCockpit({
    symbol: item.symbol,
  })
  emit('close')
}

// 7. 弹窗显示状态控制与焦点
watch(
  () => props.show,
  (newVal) => {
    if (newVal) {
      selectedIndex.value = 0
      query.value = ''
      searchSymbolResults.value = []
      nextTick(() => {
        searchInput.value?.focus()
      })
    }
  }
)

// 8. 键盘控制
function onKeyDown(e: KeyboardEvent) {
  if (!props.show) return

  const total = unifiedItems.value.length

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (total > 0) {
      selectedIndex.value = (selectedIndex.value + 1) % total
      scrollToActiveItem()
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (total > 0) {
      selectedIndex.value = (selectedIndex.value - 1 + total) % total
      scrollToActiveItem()
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = unifiedItems.value[selectedIndex.value]
    if (item) {
      executeItem(item)
    }
  } else if ((e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === 'b' || e.code === 'KeyB')) {
    // 快捷键 ⌘+B：若当前选中为标的，直接呼出回测工作舱！
    const item = unifiedItems.value[selectedIndex.value]
    if (item && item.type === 'symbol') {
      e.preventDefault()
      runBacktestForSymbol(item.symbolData)
    }
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  }
}

function scrollToActiveItem() {
  nextTick(() => {
    if (!listContainer.value) return
    const activeEl = listContainer.value.querySelector('.item-active') as HTMLElement
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<template>
  <Teleport to="body">
    <transition name="fade">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-black/65 backdrop-blur-md transition-all duration-200"
        @click.self="emit('close')"
      >
        <div
          class="w-full max-w-2xl bg-[#121216]/95 border border-white/[0.14] rounded-2xl shadow-2xl shadow-black/80 overflow-hidden flex flex-col backdrop-filter backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-150"
        >
          <!-- 1. 搜索输入框主条 -->
          <div class="flex items-center px-4 py-3.5 border-b border-white/[0.08] relative">
            <span class="text-zinc-400 mr-3 text-base">🔍</span>
            <input
              ref="searchInput"
              v-model="query"
              type="text"
              placeholder="输入股票代码、拼音、名称或系统指令 (如 600519、GZMT、AI助手、回测)..."
              class="w-full bg-transparent text-sm text-white placeholder-zinc-500 focus:outline-none font-sans"
            />

            <!-- 搜索加载中指示 -->
            <div v-if="isSearchingSymbols" class="flex items-center space-x-1 mr-2">
              <span class="w-1.5 h-1.5 rounded-full bg-red-400 animate-ping"></span>
              <span class="text-[10px] text-zinc-400 font-mono">检索中</span>
            </div>

            <!-- 清空按钮 -->
            <button
              v-if="query"
              @click="query = ''; searchInput?.focus()"
              class="text-zinc-500 hover:text-zinc-300 text-xs px-1.5 py-0.5 mr-1 cursor-pointer transition-colors"
              title="清空搜索"
            >
              ✕
            </button>

            <button
              @click="emit('close')"
              class="px-2 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.1] text-[10px] text-zinc-400 font-mono hover:text-white cursor-pointer ml-1"
            >
              ESC
            </button>
          </div>

          <!-- 2. 搜索结果与快捷指令列表 -->
          <div
            ref="listContainer"
            class="max-h-[420px] overflow-y-auto p-2 space-y-1 select-none"
          >
            <!-- 2.1 无结果提示 -->
            <div
              v-if="unifiedItems.length === 0 && !isSearchingSymbols"
              class="py-12 text-center text-xs text-zinc-400 flex flex-col items-center space-y-2"
            >
              <span class="text-2xl opacity-60">🔎</span>
              <span class="text-zinc-300 font-medium">未找到与 "{{ query }}" 匹配的标的或指令</span>
              <span class="text-[11px] text-zinc-500 font-mono">支持输入股票代码 (如 600519)、拼音缩写 (如 GZMT) 或功能指令 (如 AI、回测)</span>
            </div>

            <!-- 2.2 项目列表 -->
            <div
              v-for="(item, idx) in unifiedItems"
              :key="item.id"
              @click="executeItem(item)"
              @mouseenter="selectedIndex = idx"
              class="group flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all text-xs border border-transparent"
              :class="[
                selectedIndex === idx
                  ? 'item-active bg-white/[0.08] border-white/[0.1] text-white shadow-sm'
                  : 'text-zinc-300 hover:bg-white/[0.04]'
              ]"
            >
              <!-- A. 标的资产项渲染 -->
              <template v-if="item.type === 'symbol'">
                <div class="flex items-center space-x-3 overflow-hidden min-w-0">
                  <span
                    class="px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0"
                    :class="[
                      item.symbolData.asset_type === 'ETF'
                        ? 'bg-purple-500/15 text-purple-300 border border-purple-500/30'
                        : 'bg-red-500/10 text-red-400 border border-red-500/20'
                    ]"
                  >
                    {{ item.category }}
                  </span>

                  <div class="flex flex-col min-w-0 truncate">
                    <div class="flex items-center space-x-2">
                      <span class="font-bold text-zinc-100 group-hover:text-white truncate">
                        {{ item.symbolData.name }}
                      </span>
                      <span class="text-[11px] font-mono text-zinc-400">
                        {{ item.symbolData.ticker || item.symbolData.symbol }}
                      </span>
                    </div>
                  </div>
                </div>

                <!-- 标的最新价与涨跌幅 + 快捷回测动作 -->
                <div class="flex items-center space-x-2.5 shrink-0 ml-2">
                  <div
                    v-if="item.symbolData.latest_price != null"
                    class="text-right font-mono text-[11px] flex items-center space-x-1.5"
                  >
                    <span class="text-zinc-300">
                      ¥{{ Number(item.symbolData.latest_price).toFixed(2) }}
                    </span>
                    <span
                      v-if="item.symbolData.pct_change != null"
                      class="px-1.5 py-0.2 rounded text-[10px] font-bold"
                      :class="[
                        Number(item.symbolData.pct_change) > 0
                          ? 'bg-red-500/15 text-red-400'
                          : Number(item.symbolData.pct_change) < 0
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'bg-white/[0.06] text-zinc-400'
                      ]"
                    >
                      {{ Number(item.symbolData.pct_change) > 0 ? '+' : '' }}{{ Number(item.symbolData.pct_change).toFixed(2) }}%
                    </span>
                  </div>

                  <!-- 快捷回测小按钮 -->
                  <button
                    @click.stop="runBacktestForSymbol(item.symbolData, $event)"
                    class="opacity-0 group-hover:opacity-100 hover:scale-105 px-2 py-0.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-[10px] flex items-center space-x-1 transition-all cursor-pointer shadow-xs"
                    title="立即载入此标的并呼出量化回测工作舱 (⌘+B)"
                  >
                    <span>⚡</span>
                    <span>回测</span>
                  </button>

                  <span
                    v-if="selectedIndex === idx"
                    class="px-1.5 py-0.5 rounded bg-white/[0.1] text-[10px] text-zinc-300 font-mono"
                  >
                    ↵
                  </span>
                </div>
              </template>

              <!-- B. 系统功能与动作渲染 -->
              <template v-else>
                <div class="flex items-center space-x-3 overflow-hidden min-w-0">
                  <div class="w-6 h-6 rounded-lg bg-white/[0.06] border border-white/[0.1] flex items-center justify-center text-sm shrink-0">
                    {{ item.icon }}
                  </div>
                  <div class="flex flex-col min-w-0 truncate">
                    <span class="font-medium text-zinc-200 group-hover:text-white truncate">
                      {{ item.title }}
                    </span>
                    <span class="text-[11px] text-zinc-400 truncate">
                      {{ item.subtitle }}
                    </span>
                  </div>
                </div>

                <div class="flex items-center space-x-2 shrink-0 ml-2">
                  <span
                    class="px-1.5 py-0.5 rounded text-[10px] font-mono"
                    :class="[
                      item.badge?.includes('⌘')
                        ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold'
                        : 'bg-white/[0.06] text-zinc-400'
                    ]"
                  >
                    {{ item.badge }}
                  </span>
                  <span
                    v-if="selectedIndex === idx"
                    class="px-1.5 py-0.5 rounded bg-white/[0.1] text-[10px] text-zinc-300 font-mono"
                  >
                    ↵ Enter
                  </span>
                </div>
              </template>
            </div>
          </div>

          <!-- 3. 底部快捷键提示栏 -->
          <div class="px-4 py-2.5 border-t border-white/[0.06] bg-black/40 flex items-center justify-between text-[11px] text-zinc-400">
            <div class="flex items-center space-x-3">
              <span class="flex items-center space-x-1">
                <kbd class="px-1.5 py-0.2 rounded bg-white/[0.08] text-[9px] font-mono text-zinc-300">↑</kbd>
                <kbd class="px-1.5 py-0.2 rounded bg-white/[0.08] text-[9px] font-mono text-zinc-300">↓</kbd>
                <span>移动高亮</span>
              </span>
              <span class="flex items-center space-x-1">
                <kbd class="px-1.5 py-0.2 rounded bg-white/[0.08] text-[9px] font-mono text-zinc-300">↵</kbd>
                <span>打开行情详情</span>
              </span>
              <span class="hidden sm:flex items-center space-x-1">
                <kbd class="px-1.5 py-0.2 rounded bg-white/[0.08] text-[9px] font-mono text-zinc-300">⌘B</kbd>
                <span>一键载入回测</span>
              </span>
            </div>

            <div class="flex items-center space-x-2 font-mono text-[10px] text-zinc-500">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
              <span>Raycast Omnibar</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
