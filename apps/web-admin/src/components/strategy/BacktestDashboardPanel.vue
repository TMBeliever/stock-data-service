<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useStrategyStore, type UserBacktestItem, PRESET_WATCHLISTS } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const activeTab = ref<'chart' | 'trades' | 'history'>('chart')
const toastMsg = ref('')
const showArchiveModal = ref(false)
const archiveNameInput = ref('')

// 自选组合与持仓弹窗控制
const showSaveWatchlistModal = ref(false)
const watchlistNameInput = ref('')
const watchlistDescInput = ref('')
const showManageHoldingsModal = ref(false)
const editingHoldings = ref<{ symbol: string; name: string; quantity: number; avg_cost: number }[]>([])

// 快捷输入控制
const singleSymbolInput = ref(strategyStore.symbol)
const inputSymbolToAdd = ref('')

// 监听当前 store.symbol 变化同步到单标的输入框
watch(
  () => strategyStore.symbol,
  (newVal) => {
    singleSymbolInput.value = newVal
  }
)

// 快速单标的预设推荐
const singleQuickPresets = [
  { label: '沪深300 ETF', value: '510300.SH.ETF' },
  { label: '红利 ETF', value: '510880.SH.ETF' },
  { label: '中证500 ETF', value: '510500.SH.ETF' },
  { label: '黄金 ETF', value: '518880.SH.ETF' },
  { label: '贵州茅台', value: '600519.SH' },
  { label: '宁德时代', value: '300750.SZ' },
]

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 3000)
}

function handleSingleSymbolChange() {
  const val = singleSymbolInput.value.trim().toUpperCase()
  if (!val) return
  let formatted = val
  if (/^\d{6}$/.test(formatted)) {
    if (formatted.startsWith('6') || formatted.startsWith('5')) {
      formatted += formatted.startsWith('5') ? '.SH.ETF' : '.SH'
    } else if (formatted.startsWith('0') || formatted.startsWith('3') || formatted.startsWith('1')) {
      formatted += formatted.startsWith('1') ? '.SZ.ETF' : '.SZ'
    }
  }
  singleSymbolInput.value = formatted
  strategyStore.symbol = formatted
  strategyStore.symbols = [formatted]
  showToast(`🎯 已切换回测标的：${formatted}`)
}

function selectSinglePreset(item: { label: string; value: string }) {
  singleSymbolInput.value = item.value
  strategyStore.symbol = item.value
  strategyStore.symbols = [item.value]
  showToast(`🎯 已应用标的：${item.label}`)
}

// 批量解析与添加组合代码
function handleAddSymbol() {
  if (!inputSymbolToAdd.value.trim()) return
  const tokens = inputSymbolToAdd.value
    .split(/[,，\s]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
  tokens.forEach((t) => {
    let formatted = t
    if (/^\d{6}$/.test(formatted)) {
      if (formatted.startsWith('6') || formatted.startsWith('5')) {
        formatted += formatted.startsWith('5') ? '.SH.ETF' : '.SH'
      } else if (formatted.startsWith('0') || formatted.startsWith('3') || formatted.startsWith('1')) {
        formatted += formatted.startsWith('1') ? '.SZ.ETF' : '.SZ'
      }
    }
    strategyStore.addSymbolTag(formatted)
  })
  inputSymbolToAdd.value = ''
  showToast(`✅ 已更新标的池 (共 ${strategyStore.symbols.length} 只标的)`)
}

// 打开保存自选组合弹窗
function openSaveWatchlistModal() {
  watchlistNameInput.value = `我的自选组合 (${strategyStore.symbols.length}只标的)`
  watchlistDescInput.value = ''
  showSaveWatchlistModal.value = true
}

async function confirmSaveWatchlist() {
  if (!watchlistNameInput.value.trim()) {
    showToast('⚠️ 组合名称不能为空')
    return
  }
  const ok = await strategyStore.saveUserWatchlist(watchlistNameInput.value, watchlistDescInput.value)
  if (ok) {
    showSaveWatchlistModal.value = false
    showToast('💾 已成功保存自选股票池组合！')
  } else {
    showToast('⚠️ 保存失败，请检查网络或登录状态')
  }
}

// 打开管理持仓弹窗
function openManageHoldingsModal() {
  editingHoldings.value = strategyStore.userHoldings.map((h) => ({
    symbol: h.symbol,
    name: h.name,
    quantity: h.quantity,
    avg_cost: h.avg_cost,
  }))
  if (editingHoldings.value.length === 0) {
    editingHoldings.value = [
      { symbol: '510300.SH.ETF', name: '沪深300 ETF', quantity: 10000, avg_cost: 3.75 },
      { symbol: '510880.SH.ETF', name: '红利 ETF', quantity: 15000, avg_cost: 2.92 },
    ]
  }
  showManageHoldingsModal.value = true
}

function addHoldingRow() {
  editingHoldings.value.push({
    symbol: '',
    name: '',
    quantity: 1000,
    avg_cost: 10.0,
  })
}

function removeHoldingRow(idx: number) {
  editingHoldings.value.splice(idx, 1)
}

async function confirmSaveHoldings() {
  const valid = editingHoldings.value.filter((h) => h.symbol.trim().length > 0)
  if (valid.length === 0) {
    showToast('⚠️ 请至少录入一条有效持仓数据')
    return
  }
  const ok = await strategyStore.saveUserHoldings(valid)
  if (ok) {
    showManageHoldingsModal.value = false
    strategyStore.applyHoldingsToBacktest()
    showToast('💼 持仓底仓已同步更新并注入回测池！')
  } else {
    showToast('⚠️ 持仓更新失败，请稍后重试')
  }
}

// 计算持仓估算总市值成本
const holdingTotalCost = computed(() => {
  return strategyStore.userHoldings.reduce((sum, h) => sum + h.quantity * h.avg_cost, 0)
})

// 多标的判定
const isMultiSymbol = computed(() => {
  return strategyStore.backtestMode !== 'single' || strategyStore.symbols.length > 1
})

// 净值走势图 ECharts 配置
const chartOption = computed(() => {
  const res = strategyStore.backtestResult
  if (!res || !res.daily_records || res.daily_records.length === 0) {
    return {}
  }

  const initialCash = res.summary.initial_cash || 100000
  const dates = res.daily_records.map((r) => r.date)
  const strategyReturns = res.daily_records.map((r) => {
    return Number((((r.total_equity - initialCash) / initialCash) * 100).toFixed(2))
  })

  // 标的基准收益对齐
  const benchmarkReturns = res.benchmark_records?.map((b) => Number((b.return_pct * 100).toFixed(2))) || []

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(18, 19, 22, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.12)',
      textStyle: { color: '#ffffff', fontSize: 12 },
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        let tip = `<div class="font-mono font-bold mb-1 text-zinc-300">${params[0].axisValue}</div>`
        params.forEach((item: any) => {
          const val = item.value
          const color = val >= 0 ? '#ff2d55' : '#10b981'
          tip += `<div class="flex items-center justify-between gap-4 text-xs font-mono">
            <span class="flex items-center gap-1.5">${item.marker} ${item.seriesName}</span>
            <strong style="color: ${color}">${val >= 0 ? '+' : ''}${val}%</strong>
          </div>`
        })
        return tip
      },
    },
    legend: {
      data: [isMultiSymbol.value ? '策略组合总收益' : '策略累计收益', isMultiSymbol.value ? '沪深300基准收益' : '标的基准收益'],
      textStyle: { color: '#a1a1aa', fontSize: 11 },
      top: 0,
      right: 10,
    },
    grid: { left: 45, right: 20, top: 35, bottom: 25 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: 'rgba(255,255,255,0.4)',
        fontSize: 10,
        formatter: '{value}%',
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
    },
    series: [
      {
        name: isMultiSymbol.value ? '策略组合总收益' : '策略累计收益',
        type: 'line',
        smooth: true,
        data: strategyReturns,
        lineStyle: { width: 2.2, color: '#ff2d55' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(255, 45, 85, 0.28)' },
              { offset: 1, color: 'rgba(255, 45, 85, 0.0)' },
            ],
          },
        },
      },
      {
        name: isMultiSymbol.value ? '沪深300基准收益' : '标的基准收益',
        type: 'line',
        smooth: true,
        data: benchmarkReturns,
        lineStyle: { width: 1.5, color: '#38bdf8', type: 'dashed' },
      },
    ],
  }
})

// 打开归档弹窗
function openArchiveModal() {
  if (!authStore.isLoggedIn) {
    authStore.openLogin()
    return
  }
  if (!strategyStore.backtestResult) {
    showToast('⚠️ 当前没有可归档的回测结果，请先运行回测')
    return
  }
  const symbolDesc = isMultiSymbol.value
    ? `组合(${strategyStore.symbols.length}标的)`
    : strategyStore.symbol.split('.')[0]
  archiveNameInput.value = `${strategyStore.activeStrategyName || '自定策略'} (${symbolDesc})`
  showArchiveModal.value = true
}

// 确认归档保存
async function confirmArchiveBacktest() {
  if (!archiveNameInput.value.trim()) {
    showToast('⚠️ 档案名称不能为空')
    return
  }
  const res = await strategyStore.saveBacktestRecord(archiveNameInput.value.trim())
  if (res.success) {
    showArchiveModal.value = false
    showToast(res.message)
  } else {
    alert(res.message)
  }
}

// 载入历史回测参数配置
function loadHistoryParams(item: UserBacktestItem) {
  strategyStore.symbol = item.symbol
  if (item.symbol.includes(',')) {
    strategyStore.setSymbols(item.symbol.split(','))
    strategyStore.backtestMode = 'basket'
  } else {
    strategyStore.symbols = [item.symbol]
    strategyStore.backtestMode = 'single'
  }
  strategyStore.startDate = item.start_date
  if (item.end_date) {
    strategyStore.endDate = item.end_date
  }
  strategyStore.initialCash = item.initial_cash

  // 若关联了用户策略库中的策略，尝试联动载入代码
  if (item.strategy_id) {
    const matched = strategyStore.userStrategies.find((s) => s.id === item.strategy_id)
    if (matched) {
      strategyStore.loadUserStrategy(matched)
    }
  }

  activeTab.value = 'chart'
  showToast(`✅ 已复原回测参数：${item.strategy_name} (${item.symbol})`)
}

// 删除历史回测记录
async function deleteHistoryRecord(item: UserBacktestItem, e: Event) {
  e.stopPropagation()
  if (confirm(`确定要永久删除回测档案「${item.strategy_name}」吗？`)) {
    const ok = await strategyStore.deleteUserBacktest(item.id)
    if (ok) {
      showToast('🗑️ 回测档案已删除')
    }
  }
}

onMounted(() => {
  strategyStore.fetchUserWatchlists()
  strategyStore.fetchUserHoldings()
  if (authStore.isLoggedIn && strategyStore.userBacktests.length === 0) {
    strategyStore.fetchUserBacktests()
  }
})
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl relative">
    <!-- 提示气泡 Toast -->
    <div
      v-if="toastMsg"
      class="absolute top-14 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-emerald-500/90 text-white font-medium text-xs shadow-xl backdrop-blur-sm animate-bounce"
    >
      {{ toastMsg }}
    </div>

    <!-- 1. 顶部标的与组合全能控制舱 (Raycast Command Center) -->
    <div class="p-3 border-b border-white/[0.08] bg-white/[0.02] space-y-2.5 shrink-0">
      <!-- 第一行：模式分段切换器 & 起止时间与资金 -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <!-- 模式切换胶囊 Pills -->
        <div class="inline-flex p-0.5 rounded-xl bg-black/40 border border-white/[0.08] text-xs">
          <button
            @click="strategyStore.backtestMode = 'single'"
            :class="strategyStore.backtestMode === 'single' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-3 py-1 rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>🎯</span>
            <span>自由单标的</span>
          </button>
          <button
            @click="strategyStore.backtestMode = 'basket'"
            :class="strategyStore.backtestMode === 'basket' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-3 py-1 rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>🧺</span>
            <span>自选组合</span>
            <span class="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.08] text-zinc-300 font-mono">
              {{ strategyStore.symbols.length }}
            </span>
          </button>
          <button
            @click="strategyStore.backtestMode = 'holdings'; strategyStore.applyHoldingsToBacktest()"
            :class="strategyStore.backtestMode === 'holdings' ? 'bg-amber-500/20 text-amber-300 border-amber-500/30 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-3 py-1 rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>💼</span>
            <span>我的持仓回测</span>
            <span class="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.08] text-zinc-300 font-mono">
              {{ strategyStore.userHoldings.length }}
            </span>
          </button>
        </div>

        <!-- 起止时间与本金 -->
        <div class="flex items-center space-x-3 text-xs text-zinc-400">
          <div class="flex items-center space-x-1.5">
            <span>起始:</span>
            <input
              v-model="strategyStore.startDate"
              type="date"
              class="bg-black/50 border border-white/[0.1] rounded-lg px-2 py-0.5 text-xs text-white focus:outline-none focus:border-amber-500/50 font-mono"
            />
          </div>
          <div class="flex items-center space-x-1.5">
            <span>本金:</span>
            <div class="relative flex items-center">
              <span class="absolute left-2 text-zinc-500 font-mono text-[11px]">¥</span>
              <input
                v-model.number="strategyStore.initialCash"
                type="number"
                step="10000"
                class="w-24 pl-5 pr-1.5 py-0.5 bg-black/50 border border-white/[0.1] rounded-lg text-xs font-mono font-semibold text-white focus:outline-none focus:border-amber-500/50"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 第二行：子模式交互面板 (针对三种模式深度定制) -->
      <!-- A. 单标的模式 -->
      <div v-if="strategyStore.backtestMode === 'single'" class="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div class="flex items-center space-x-2 flex-1 max-w-md">
          <span class="text-xs text-zinc-400 shrink-0 font-medium">输入代码:</span>
          <div class="relative flex-1">
            <input
              v-model="singleSymbolInput"
              @change="handleSingleSymbolChange"
              @keydown.enter.prevent="handleSingleSymbolChange"
              type="text"
              placeholder="如 600519.SH / 510300.SH.ETF / 000858"
              class="w-full bg-black/50 border border-white/[0.12] rounded-lg px-3 py-1 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/60 font-mono"
            />
          </div>
          <button
            @click="handleSingleSymbolChange"
            class="px-2.5 py-1 rounded-lg bg-white/[0.08] hover:bg-white/[0.14] text-xs text-white transition-colors cursor-pointer shrink-0 font-medium"
          >
            确认应用
          </button>
          <button
            @click="router.push(`/symbol/${encodeURIComponent(strategyStore.symbol)}`)"
            class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-xs text-zinc-300 hover:text-white border border-white/[0.08] transition-colors cursor-pointer shrink-0 flex items-center space-x-1"
            title="查看该标的实时行情与K线"
          >
            <span>👁️</span>
            <span>查看K线</span>
          </button>
        </div>

        <!-- 快捷热门推荐 -->
        <div class="flex items-center space-x-1.5 overflow-x-auto text-[11px]">
          <span class="text-zinc-500 text-[10px] shrink-0">快捷推荐:</span>
          <button
            v-for="item in singleQuickPresets"
            :key="item.value"
            @click="selectSinglePreset(item)"
            :class="strategyStore.symbol === item.value ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-white/[0.03] hover:bg-white/[0.08] text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
            class="px-2 py-0.5 rounded-md border transition-all cursor-pointer shrink-0"
          >
            {{ item.label }}
          </button>
        </div>
      </div>

      <!-- B. 自选组合/股票池模式 -->
      <div v-else-if="strategyStore.backtestMode === 'basket'" class="space-y-2 pt-1">
        <!-- 组合标的标签池 + 快速添加输入框 -->
        <div class="flex flex-wrap items-center gap-1.5 p-2 rounded-xl bg-black/40 border border-white/[0.08] min-h-[38px]">
          <!-- 标的 Capsule 胶囊 -->
          <div
            v-for="sym in strategyStore.symbols"
            :key="sym"
            class="inline-flex items-center space-x-1 px-2 py-0.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-mono group hover:bg-amber-500/20 transition-all"
          >
            <span
              @click="router.push(`/symbol/${encodeURIComponent(sym)}`)"
              class="cursor-pointer hover:underline"
              title="点击查看标的行情详情与K线"
            >
              {{ sym }}
            </span>
            <button
              @click="strategyStore.removeSymbolTag(sym)"
              class="text-amber-500 hover:text-red-400 transition-colors cursor-pointer text-xs ml-0.5"
              title="移除标的"
            >
              ×
            </button>
          </div>

          <!-- 快速输入 / 批量粘贴框 -->
          <div class="flex-1 min-w-[220px] flex items-center space-x-1">
            <input
              v-model="inputSymbolToAdd"
              @keydown.enter.prevent="handleAddSymbol"
              type="text"
              placeholder="+ 粘贴或输入代码 (支持多只逗号隔开，回车添加)..."
              class="w-full bg-transparent border-none text-xs text-white placeholder-zinc-500 focus:outline-none font-mono py-0.5 px-1"
            />
            <button
              v-if="inputSymbolToAdd.trim()"
              @click="handleAddSymbol"
              class="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-600 text-[10px] font-bold text-white transition-colors cursor-pointer shrink-0"
            >
              添加
            </button>
          </div>
        </div>

        <!-- 组合快捷操作条：经典组合模板 & 存为自选 & 清空 -->
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
          <!-- 模板组合与我的组合选择下拉 -->
          <div class="flex items-center space-x-2">
            <span class="text-zinc-500 text-[11px]">组合模板:</span>
            <select
              @change="(e: any) => {
                const val = e.target.value
                if (!val) return
                const all = [...PRESET_WATCHLISTS, ...strategyStore.userWatchlists]
                const target = all.find((w) => w.name === val)
                if (target) {
                  strategyStore.loadPresetWatchlist(target)
                  showToast(`✅ 已应用组合：${target.name}`)
                }
              }"
              class="bg-black/50 border border-white/[0.1] rounded-lg px-2 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-amber-500/50 cursor-pointer"
            >
              <option value="">快速载入组合模板...</option>
              <optgroup label="🏛️ 机构经典配置池">
                <option v-for="w in PRESET_WATCHLISTS" :key="w.name" :value="w.name">
                  {{ w.name }} ({{ w.symbols.length }}标的)
                </option>
              </optgroup>
              <optgroup v-if="strategyStore.userWatchlists.length > 0" label="⭐ 我的自选组合">
                <option v-for="w in strategyStore.userWatchlists" :key="w.id" :value="w.name">
                  {{ w.name }} ({{ w.symbols.length }}标的)
                </option>
              </optgroup>
            </select>
          </div>

          <!-- 组合管理快捷按钮 -->
          <div class="flex items-center space-x-2">
            <button
              @click="openSaveWatchlistModal"
              class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs border border-white/[0.08] transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>💾</span>
              <span>存为我的组合</span>
            </button>
            <button
              @click="strategyStore.symbols = ['510300.SH.ETF']; showToast('已重置标的池为沪深300')"
              class="px-2 py-1 rounded-lg text-zinc-500 hover:text-red-400 text-xs transition-colors cursor-pointer"
            >
              重置
            </button>
          </div>
        </div>
      </div>

      <!-- C. 我的持仓回测模式 -->
      <div v-else-if="strategyStore.backtestMode === 'holdings'" class="pt-1">
        <div class="p-2.5 rounded-xl bg-gradient-to-r from-emerald-500/10 to-teal-500/5 border border-emerald-500/20 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div class="flex items-center space-x-2.5">
            <span class="text-lg">💼</span>
            <div>
              <div class="font-bold text-emerald-300 flex items-center space-x-1.5">
                <span>已关联当前资产底仓 (共 {{ strategyStore.userHoldings.length }} 只品种)</span>
                <span class="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 font-mono">
                  成本约 ¥{{ holdingTotalCost.toLocaleString() }}
                </span>
              </div>
              <div class="text-[11px] text-zinc-400 mt-0.5 flex items-center space-x-1 font-mono">
                <span>标的池:</span>
                <span class="text-zinc-200 truncate max-w-md">
                  {{ strategyStore.userHoldings.map((h) => `${h.name}(${h.symbol.split('.')[0]})`).join('、') }}
                </span>
              </div>
            </div>
          </div>

          <div class="flex items-center space-x-2">
            <button
              @click="strategyStore.applyHoldingsToBacktest(); showToast('⚡ 已自动将底仓标的与总市值同步至回测环境！')"
              class="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>⚡</span>
              <span>重新同步持仓</span>
            </button>
            <button
              @click="openManageHoldingsModal"
              class="px-2.5 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 text-xs border border-white/[0.08] transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>📝</span>
              <span>编辑底仓</span>
            </button>
          </div>
        </div>
      </div>
    </div>


    <!-- 2. 错误告警区 -->
    <div
      v-if="strategyStore.backtestError"
      class="m-4 p-3.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-300 space-y-1 animate-fadeIn"
    >
      <div class="flex items-center space-x-2 font-bold text-red-400">
        <span>⚠️ 回测中断告警</span>
      </div>
      <p class="font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap">
        {{ strategyStore.backtestError }}
      </p>
    </div>

    <!-- 3. 标签页与归档按钮条 -->
    <div class="px-4 py-2 border-b border-white/[0.08] bg-white/[0.01] flex flex-wrap items-center justify-between gap-2 shrink-0">
      <div class="flex items-center space-x-1 sm:space-x-2">
        <button
          @click="activeTab = 'chart'"
          :class="activeTab === 'chart' ? 'text-white border-b-2 border-red-500 font-bold bg-white/[0.04]' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-2.5 py-1 text-xs rounded-t-lg transition-all cursor-pointer flex items-center space-x-1"
        >
          <span>📈</span>
          <span>净值收益曲线</span>
        </button>
        <button
          @click="activeTab = 'trades'"
          :class="activeTab === 'trades' ? 'text-white border-b-2 border-red-500 font-bold bg-white/[0.04]' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-2.5 py-1 text-xs rounded-t-lg transition-all cursor-pointer flex items-center space-x-1"
        >
          <span>📑</span>
          <span>成交流水明细</span>
          <span v-if="strategyStore.backtestResult?.trades?.length" class="text-[10px] text-zinc-500 font-mono">
            ({{ strategyStore.backtestResult.trades.length }})
          </span>
        </button>
        <button
          @click="activeTab = 'history'"
          :class="activeTab === 'history' ? 'text-white border-b-2 border-amber-500 font-bold bg-white/[0.04]' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-2.5 py-1 text-xs rounded-t-lg transition-all cursor-pointer flex items-center space-x-1.5"
        >
          <span>📜</span>
          <span>历史回测档案</span>
          <span
            v-if="authStore.isLoggedIn && strategyStore.userBacktests.length"
            class="px-1.5 py-0.2 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold font-mono"
          >
            {{ strategyStore.userBacktests.length }}
          </span>
        </button>
      </div>

      <!-- 右侧：归档本次回测按钮与资产 -->
      <div class="flex items-center space-x-3">
        <span
          v-if="strategyStore.backtestResult"
          class="hidden md:inline text-[11px] text-zinc-400 font-mono"
        >
          期末资产: <strong class="text-white">¥{{ strategyStore.backtestResult.summary.final_equity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</strong>
        </span>

        <button
          v-if="strategyStore.backtestResult"
          @click="openArchiveModal"
          :disabled="strategyStore.isSavingBacktest"
          class="px-2.5 py-1 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 disabled:opacity-50 text-white font-semibold text-xs flex items-center space-x-1.5 shadow-md shadow-orange-500/20 transition-all cursor-pointer"
        >
          <span>💾</span>
          <span>{{ strategyStore.isSavingBacktest ? '正在归档...' : '归档本次回测' }}</span>
        </button>
      </div>
    </div>

    <!-- 4. 主体内容区 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- 4.1 历史回测档案视图 -->
      <div v-if="activeTab === 'history'" class="space-y-3">
        <!-- 未登录提示卡片 -->
        <div
          v-if="!authStore.isLoggedIn"
          class="p-8 text-center rounded-2xl bg-white/[0.02] border border-white/[0.08] space-y-3"
        >
          <div class="w-12 h-12 mx-auto rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-2xl">
            🔐
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">登录以解锁历史回测云端归档</h3>
            <p class="text-xs text-zinc-400 mt-1 max-w-md mx-auto leading-relaxed">
              登录后即可将每一次量化策略的回测指标（累计收益、年化、动态最大回撤、夏普比率与流水笔数）永久沉淀至个人档案，支持跨策略绩效对比与一键复原参数。
            </p>
          </div>
          <button
            @click="authStore.openLogin()"
            class="px-4 py-2 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-bold text-xs shadow-lg shadow-red-500/20 cursor-pointer"
          >
            立即登录 / 注册
          </button>
        </div>

        <!-- 已登录：加载中 -->
        <div
          v-else-if="strategyStore.userBacktestsLoading"
          class="p-12 flex flex-col items-center justify-center text-center space-y-3"
        >
          <div class="w-8 h-8 border-2 border-amber-500/20 border-t-amber-500 rounded-full animate-spin"></div>
          <span class="text-xs text-zinc-400 font-mono">拉取历史回测档案中...</span>
        </div>

        <!-- 已登录：空状态 -->
        <div
          v-else-if="strategyStore.userBacktests.length === 0"
          class="p-12 text-center rounded-2xl bg-white/[0.02] border border-white/[0.08] space-y-3"
        >
          <div class="w-12 h-12 mx-auto rounded-2xl bg-white/[0.03] border border-white/[0.08] flex items-center justify-center text-2xl">
            📜
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">暂无历史回测归档记录</h3>
            <p class="text-xs text-zinc-400 mt-1 max-w-sm mx-auto">
              在左侧编写量化策略并点击 <strong class="text-amber-400">【▶ 运行回测】</strong>，生成收益曲线后点击右上角 <strong class="text-amber-400">【💾 归档本次回测】</strong> 即可永久沉淀。
            </p>
          </div>
        </div>

        <!-- 已登录：档案卡片列表 -->
        <div v-else class="space-y-3">
          <div class="flex items-center justify-between text-xs text-zinc-400 px-1">
            <span>共存档 <strong class="text-white">{{ strategyStore.userBacktests.length }}</strong> 次回测评估记录</span>
            <button
              @click="strategyStore.fetchUserBacktests()"
              class="text-[11px] text-zinc-400 hover:text-white flex items-center space-x-1 cursor-pointer"
            >
              <span>🔄 刷新档案</span>
            </button>
          </div>

          <div
            v-for="record in strategyStore.userBacktests"
            :key="record.id"
            class="p-3.5 rounded-xl bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] hover:border-white/[0.12] transition-all space-y-3"
          >
            <!-- 卡片头部：策略名、标的与时间 -->
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center space-x-2">
                <span class="font-bold text-white text-xs">{{ record.strategy_name }}</span>
                <span class="px-1.5 py-0.5 rounded text-[10px] bg-red-500/15 text-red-400 font-mono font-bold">
                  {{ record.symbol }}
                </span>
                <span class="text-[10px] text-zinc-500 font-mono">
                  {{ record.start_date }} ~ {{ record.end_date || '至今' }}
                </span>
              </div>
              <div class="text-[10px] text-zinc-500 font-mono">
                归档于: {{ new Date(record.created_at).toLocaleString() }}
              </div>
            </div>

            <!-- 卡片中段：核心指标网格 -->
            <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center text-xs">
              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">总收益率</div>
                <div
                  :class="record.total_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                  class="font-mono font-bold mt-0.5"
                >
                  {{ record.total_return >= 0 ? '+' : '' }}{{ (record.total_return * 100).toFixed(2) }}%
                </div>
              </div>

              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">年化收益</div>
                <div
                  :class="record.annualized_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                  class="font-mono font-bold mt-0.5"
                >
                  {{ record.annualized_return >= 0 ? '+' : '' }}{{ (record.annualized_return * 100).toFixed(2) }}%
                </div>
              </div>

              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">最大动态回撤</div>
                <div class="font-mono font-bold text-emerald-400 mt-0.5">
                  -{{ (record.max_drawdown * 100).toFixed(2) }}%
                </div>
              </div>

              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">夏普比率</div>
                <div class="font-mono font-bold text-amber-300 mt-0.5">
                  {{ record.sharpe_ratio.toFixed(2) }}
                </div>
              </div>

              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">胜率</div>
                <div class="font-mono font-bold text-white mt-0.5">
                  {{ (record.win_rate * 100).toFixed(1) }}%
                </div>
              </div>

              <div class="p-2 rounded-lg bg-black/30 border border-white/[0.04]">
                <div class="text-[10px] text-zinc-400">成交流水</div>
                <div class="font-mono font-bold text-white mt-0.5">
                  {{ record.total_trades }} 笔
                </div>
              </div>
            </div>

            <!-- 卡片底部：期末资产与快捷操作 -->
            <div class="flex items-center justify-between pt-1 border-t border-white/[0.04] text-xs">
              <div class="text-zinc-400 text-[11px]">
                初始: <span class="font-mono text-zinc-300">¥{{ record.initial_cash.toLocaleString() }}</span>
                <span class="mx-1.5">➔</span>
                期末资产: <strong class="font-mono text-white">¥{{ record.final_equity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</strong>
              </div>

              <div class="flex items-center space-x-2">
                <button
                  @click="loadHistoryParams(record)"
                  class="px-2 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 hover:text-white transition-all text-[11px] flex items-center space-x-1 cursor-pointer"
                >
                  <span>🚀</span>
                  <span>载入回测参数</span>
                </button>
                <button
                  @click="deleteHistoryRecord(record, $event)"
                  class="px-2 py-1 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 transition-all text-[11px] flex items-center space-x-1 cursor-pointer"
                >
                  <span>🗑️</span>
                  <span>删除</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 4.2 实时回测模式 (净值曲线或成交流水) -->
      <template v-else>
        <!-- 加载中动画 -->
        <div
          v-if="strategyStore.isBacktesting"
          class="h-full flex flex-col items-center justify-center text-center p-8 space-y-3"
        >
          <div class="w-10 h-10 border-2 border-red-500/20 border-t-red-500 rounded-full animate-spin"></div>
          <div class="text-xs font-mono text-zinc-300">
            <span>安全沙箱编译审计中 & 事件撮合推进...</span>
          </div>
        </div>

        <!-- 空状态：等待运行 -->
        <div
          v-else-if="!strategyStore.backtestResult"
          class="h-full flex flex-col items-center justify-center text-center p-8 space-y-3"
        >
          <div class="w-12 h-12 rounded-2xl bg-white/[0.03] border border-white/[0.08] flex items-center justify-center text-2xl">
            📊
          </div>
          <div>
            <h3 class="text-sm font-bold text-white">回测绩效看板等待就绪</h3>
            <p class="text-xs text-zinc-400 mt-1 max-w-sm">
              点击编辑器右上角的 <strong class="text-amber-400">【▶ 运行回测 (⌘+Enter)】</strong>，撮合引擎将在沙箱中毫秒级完成全历史模拟撮合并绘制收益曲线。
            </p>
          </div>
        </div>

        <!-- 回测完成：展示指标卡片与图表/流水 -->
        <template v-else>
          <!-- 核心 KPI 矩阵卡片 -->
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5">
            <!-- 累计收益率 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">累计总收益</div>
              <div
                :class="strategyStore.backtestResult.summary.total_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                class="text-base font-bold font-mono mt-0.5"
              >
                {{ strategyStore.backtestResult.summary.total_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.total_return * 100).toFixed(2) }}%
              </div>
            </div>

            <!-- 年化收益率 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">年化收益率</div>
              <div
                :class="strategyStore.backtestResult.summary.annualized_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                class="text-base font-bold font-mono mt-0.5"
              >
                {{ strategyStore.backtestResult.summary.annualized_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.annualized_return * 100).toFixed(2) }}%
              </div>
            </div>

            <!-- 最大回撤 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">最大动态回撤</div>
              <div class="text-base font-bold font-mono text-emerald-400 mt-0.5">
                -{{ (strategyStore.backtestResult.summary.max_drawdown * 100).toFixed(2) }}%
              </div>
            </div>

            <!-- 夏普比率 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">夏普比率 (Sharpe)</div>
              <div class="text-base font-bold font-mono text-amber-300 mt-0.5">
                {{ strategyStore.backtestResult.summary.sharpe_ratio.toFixed(2) }}
              </div>
            </div>

            <!-- 交易胜率 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">交易胜率</div>
              <div class="text-base font-bold font-mono text-white mt-0.5">
                {{ (strategyStore.backtestResult.summary.win_rate * 100).toFixed(1) }}%
              </div>
            </div>

            <!-- 交易总次数 -->
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <div class="text-[10px] text-zinc-400">撮合成交笔数</div>
              <div class="text-base font-bold font-mono text-white mt-0.5">
                {{ strategyStore.backtestResult.summary.total_trades }} 笔
              </div>
            </div>
          </div>

          <!-- 图表视图 -->
          <div v-show="activeTab === 'chart'" class="w-full">
            <EChartWrapper :option="chartOption" height="280px" />
          </div>

          <!-- 成交流水记录表格 -->
          <div v-show="activeTab === 'trades'" class="overflow-x-auto max-h-64 rounded-xl border border-white/[0.06]">
            <table class="w-full text-left text-[11px] font-mono">
              <thead class="bg-white/[0.03] text-zinc-400 border-b border-white/[0.06]">
                <tr>
                  <th class="p-2.5">成交时间</th>
                  <th class="p-2.5">标的</th>
                  <th class="p-2.5">方向</th>
                  <th class="p-2.5">成交均价</th>
                  <th class="p-2.5">成交数量</th>
                  <th class="p-2.5">佣金手续费</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/[0.04]">
                <tr
                  v-for="(t, idx) in strategyStore.backtestResult.trades"
                  :key="idx"
                  class="hover:bg-white/[0.02] transition-colors"
                >
                  <td class="p-2.5 text-zinc-300">{{ t.datetime_str }}</td>
                  <td class="p-2.5">
                    <span
                      @click="router.push(`/symbol/${encodeURIComponent(t.symbol)}`)"
                      class="px-1.5 py-0.5 rounded bg-amber-500/15 hover:bg-amber-500/30 text-amber-300 font-mono font-bold text-[10px] border border-amber-500/20 cursor-pointer transition-colors"
                      title="点击查看标的行情与K线详情"
                    >
                      {{ t.symbol }}
                    </span>
                  </td>
                  <td class="p-2.5">
                    <span
                      :class="t.side.toUpperCase() === 'BUY' ? 'bg-red-500/15 text-red-400 border border-red-500/20' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'"
                      class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                    >
                      {{ t.side.toUpperCase() === 'BUY' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="p-2.5 text-zinc-100 font-semibold">¥{{ t.price.toFixed(3) }}</td>
                  <td class="p-2.5 text-zinc-300">{{ t.quantity.toLocaleString() }} 股</td>
                  <td class="p-2.5 text-zinc-400">¥{{ t.commission.toFixed(2) }}</td>
                </tr>
                <tr v-if="!strategyStore.backtestResult.trades?.length">
                  <td colspan="6" class="p-4 text-center text-zinc-500">该回测区间内未触发交易信号</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>

    <!-- 5. 归档回测弹窗 Modal -->
    <div
      v-if="showArchiveModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#18191e] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2">
            <span class="text-amber-400 text-base">💾</span>
            <h3 class="text-sm font-bold text-white">归档本次回测绩效到云端</h3>
          </div>
          <button
            @click="showArchiveModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">档案备注名称</label>
            <input
              v-model="archiveNameInput"
              type="text"
              placeholder="如: 经典双均线(5-20) 2023年沪深300测试"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/50"
            />
          </div>

          <!-- 回测关键指标速览 -->
          <div
            v-if="strategyStore.backtestResult"
            class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-1 text-zinc-400 text-[11px] font-mono"
          >
            <div class="flex justify-between">
              <span>回测标的:</span>
              <span class="text-white">{{ strategyStore.symbol }}</span>
            </div>
            <div class="flex justify-between">
              <span>区间收益:</span>
              <span :class="strategyStore.backtestResult.summary.total_return >= 0 ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'">
                {{ (strategyStore.backtestResult.summary.total_return * 100).toFixed(2) }}%
              </span>
            </div>
            <div class="flex justify-between">
              <span>最大回撤:</span>
              <span class="text-emerald-400">-{{ (strategyStore.backtestResult.summary.max_drawdown * 100).toFixed(2) }}%</span>
            </div>
            <div class="flex justify-between">
              <span>夏普比率:</span>
              <span class="text-amber-300">{{ strategyStore.backtestResult.summary.sharpe_ratio.toFixed(2) }}</span>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button
            @click="showArchiveModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmArchiveBacktest"
            :disabled="strategyStore.isSavingBacktest"
            class="px-4 py-1.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 disabled:opacity-50 text-white font-bold text-xs shadow-lg shadow-orange-500/20 transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>{{ strategyStore.isSavingBacktest ? '正在保存...' : '确认归档' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 6. 保存自选组合弹窗 Modal -->
    <div
      v-if="showSaveWatchlistModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#18191e] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2">
            <span class="text-blue-400 text-base">💾</span>
            <h3 class="text-sm font-bold text-white">保存为我的自选组合</h3>
          </div>
          <button
            @click="showSaveWatchlistModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">组合名称 <span class="text-red-400">*</span></label>
            <input
              v-model="watchlistNameInput"
              type="text"
              placeholder="如: 高股息核心组合 / 科技成长先锋"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>

          <div>
            <label class="block text-zinc-400 mb-1 font-medium">投资逻辑 / 备注说明</label>
            <textarea
              v-model="watchlistDescInput"
              rows="2"
              placeholder="简要记录组合选股逻辑或回测策略说明 (选填)"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 resize-none"
            ></textarea>
          </div>

          <!-- 组合内标的清单 -->
          <div>
            <div class="flex items-center justify-between mb-1.5 text-zinc-400 font-medium">
              <span>包含标的</span>
              <span class="text-blue-300 font-mono">共 {{ strategyStore.symbols.length }} 只标的</span>
            </div>
            <div class="p-2.5 rounded-xl bg-black/30 border border-white/[0.06] flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
              <span
                v-for="sym in strategyStore.symbols"
                :key="sym"
                class="px-2 py-0.5 rounded-md bg-blue-500/15 text-blue-300 font-mono text-[11px] border border-blue-500/20"
              >
                {{ sym }}
              </span>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button
            @click="showSaveWatchlistModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmSaveWatchlist"
            class="px-4 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-500/20 transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>确认保存组合</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 7. 编辑我的持仓底仓弹窗 Modal -->
    <div
      v-if="showManageHoldingsModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-xl bg-[#18191e] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden p-5 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2">
            <span class="text-emerald-400 text-base">💼</span>
            <div>
              <h3 class="text-sm font-bold text-white">管理我的持仓底仓</h3>
              <p class="text-[11px] text-zinc-400">录入实盘持仓或模拟底仓，保存后将自动同步并注入回测环境</p>
            </div>
          </div>
          <button
            @click="showManageHoldingsModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <div class="space-y-3 text-xs">
          <!-- 持仓列表滚动区 -->
          <div class="max-h-64 overflow-y-auto rounded-xl border border-white/[0.08] overflow-hidden">
            <table class="w-full text-left font-mono text-[11px]">
              <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08]">
                <tr>
                  <th class="p-2">标的代码 (如 600519.SH)</th>
                  <th class="p-2">标的名称 (选填)</th>
                  <th class="p-2">持仓股数</th>
                  <th class="p-2">成本均价(元)</th>
                  <th class="p-2 text-center">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/[0.04]">
                <tr v-for="(h, idx) in editingHoldings" :key="idx" class="hover:bg-white/[0.02]">
                  <td class="p-1.5">
                    <input
                      v-model="h.symbol"
                      type="text"
                      placeholder="600519.SH"
                      class="w-full bg-black/40 border border-white/[0.1] rounded px-2 py-1 text-white font-mono text-xs focus:outline-none focus:border-emerald-500/50 uppercase"
                    />
                  </td>
                  <td class="p-1.5">
                    <input
                      v-model="h.name"
                      type="text"
                      placeholder="贵州茅台"
                      class="w-full bg-black/40 border border-white/[0.1] rounded px-2 py-1 text-zinc-200 text-xs focus:outline-none focus:border-emerald-500/50"
                    />
                  </td>
                  <td class="p-1.5">
                    <input
                      v-model.number="h.quantity"
                      type="number"
                      step="100"
                      min="0"
                      class="w-full bg-black/40 border border-white/[0.1] rounded px-2 py-1 text-zinc-200 text-xs focus:outline-none focus:border-emerald-500/50 font-mono"
                    />
                  </td>
                  <td class="p-1.5">
                    <input
                      v-model.number="h.avg_cost"
                      type="number"
                      step="0.01"
                      min="0"
                      class="w-full bg-black/40 border border-white/[0.1] rounded px-2 py-1 text-zinc-200 text-xs focus:outline-none focus:border-emerald-500/50 font-mono"
                    />
                  </td>
                  <td class="p-1.5 text-center">
                    <button
                      @click="removeHoldingRow(idx)"
                      class="text-zinc-500 hover:text-red-400 transition-colors p-1 cursor-pointer"
                      title="删除该条记录"
                    >
                      🗑️
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 添加按钮与底仓总成本统计 -->
          <div class="flex items-center justify-between pt-1">
            <button
              @click="addHoldingRow"
              class="px-2.5 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 hover:text-white border border-white/[0.08] transition-all text-xs flex items-center space-x-1 cursor-pointer"
            >
              <span>➕ 添加持仓标的</span>
            </button>
            <div class="text-[11px] text-zinc-400 font-mono">
              持仓估算总成本: <strong class="text-emerald-400 text-xs">¥{{ editingHoldings.reduce((s, h) => s + (h.quantity || 0) * (h.avg_cost || 0), 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</strong>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-3 border-t border-white/[0.08]">
          <button
            @click="showManageHoldingsModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            @click="confirmSaveHoldings"
            class="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>保存并同步注入回测</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
