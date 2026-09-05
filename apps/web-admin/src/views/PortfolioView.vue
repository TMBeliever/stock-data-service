<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useStrategyStore, PRESET_WATCHLISTS, type UserWatchlistItem, type UserHoldingItem } from '@/stores/strategy'
import { useMarketStore, type SymbolItem } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const strategyStore = useStrategyStore()
const marketStore = useMarketStore()
const authStore = useAuthStore()

const activeMainTab = ref<'watchlists' | 'holdings'>('watchlists')
const toastMsg = ref('')

// 选中的组合 (可以是预置组合或用户的自选组合)
const activeWatchlistName = ref<string>(PRESET_WATCHLISTS[0].name)
const watchlistSymbolsQuotes = ref<Record<string, SymbolItem>>({})
const isQuotesLoading = ref(false)

// 组合追加标的输入
const inputAddSymbol = ref('')

// 新建组合弹窗
const showCreateModal = ref(false)
const createNameInput = ref('')
const createDescInput = ref('')
const createSymbolsInput = ref('')

// 编辑持仓弹窗
const showAddHoldingModal = ref(false)
const newHoldingSymbol = ref('')
const newHoldingName = ref('')
const newHoldingQty = ref<number>(1000)
const newHoldingCost = ref<number>(10.0)

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2500)
}

// 获取所有可用组合列表 (包含预设与用户云端组合)
const allWatchlists = computed(() => {
  return [
    ...PRESET_WATCHLISTS.map((w) => ({ ...w, isPreset: true })),
    ...strategyStore.userWatchlists.map((w) => ({ ...w, isPreset: false })),
  ]
})

// 当前选中的组合对象
const currentWatchlist = computed(() => {
  const found = allWatchlists.value.find((w) => w.name === activeWatchlistName.value)
  return found || allWatchlists.value[0]
})

// 批量加载当前组合内标的的实时行情
async function loadWatchlistQuotes() {
  if (!currentWatchlist.value || !currentWatchlist.value.symbols.length) return
  isQuotesLoading.value = true
  try {
    const symbols = currentWatchlist.value.symbols
    // 利用 marketStore 的批量搜索拉取快照
    const res = await marketStore.searchSymbols('', 'all', 50)
    const map: Record<string, SymbolItem> = {}
    // 对每个 symbol 查询或从 search 结果映射
    for (const sym of symbols) {
      const found = res.find((r) => r.symbol === sym || r.ticker === sym.split('.')[0])
      if (found) {
        map[sym] = found
      } else {
        // 单独查询一次详情补全
        const detail = await marketStore.fetchSymbolDetail(sym)
        if (detail) map[sym] = detail
      }
    }
    watchlistSymbolsQuotes.value = map
  } catch (err) {
    console.error('loadWatchlistQuotes error:', err)
  } finally {
    isQuotesLoading.value = false
  }
}

watch(
  () => activeWatchlistName.value,
  () => {
    loadWatchlistQuotes()
  }
)

onMounted(async () => {
  if (authStore.isLoggedIn) {
    await Promise.all([
      strategyStore.fetchUserWatchlists(),
      strategyStore.fetchUserHoldings(),
    ])
  }
  loadWatchlistQuotes()
})

// 切换组合
function selectWatchlist(name: string) {
  activeWatchlistName.value = name
}

// 快速向当前组合追加标的
async function handleAddSymbolToCurrent() {
  const text = inputAddSymbol.value.trim().toUpperCase()
  if (!text) return

  let sym = text
  if (/^\d{6}$/.test(sym)) {
    if (sym.startsWith('6') || sym.startsWith('5')) sym += sym.startsWith('5') ? '.SH.ETF' : '.SH.STK'
    else if (sym.startsWith('0') || sym.startsWith('3') || sym.startsWith('1')) sym += sym.startsWith('1') ? '.SZ.ETF' : '.SZ.STK'
  }

  const wl = currentWatchlist.value
  if (wl.isPreset) {
    // 预设组合不可直接覆盖服务端，自动复制为用户新组合并追加
    const newSymbols = Array.from(new Set([...wl.symbols, sym]))
    const copyName = `${wl.name} (我的副本)`
    const ok = await strategyStore.saveUserWatchlist(copyName, '基于官方模板定制', newSymbols)
    if (ok) {
      activeWatchlistName.value = copyName
      showToast(`⭐ 已复制为个人组合「${copyName}」并添加标的！`)
    }
  } else {
    // 用户自定义组合：调用追加接口
    const ok = await marketStore.addSymbolToWatchlist(wl.id!, sym)
    if (ok) {
      showToast(`✅ 已向「${wl.name}」添加标的 ${sym}`)
      loadWatchlistQuotes()
    }
  }
  inputAddSymbol.value = ''
}

// 从当前组合移除标的
async function handleRemoveSymbolFromCurrent(sym: string) {
  const wl = currentWatchlist.value
  if (wl.isPreset) {
    showToast('⚠️ 官方经典配置池为系统基准，不可直接修改。请点击「存为我的组合」进行定制！')
    return
  }
  const ok = await marketStore.removeSymbolFromWatchlist(wl.id!, sym)
  if (ok) {
    showToast(`已从「${wl.name}」移除标的 ${sym}`)
    loadWatchlistQuotes()
  }
}

// 删除自定义组合
async function handleDeleteCurrentWatchlist() {
  const wl = currentWatchlist.value
  if (wl.isPreset) return
  if (confirm(`确认删除自选组合「${wl.name}」吗？`)) {
    const ok = await strategyStore.deleteUserWatchlist(wl.id!)
    if (ok) {
      showToast(`🗑️ 已删除组合「${wl.name}」`)
      activeWatchlistName.value = PRESET_WATCHLISTS[0].name
    }
  }
}

// 确认新建组合
async function confirmCreateWatchlist() {
  if (!createNameInput.value.trim()) {
    showToast('⚠️ 请输入组合名称')
    return
  }
  const rawSymbols = createSymbolsInput.value
    .split(/[,，\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
  if (rawSymbols.length === 0) {
    rawSymbols.push('510300.SH.ETF')
  }

  const ok = await strategyStore.saveUserWatchlist(createNameInput.value.trim(), createDescInput.value.trim(), rawSymbols)
  if (ok) {
    activeWatchlistName.value = createNameInput.value.trim()
    showCreateModal.value = false
    createNameInput.value = ''
    createDescInput.value = ''
    createSymbolsInput.value = ''
    showToast('⭐ 成功创建个人自选组合！')
  }
}

// 一键唤起悬浮工作舱并以当前组合发起回测
function runBacktestWithWatchlist() {
  const symbols = currentWatchlist.value.symbols
  if (!symbols || symbols.length === 0) return
  strategyStore.openBacktestCockpit({
    symbols: [...symbols],
    mode: 'basket',
    autoRun: true,
  })
  showToast(`⚡ 已唤起回测工作舱并载入组合「${currentWatchlist.value.name}」(${symbols.length}只标的)！`)
}

// 持仓管理计算
const holdingsWithMarketData = computed(() => {
  return strategyStore.userHoldings.map((h) => {
    const quote = watchlistSymbolsQuotes.value[h.symbol] || null
    const currentPrice = quote?.latest_price || h.avg_cost
    const currentVal = (h.quantity || 0) * currentPrice
    const costVal = (h.quantity || 0) * (h.avg_cost || 0)
    const pnl = currentVal - costVal
    const pnlPct = costVal > 0 ? (pnl / costVal) * 100 : 0
    return {
      ...h,
      currentPrice,
      currentVal,
      costVal,
      pnl,
      pnlPct,
    }
  })
})

const totalHoldingCost = computed(() => {
  return holdingsWithMarketData.value.reduce((s, h) => s + h.costVal, 0)
})

const totalHoldingValue = computed(() => {
  return holdingsWithMarketData.value.reduce((s, h) => s + h.currentVal, 0)
})

const totalHoldingPnl = computed(() => {
  return totalHoldingValue.value - totalHoldingCost.value
})

const totalHoldingPnlPct = computed(() => {
  return totalHoldingCost.value > 0 ? (totalHoldingPnl.value / totalHoldingCost.value) * 100 : 0
})

// 添加一条新持仓
async function confirmAddHolding() {
  if (!newHoldingSymbol.value.trim()) {
    showToast('⚠️ 标的代码不能为空')
    return
  }
  let sym = newHoldingSymbol.value.trim().toUpperCase()
  if (/^\d{6}$/.test(sym)) {
    if (sym.startsWith('6') || sym.startsWith('5')) sym += sym.startsWith('5') ? '.SH.ETF' : '.SH.STK'
    else if (sym.startsWith('0') || sym.startsWith('3') || sym.startsWith('1')) sym += sym.startsWith('1') ? '.SZ.ETF' : '.SZ.STK'
  }

  const list = [
    ...strategyStore.userHoldings,
    {
      symbol: sym,
      name: newHoldingName.value.trim() || sym.split('.')[0],
      quantity: Number(newHoldingQty.value) || 1000,
      avg_cost: Number(newHoldingCost.value) || 10.0,
    },
  ]

  const ok = await strategyStore.saveUserHoldings(list)
  if (ok) {
    showAddHoldingModal.value = false
    newHoldingSymbol.value = ''
    newHoldingName.value = ''
    showToast('💼 已成功添加持仓品种！')
  }
}

// 删除持仓
async function removeHolding(idx: number) {
  const list = [...strategyStore.userHoldings]
  list.splice(idx, 1)
  const ok = await strategyStore.saveUserHoldings(list)
  if (ok) {
    showToast('🗑️ 已删除该条持仓记录')
  }
}

// 一键唤起悬浮工作舱并以底仓同步发起回测
function syncHoldingsToBacktest() {
  strategyStore.openBacktestCockpit({
    mode: 'holdings',
    autoRun: true,
  })
  showToast('⚡ 已唤起回测工作舱并自动同步底仓标的与总市值！')
}
</script>

<template>
  <div class="space-y-4 max-w-7xl mx-auto pb-16 animate-fadeIn">
    <!-- 1. 顶部主面板与导航切换 -->
    <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] backdrop-blur-md flex flex-col md:flex-row md:items-center justify-between gap-4">
      <div>
        <div class="flex items-center space-x-3">
          <span class="text-2xl">💼</span>
          <div>
            <h1 class="text-xl font-bold text-white tracking-tight">我的自选组合与持仓中枢</h1>
            <p class="text-xs text-zinc-400 mt-0.5">
              全市场多资产策略组合管理、行情异动追踪与实盘/模拟底仓回测中枢
            </p>
          </div>
        </div>
      </div>

      <!-- 主视图切换 Tab -->
      <div class="flex items-center space-x-1 p-1 rounded-xl bg-black/40 border border-white/[0.08]">
        <button
          @click="activeMainTab = 'watchlists'"
          :class="activeMainTab === 'watchlists' ? 'bg-white/10 text-white font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-4 py-1.5 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>⭐</span>
          <span>自选股票池与组合 ({{ allWatchlists.length }})</span>
        </button>
        <button
          @click="activeMainTab = 'holdings'"
          :class="activeMainTab === 'holdings' ? 'bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border border-emerald-500/30 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-4 py-1.5 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>💼</span>
          <span>真实/模拟底仓资产 ({{ strategyStore.userHoldings.length }})</span>
        </button>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- 2. 主视图 A: 自选股票池与策略组合 (Watchlists) -->
    <!-- ============================================================== -->
    <div v-if="activeMainTab === 'watchlists'" class="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
      <!-- 左侧：自选组合导航列表 -->
      <div class="lg:col-span-1 p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08] space-y-4">
        <div class="flex items-center justify-between pb-2 border-b border-white/[0.06]">
          <span class="text-xs font-bold text-zinc-300 flex items-center space-x-1">
            <span>📁</span>
            <span>策略股票池列表</span>
          </span>
          <button
            @click="showCreateModal = true"
            class="px-2 py-1 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 text-[11px] font-bold border border-blue-500/30 transition-all flex items-center space-x-1 cursor-pointer"
          >
            <span>➕</span>
            <span>新建组合</span>
          </button>
        </div>

        <!-- 组合导航卡片列表 -->
        <div class="space-y-2">
          <!-- 官方经典配置池 -->
          <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider px-1 pt-1">
            🏛️ 机构经典配置组合
          </div>
          <div
            v-for="wl in PRESET_WATCHLISTS"
            :key="wl.name"
            @click="selectWatchlist(wl.name)"
            :class="activeWatchlistName === wl.name ? 'bg-blue-500/15 border-blue-500/40 text-white' : 'bg-white/[0.02] hover:bg-white/[0.04] border-white/[0.06] text-zinc-300'"
            class="p-3 rounded-xl border transition-all cursor-pointer space-y-1 group"
          >
            <div class="flex items-center justify-between">
              <span class="font-bold text-xs group-hover:text-blue-300 transition-colors">{{ wl.name }}</span>
              <span class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-white/[0.06] text-zinc-400">
                {{ wl.symbols.length }}标的
              </span>
            </div>
            <div class="text-[10px] text-zinc-500 truncate">{{ wl.description }}</div>
          </div>

          <!-- 用户自定义组合 -->
          <div class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider px-1 pt-2">
            ⭐ 我的自定义组合 ({{ strategyStore.userWatchlists.length }})
          </div>
          <div
            v-for="wl in strategyStore.userWatchlists"
            :key="wl.id"
            @click="selectWatchlist(wl.name)"
            :class="activeWatchlistName === wl.name ? 'bg-amber-500/15 border-amber-500/40 text-white' : 'bg-white/[0.02] hover:bg-white/[0.04] border-white/[0.06] text-zinc-300'"
            class="p-3 rounded-xl border transition-all cursor-pointer space-y-1 group"
          >
            <div class="flex items-center justify-between">
              <span class="font-bold text-xs group-hover:text-amber-300 transition-colors">{{ wl.name }}</span>
              <span class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-white/[0.06] text-zinc-400">
                {{ wl.symbols.length }}标的
              </span>
            </div>
            <div class="text-[10px] text-zinc-500 truncate">{{ wl.description || '自定义自选策略股票池' }}</div>
          </div>
        </div>
      </div>

      <!-- 右侧：当前组合标的大盘与行情报盘 -->
      <div class="lg:col-span-3 space-y-4">
        <!-- 组合头部工具条 -->
        <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08] flex flex-wrap items-center justify-between gap-3">
          <div>
            <div class="flex items-center space-x-2">
              <h2 class="text-base font-bold text-white">{{ currentWatchlist.name }}</h2>
              <span class="px-2 py-0.5 rounded text-[10px] font-bold" :class="currentWatchlist.isPreset ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'">
                {{ currentWatchlist.isPreset ? '官方策略池' : '个人自选池' }}
              </span>
              <span class="text-xs text-zinc-400 font-mono">共 {{ currentWatchlist.symbols.length }} 只标的</span>
            </div>
            <p class="text-xs text-zinc-400 mt-1">{{ currentWatchlist.description }}</p>
          </div>

          <!-- 右侧动作按钮 -->
          <div class="flex items-center space-x-2">
            <!-- ⚡ 以此组合发起回测 -->
            <button
              @click="runBacktestWithWatchlist"
              class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-bold text-xs shadow-lg shadow-red-500/20 flex items-center space-x-1.5 transition-all cursor-pointer"
            >
              <span>⚡</span>
              <span>以此组合发起回测</span>
            </button>

            <!-- 删除自定义组合 -->
            <button
              v-if="!currentWatchlist.isPreset"
              @click="handleDeleteCurrentWatchlist"
              class="px-2.5 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 text-xs transition-colors cursor-pointer"
              title="删除此组合"
            >
              🗑️ 删除
            </button>
          </div>
        </div>

        <!-- 组合内快捷添加标的输入栏 -->
        <div class="flex items-center space-x-2 p-3 rounded-xl bg-black/40 border border-white/[0.08]">
          <span class="text-xs text-zinc-400 font-medium shrink-0">➕ 向本组合追加标的:</span>
          <input
            v-model="inputAddSymbol"
            @keydown.enter="handleAddSymbolToCurrent"
            type="text"
            placeholder="输入股票/ETF代码 (如 600519、510300、300750，回车直接添加)..."
            class="flex-1 bg-transparent text-xs text-white placeholder-zinc-500 focus:outline-none font-mono"
          />
          <button
            @click="handleAddSymbolToCurrent"
            :disabled="!inputAddSymbol.trim()"
            class="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-bold text-xs transition-colors cursor-pointer"
          >
            添加
          </button>
        </div>

        <!-- 标的行情表格 (Quote Grid) -->
        <div class="rounded-2xl border border-white/[0.08] overflow-hidden bg-white/[0.01]">
          <div v-if="isQuotesLoading" class="p-8 text-center text-zinc-400 space-y-2">
            <div class="w-6 h-6 border-2 border-red-500/30 border-t-red-500 rounded-full animate-spin mx-auto"></div>
            <span class="text-xs font-mono">正在拉取组合内标的的实时盘口数据...</span>
          </div>

          <table v-else class="w-full text-left font-mono text-xs">
            <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08] text-[11px]">
              <tr>
                <th class="p-3">标的代码</th>
                <th class="p-3">标的名称</th>
                <th class="p-3">市场/类型</th>
                <th class="p-3 text-right">最新价</th>
                <th class="p-3 text-right">今日涨跌幅</th>
                <th class="p-3 text-right">最高 / 最低</th>
                <th class="p-3 text-right">成交额</th>
                <th class="p-3 text-center">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/[0.04]">
              <tr
                v-for="sym in currentWatchlist.symbols"
                :key="sym"
                class="hover:bg-white/[0.03] transition-colors group"
              >
                <!-- 代码 -->
                <td class="p-3">
                  <span
                    @click="router.push(`/symbol/${encodeURIComponent(sym)}`)"
                    class="font-bold text-amber-300 hover:underline cursor-pointer"
                  >
                    {{ sym }}
                  </span>
                </td>

                <!-- 名称 -->
                <td class="p-3">
                  <span
                    @click="router.push(`/symbol/${encodeURIComponent(sym)}`)"
                    class="font-sans font-semibold text-white hover:text-red-400 cursor-pointer transition-colors"
                  >
                    {{ watchlistSymbolsQuotes[sym]?.name || sym.split('.')[0] }}
                  </span>
                </td>

                <!-- 市场/类型 -->
                <td class="p-3">
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-white/[0.06] text-zinc-300 border border-white/[0.08] mr-1">
                    {{ watchlistSymbolsQuotes[sym]?.market || sym.split('.')[1] || 'SH' }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-blue-500/15 text-blue-300 border border-blue-500/20">
                    {{ watchlistSymbolsQuotes[sym]?.asset_type || (sym.includes('ETF') ? 'ETF' : 'STK') }}
                  </span>
                </td>

                <!-- 最新价 -->
                <td class="p-3 text-right font-bold text-white">
                  ¥{{ watchlistSymbolsQuotes[sym]?.latest_price !== undefined && watchlistSymbolsQuotes[sym]?.latest_price !== null ? watchlistSymbolsQuotes[sym].latest_price?.toFixed(watchlistSymbolsQuotes[sym].latest_price! > 10 ? 2 : 3) : '--' }}
                </td>

                <!-- 涨跌幅 -->
                <td class="p-3 text-right font-bold">
                  <span
                    v-if="watchlistSymbolsQuotes[sym]?.pct_change !== undefined && watchlistSymbolsQuotes[sym]?.pct_change !== null"
                    :class="watchlistSymbolsQuotes[sym].pct_change! >= 0 ? 'text-red-400' : 'text-emerald-400'"
                  >
                    {{ watchlistSymbolsQuotes[sym].pct_change! >= 0 ? '+' : '' }}{{ watchlistSymbolsQuotes[sym].pct_change }}%
                  </span>
                  <span v-else class="text-zinc-500">--</span>
                </td>

                <!-- 最高 / 最低 -->
                <td class="p-3 text-right text-zinc-400 text-[11px]">
                  <span class="text-red-400">¥{{ watchlistSymbolsQuotes[sym]?.high || '--' }}</span>
                  <span class="mx-1 text-zinc-600">/</span>
                  <span class="text-emerald-400">¥{{ watchlistSymbolsQuotes[sym]?.low || '--' }}</span>
                </td>

                <!-- 成交额 -->
                <td class="p-3 text-right text-zinc-300 text-[11px]">
                  {{ watchlistSymbolsQuotes[sym]?.amount ? (watchlistSymbolsQuotes[sym].amount! / 100000000).toFixed(2) + '亿' : '--' }}
                </td>

                <!-- 操作按钮 -->
                <td class="p-3 text-center">
                  <div class="flex items-center justify-center space-x-1.5">
                    <button
                      @click="router.push(`/symbol/${encodeURIComponent(sym)}`)"
                      class="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-colors text-[11px] cursor-pointer"
                      title="查看K线详情"
                    >
                      👁️ K线
                    </button>
                    <button
                      @click="strategyStore.openBacktestCockpit({ symbol: sym, mode: 'single', autoRun: true }); showToast(`⚡ 已唤起回测工作舱测试 ${sym}`)"
                      class="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/30 text-amber-300 transition-colors text-[11px] cursor-pointer"
                      title="以此标的立即运行回测"
                    >
                      ⚡ 回测
                    </button>
                    <button
                      @click="handleRemoveSymbolFromCurrent(sym)"
                      class="px-1.5 py-1 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-colors text-xs cursor-pointer"
                      title="从组合中移除"
                    >
                      ✕
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- 3. 主视图 B: 我的真实/模拟底仓资产 (Holdings) -->
    <!-- ============================================================== -->
    <div v-else class="space-y-4">
      <!-- 4 块资产 KPI 大卡片 -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08]">
          <div class="text-xs text-zinc-400">持仓最新总资产市值</div>
          <div class="text-2xl font-bold font-mono text-white mt-1">
            ¥{{ totalHoldingValue.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
          </div>
        </div>

        <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08]">
          <div class="text-xs text-zinc-400">持仓总投入成本</div>
          <div class="text-2xl font-bold font-mono text-zinc-300 mt-1">
            ¥{{ totalHoldingCost.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
          </div>
        </div>

        <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08]">
          <div class="text-xs text-zinc-400">浮动总盈亏 (¥ / %)</div>
          <div
            :class="totalHoldingPnl >= 0 ? 'text-red-400' : 'text-emerald-400'"
            class="text-2xl font-bold font-mono mt-1 flex items-baseline space-x-2"
          >
            <span>{{ totalHoldingPnl >= 0 ? '+' : '' }}{{ totalHoldingPnl.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</span>
            <span class="text-sm font-semibold">({{ totalHoldingPnl >= 0 ? '+' : '' }}{{ totalHoldingPnlPct.toFixed(2) }}%)</span>
          </div>
        </div>

        <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08]">
          <div class="text-xs text-zinc-400">持仓标的品种</div>
          <div class="text-2xl font-bold font-mono text-amber-300 mt-1">
            {{ strategyStore.userHoldings.length }} <span class="text-xs text-zinc-400 font-sans">只品种</span>
          </div>
        </div>
      </div>

      <!-- 持仓操作工具条 -->
      <div class="flex items-center justify-between p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08]">
        <div class="text-xs text-zinc-400 font-mono">
          <span>底仓管理状态: </span>
          <strong class="text-emerald-300">云端持久化已同步</strong>
        </div>

        <div class="flex items-center space-x-2">
          <button
            @click="showAddHoldingModal = true"
            class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] text-white border border-white/[0.08] text-xs font-semibold flex items-center space-x-1.5 transition-all cursor-pointer"
          >
            <span>➕</span>
            <span>录入新持仓</span>
          </button>
          <button
            @click="syncHoldingsToBacktest"
            class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 flex items-center space-x-1.5 transition-all cursor-pointer"
          >
            <span>⚡</span>
            <span>以此持仓同步发起组合回测</span>
          </button>
        </div>
      </div>

      <!-- 持仓资产明细表 -->
      <div class="rounded-2xl border border-white/[0.08] overflow-hidden bg-white/[0.01]">
        <table class="w-full text-left font-mono text-xs">
          <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08] text-[11px]">
            <tr>
              <th class="p-3">标的代码</th>
              <th class="p-3">标的简称</th>
              <th class="p-3 text-right">持仓股数</th>
              <th class="p-3 text-right">成本均价(元)</th>
              <th class="p-3 text-right">当前市价(元)</th>
              <th class="p-3 text-right">最新市值(元)</th>
              <th class="p-3 text-right">浮动盈亏(元/%)</th>
              <th class="p-3 text-center">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/[0.04]">
            <tr
              v-for="(h, idx) in holdingsWithMarketData"
              :key="h.symbol"
              class="hover:bg-white/[0.03] transition-colors"
            >
              <td class="p-3">
                <span
                  @click="router.push(`/symbol/${encodeURIComponent(h.symbol)}`)"
                  class="font-bold text-amber-300 hover:underline cursor-pointer"
                >
                  {{ h.symbol }}
                </span>
              </td>
              <td class="p-3 font-sans font-semibold text-white">{{ h.name }}</td>
              <td class="p-3 text-right text-zinc-200">{{ h.quantity.toLocaleString() }} 股</td>
              <td class="p-3 text-right text-zinc-400">¥{{ h.avg_cost.toFixed(3) }}</td>
              <td class="p-3 text-right font-bold text-white">¥{{ h.currentPrice.toFixed(3) }}</td>
              <td class="p-3 text-right font-bold text-zinc-100">¥{{ h.currentVal.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</td>
              <td class="p-3 text-right font-bold" :class="h.pnl >= 0 ? 'text-red-400' : 'text-emerald-400'">
                {{ h.pnl >= 0 ? '+' : '' }}{{ h.pnl.toFixed(2) }} ({{ h.pnl >= 0 ? '+' : '' }}{{ h.pnlPct.toFixed(2) }}%)
              </td>
              <td class="p-3 text-center">
                <div class="flex items-center justify-center space-x-1.5">
                  <button
                    @click="router.push(`/symbol/${encodeURIComponent(h.symbol)}`)"
                    class="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-colors text-[11px] cursor-pointer"
                  >
                    👁️ K线
                  </button>
                  <button
                    @click="strategyStore.openBacktestCockpit({ symbol: h.symbol, mode: 'single', autoRun: true }); showToast(`⚡ 已唤起回测工作舱测试 ${h.symbol}`)"
                    class="px-2 py-1 rounded bg-amber-500/15 hover:bg-amber-500/30 text-amber-300 transition-colors text-[11px] cursor-pointer"
                    title="以此持仓标的立即运行回测"
                  >
                    ⚡ 回测
                  </button>
                  <button
                    @click="removeHolding(idx)"
                    class="px-1.5 py-1 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-colors text-xs cursor-pointer"
                    title="删除持仓"
                  >
                    🗑️
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="holdingsWithMarketData.length === 0">
              <td colspan="8" class="p-8 text-center text-zinc-500">
                暂未录入底仓数据，请点击右上角「➕ 录入新持仓」
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- 弹窗 1: 新建自选组合 Modal -->
    <!-- ============================================================== -->
    <div
      v-if="showCreateModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#181920] border border-white/[0.12] rounded-2xl shadow-2xl p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <h3 class="text-sm font-bold text-white flex items-center space-x-1.5">
            <span>⭐</span>
            <span>新建策略股票池组合</span>
          </h3>
          <button @click="showCreateModal = false" class="text-zinc-400 hover:text-white cursor-pointer">✕</button>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">组合名称 <span class="text-red-400">*</span></label>
            <input
              v-model="createNameInput"
              type="text"
              placeholder="如: 新能源成长先锋 / 高分红红利组合"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>

          <div>
            <label class="block text-zinc-400 mb-1 font-medium">策略投资逻辑说明</label>
            <textarea
              v-model="createDescInput"
              rows="2"
              placeholder="简述组合选股标准与配置逻辑 (选填)"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 resize-none"
            ></textarea>
          </div>

          <div>
            <label class="block text-zinc-400 mb-1 font-medium">初始成分标的代码</label>
            <input
              v-model="createSymbolsInput"
              type="text"
              placeholder="如: 600519.SH, 300750.SZ, 510300.SH.ETF (逗号隔开)"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 font-mono"
            />
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button
            @click="showCreateModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmCreateWatchlist"
            class="px-4 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-500/20 cursor-pointer"
          >
            确认创建
          </button>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- 弹窗 2: 录入新持仓 Modal -->
    <!-- ============================================================== -->
    <div
      v-if="showAddHoldingModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#181920] border border-white/[0.12] rounded-2xl shadow-2xl p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <h3 class="text-sm font-bold text-white flex items-center space-x-1.5">
            <span>💼</span>
            <span>录入新持仓标的</span>
          </h3>
          <button @click="showAddHoldingModal = false" class="text-zinc-400 hover:text-white cursor-pointer">✕</button>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">标的代码 (如 600519.SH / 510300.SH.ETF) <span class="text-red-400">*</span></label>
            <input
              v-model="newHoldingSymbol"
              type="text"
              placeholder="600519.SH"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-emerald-500/50 uppercase font-mono"
            />
          </div>

          <div>
            <label class="block text-zinc-400 mb-1 font-medium">标的简称 (选填)</label>
            <input
              v-model="newHoldingName"
              type="text"
              placeholder="贵州茅台"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-emerald-500/50"
            />
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-zinc-400 mb-1 font-medium">持仓股数 <span class="text-red-400">*</span></label>
              <input
                v-model.number="newHoldingQty"
                type="number"
                step="100"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white font-mono focus:outline-none focus:border-emerald-500/50"
              />
            </div>
            <div>
              <label class="block text-zinc-400 mb-1 font-medium">成本均价(元) <span class="text-red-400">*</span></label>
              <input
                v-model.number="newHoldingCost"
                type="number"
                step="0.01"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white font-mono focus:outline-none focus:border-emerald-500/50"
              />
            </div>
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button
            @click="showAddHoldingModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmAddHolding"
            class="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 cursor-pointer"
          >
            确认录入
          </button>
        </div>
      </div>
    </div>

    <!-- 浮动 Toast 提示 -->
    <div
      v-if="toastMsg"
      class="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl bg-black/90 border border-white/[0.15] text-white font-bold text-xs shadow-2xl animate-fadeIn flex items-center space-x-2"
    >
      <span>{{ toastMsg }}</span>
    </div>
  </div>
</template>
