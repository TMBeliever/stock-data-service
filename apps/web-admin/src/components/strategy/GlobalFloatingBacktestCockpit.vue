<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useStrategyStore, type UserBacktestItem } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const { cockpitPosition: cockpitPos, cockpitSize } = storeToRefs(strategyStore)

const activeTab = ref<'chart' | 'trades'>('chart')
const isMaximized = ref(false)
const toastMsg = ref('')
const singleSymbolInput = ref(strategyStore.symbol)
const inputSymbolToAdd = ref('')
const selectedQuickRange = ref<'half_year' | '1y' | '2y' | '3y' | '2023' | 'all'>('1y')
const showArchiveModal = ref(false)
const archiveNameInput = ref('')

// 自定义高质感下拉弹窗状态 (取代原生丑陋的 <select>)
const showStrategyDropdown = ref(false)
const showWatchlistDropdown = ref(false)
const strategyDropdownRef = ref<HTMLElement | null>(null)
const watchlistDropdownRef = ref<HTMLElement | null>(null)

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2600)
}

// 当前激活策略名称
const currentStrategyName = computed(() => {
  const matched = strategyStore.userStrategies.find((s) => s.id === strategyStore.activeStrategyId)
  return matched?.name || strategyStore.activeStrategyName || '自定义量化策略'
})

// 快速单标的推荐
const singleQuickPresets = [
  { label: '沪深300 ETF', value: '510300.SH.ETF' },
  { label: '贵州茅台', value: '600519.SH.STK' },
  { label: '宁德时代', value: '300750.SZ.STK' },
  { label: '红利 ETF', value: '510880.SH.ETF' },
  { label: '黄金 ETF', value: '518880.SH.ETF' },
  { label: '纳指 ETF', value: '513100.SH.ETF' },
]

// 监听当前 store.symbol 变化同步到单标的输入框
watch(
  () => strategyStore.symbol,
  (newVal) => {
    singleSymbolInput.value = newVal
  }
)

function handleSingleSymbolChange() {
  const val = singleSymbolInput.value.trim().toUpperCase()
  if (!val) return
  let formatted = val
  if (/^\d{6}$/.test(formatted)) {
    if (formatted.startsWith('6') || formatted.startsWith('5')) {
      formatted += formatted.startsWith('5') ? '.SH.ETF' : '.SH.STK'
    } else if (formatted.startsWith('0') || formatted.startsWith('3') || formatted.startsWith('1')) {
      formatted += formatted.startsWith('1') ? '.SZ.ETF' : '.SZ.STK'
    }
  }
  singleSymbolInput.value = formatted
  strategyStore.symbol = formatted
  strategyStore.symbols = [formatted]
  showToast(`🎯 已应用回测标的：${formatted}`)
}

function selectSinglePreset(item: { label: string; value: string }) {
  singleSymbolInput.value = item.value
  strategyStore.symbol = item.value
  strategyStore.symbols = [item.value]
  showToast(`🎯 已应用标的：${item.label}`)
}

// 快捷区间切换
function applyDateRange(range: 'half_year' | '1y' | '2y' | '3y' | '2023' | 'all') {
  selectedQuickRange.value = range
  strategyStore.setQuickDateRange(range)
  showToast(`📅 时间跨度已应用：${strategyStore.startDate} 至 ${strategyStore.endDate || '最新'}`)
}

// 批量添加组合标的
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
        formatted += formatted.startsWith('5') ? '.SH.ETF' : '.SH.STK'
      } else if (formatted.startsWith('0') || formatted.startsWith('3') || formatted.startsWith('1')) {
        formatted += formatted.startsWith('1') ? '.SZ.ETF' : '.SZ.STK'
      }
    }
    strategyStore.addSymbolTag(formatted)
  })
  inputSymbolToAdd.value = ''
  showToast(`✅ 已更新标的池 (共 ${strategyStore.symbols.length} 只标的)`)
}

// 切换策略模板
function selectStrategyTemplate(st: any) {
  strategyStore.loadUserStrategy(st)
  showStrategyDropdown.value = false
  showToast(`✓ 已切换策略: ${st.name}`)
}

// 载入预设组合
function selectWatchlistTemplate(w: any) {
  strategyStore.loadPresetWatchlist(w)
  showWatchlistDropdown.value = false
  showToast(`✅ 已应用配置池：${w.name}`)
}

// 底仓估算总成本
const holdingTotalCost = computed(() => {
  return strategyStore.userHoldings.reduce((sum, h) => sum + h.quantity * h.avg_cost, 0)
})

// -------------------------------------------------------------
// 1. 悬浮胶囊自由拖拽 (Draggable Capsule)
// -------------------------------------------------------------
let isDraggingTrigger = false
let triggerMouseStartX = 0
let triggerMouseStartY = 0
let triggerInitialX = 0
let triggerInitialY = 0
let hasTriggerMoved = false

function onTriggerMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  isDraggingTrigger = true
  hasTriggerMoved = false
  triggerMouseStartX = e.clientX
  triggerMouseStartY = e.clientY
  triggerInitialX = strategyStore.cockpitTriggerPosition?.x ?? 880
  triggerInitialY = strategyStore.cockpitTriggerPosition?.y ?? 720

  window.addEventListener('mousemove', onTriggerMouseMove)
  window.addEventListener('mouseup', onTriggerMouseUp)
}

function onTriggerMouseMove(e: MouseEvent) {
  if (!isDraggingTrigger) return
  const deltaX = e.clientX - triggerMouseStartX
  const deltaY = e.clientY - triggerMouseStartY
  if (Math.hypot(deltaX, deltaY) > 3) {
    hasTriggerMoved = true
  }
  strategyStore.updateCockpitTriggerPosition(triggerInitialX + deltaX, triggerInitialY + deltaY)
}

function onTriggerMouseUp() {
  if (!isDraggingTrigger) return
  isDraggingTrigger = false
  window.removeEventListener('mousemove', onTriggerMouseMove)
  window.removeEventListener('mouseup', onTriggerMouseUp)

  if (!hasTriggerMoved) {
    strategyStore.toggleBacktestCockpit(strategyStore.cockpitTriggerPosition)
  }
}

// -------------------------------------------------------------
// 2. 窗口拖拽 (Draggable Window Header)
// -------------------------------------------------------------
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let initialPosX = 0
let initialPosY = 0

function onHeaderMouseDown(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.closest('button') || target.closest('select') || target.closest('input') || target.closest('textarea') || target.closest('.no-drag')) {
    return
  }
  isDragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  initialPosX = cockpitPos.value.x
  initialPosY = cockpitPos.value.y

  window.addEventListener('mousemove', onHeaderMouseMove)
  window.addEventListener('mouseup', onHeaderMouseUp)
}

function onHeaderMouseMove(e: MouseEvent) {
  if (!isDragging || isMaximized.value) return
  const deltaX = e.clientX - dragStartX
  const deltaY = e.clientY - dragStartY
  strategyStore.updateCockpitPosition(initialPosX + deltaX, initialPosY + deltaY)
}

function onHeaderMouseUp() {
  isDragging = false
  window.removeEventListener('mousemove', onHeaderMouseMove)
  window.removeEventListener('mouseup', onHeaderMouseUp)
}

// -------------------------------------------------------------
// 3. 4-Corner 自由拉伸缩放 (Resizable)
// -------------------------------------------------------------
let isCornerResizing = false
let activeCorner: 'nw' | 'ne' | 'sw' | 'se' | null = null
let resizeMouseStartX = 0
let resizeMouseStartY = 0
let resizeInitialX = 0
let resizeInitialY = 0
let resizeInitialW = 0
let resizeInitialH = 0

function onCornerMouseDown(corner: 'nw' | 'ne' | 'sw' | 'se', e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  if (isMaximized.value) return

  isCornerResizing = true
  activeCorner = corner
  resizeMouseStartX = e.clientX
  resizeMouseStartY = e.clientY
  resizeInitialX = cockpitPos.value.x
  resizeInitialY = cockpitPos.value.y
  resizeInitialW = cockpitSize.value.width
  resizeInitialH = cockpitSize.value.height

  window.addEventListener('mousemove', onCornerMouseMove)
  window.addEventListener('mouseup', onCornerMouseUp)
}

function onCornerMouseMove(e: MouseEvent) {
  if (!isCornerResizing || !activeCorner) return
  const deltaX = e.clientX - resizeMouseStartX
  const deltaY = e.clientY - resizeMouseStartY

  const minW = 560
  const minH = 460

  let newX = resizeInitialX
  let newY = resizeInitialY
  let newW = resizeInitialW
  let newH = resizeInitialH

  if (activeCorner === 'se') {
    newW = Math.max(minW, resizeInitialW + deltaX)
    newH = Math.max(minH, resizeInitialH + deltaY)
  } else if (activeCorner === 'sw') {
    const tentativeW = resizeInitialW - deltaX
    if (tentativeW < minW) {
      newW = minW
      newX = resizeInitialX + (resizeInitialW - minW)
    } else {
      newW = tentativeW
      newX = resizeInitialX + deltaX
    }
    newH = Math.max(minH, resizeInitialH + deltaY)
  } else if (activeCorner === 'ne') {
    newW = Math.max(minW, resizeInitialW + deltaX)
    const tentativeH = resizeInitialH - deltaY
    if (tentativeH < minH) {
      newH = minH
      newY = resizeInitialY + (resizeInitialH - minH)
    } else {
      newH = tentativeH
      newY = resizeInitialY + deltaY
    }
  } else if (activeCorner === 'nw') {
    const tentativeW = resizeInitialW - deltaX
    if (tentativeW < minW) {
      newW = minW
      newX = resizeInitialX + (resizeInitialW - minW)
    } else {
      newW = tentativeW
      newX = resizeInitialX + deltaX
    }
    const tentativeH = resizeInitialH - deltaY
    if (tentativeH < minH) {
      newH = minH
      newY = resizeInitialY + (resizeInitialH - minH)
    } else {
      newH = tentativeH
      newY = resizeInitialY + deltaY
    }
  }

  strategyStore.updateCockpitPosition(newX, newY)
  strategyStore.updateCockpitSize(newW, newH)
}

function onCornerMouseUp() {
  isCornerResizing = false
  activeCorner = null
  window.removeEventListener('mousemove', onCornerMouseMove)
  window.removeEventListener('mouseup', onCornerMouseUp)
}

// -------------------------------------------------------------
// 快捷键 ⌘+B 切换回测工作舱
// -------------------------------------------------------------
function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
    e.preventDefault()
    strategyStore.toggleBacktestCockpit(strategyStore.cockpitTriggerPosition)
  } else if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && strategyStore.isBacktestCockpitOpen) {
    e.preventDefault()
    strategyStore.runBacktest()
  } else if (e.key === 'Escape') {
    if (showStrategyDropdown.value) {
      showStrategyDropdown.value = false
    }
    if (showWatchlistDropdown.value) {
      showWatchlistDropdown.value = false
    }
  }
}

function onWindowClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (strategyDropdownRef.value && !strategyDropdownRef.value.contains(target)) {
    showStrategyDropdown.value = false
  }
  if (watchlistDropdownRef.value && !watchlistDropdownRef.value.contains(target)) {
    showWatchlistDropdown.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('click', onWindowClick)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('click', onWindowClick)
})

// 归档回测
function openArchiveModal() {
  if (!authStore.isLoggedIn) {
    authStore.openLogin()
    return
  }
  const dateStr = new Date().toLocaleDateString('zh-CN')
  archiveNameInput.value = `${strategyStore.activeStrategyName} - ${strategyStore.symbol} (${dateStr})`
  showArchiveModal.value = true
}

async function confirmArchiveBacktest() {
  const success = await strategyStore.saveBacktestRecord(archiveNameInput.value)
  if (success) {
    showArchiveModal.value = false
    showToast('💾 回测结果已成功归档到个人云端档案！')
  }
}

// 快捷保存当前标的池为新组合
async function handleSaveCurrentSymbolsAsWatchlist() {
  if (!authStore.isLoggedIn) {
    authStore.openLogin()
    return
  }
  const name = prompt('请输入新自选组合名称:', `我的策略组合 (${strategyStore.symbols.length}只标的)`)
  if (!name || !name.trim()) return
  const ok = await strategyStore.saveUserWatchlist(name.trim())
  if (ok) {
    showToast(`⭐ 已成功创建自选组合「${name.trim()}」！`)
  }
}

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

  // 基准收益严格按自然交易日 Key 精确对齐 (杜绝因停牌或切片天数差异导致的错位)
  const benchmarkMap = new Map<string, number>()
  if (res.benchmark_records) {
    for (const b of res.benchmark_records) {
      benchmarkMap.set(b.date, Number((b.return_pct * 100).toFixed(2)))
    }
  }

  let lastBench = 0.0
  const benchmarkReturns = dates.map((d) => {
    if (benchmarkMap.has(d)) {
      lastBench = benchmarkMap.get(d)!
      return lastBench
    }
    return lastBench
  })

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(18, 19, 25, 0.96)',
      borderColor: 'rgba(255, 255, 255, 0.14)',
      textStyle: { color: '#ffffff', fontSize: 12 },
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        let tip = `<div class="font-mono font-bold mb-1 text-zinc-300 text-xs">${params[0].axisValue}</div>`
        params.forEach((item: any) => {
          const colorClass = item.value >= 0 ? '#ef4444' : '#10b981'
          tip += `<div class="flex items-center justify-between space-x-3 text-xs">
            <span style="color:${item.color}">${item.seriesName}:</span>
            <strong style="color:${colorClass}" class="font-mono">${item.value >= 0 ? '+' : ''}${item.value}%</strong>
          </div>`
        })
        return tip
      },
    },
    legend: {
      data: ['策略收益率', '沪深300基准收益'],
      textStyle: { color: 'rgba(255, 255, 255, 0.75)', fontSize: 11 },
      top: 0,
      right: 15,
    },
    grid: { left: 45, right: 25, top: 32, bottom: 25 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: 'rgba(255, 255, 255, 0.45)',
        fontSize: 10,
        formatter: '{value}%',
      },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
    },
    series: [
      {
        name: '策略收益率',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: strategyReturns,
        lineStyle: { width: 2.4, color: '#ef4444' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(239, 68, 68, 0.35)' },
              { offset: 1, color: 'rgba(239, 68, 68, 0.0)' },
            ],
          },
        },
      },
      {
        name: '沪深300基准收益',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: benchmarkReturns,
        lineStyle: { width: 1.5, color: '#3b82f6', type: 'dashed' },
      },
    ],
  }
})
</script>

<template>
  <teleport to="body">
    <!-- ========================================================================= -->
    <!-- 1. 收起状态：自由拖拽的暗色毛玻璃悬浮能量胶囊 (与 AI 悬浮球和谐并列) -->
    <!-- ========================================================================= -->
    <transition name="fade">
      <div
        v-if="!strategyStore.isBacktestCockpitOpen"
        @mousedown="onTriggerMouseDown"
        :style="{
          position: 'fixed',
          left: `${strategyStore.cockpitTriggerPosition?.x ?? 880}px`,
          top: `${strategyStore.cockpitTriggerPosition?.y ?? 720}px`,
          zIndex: 9998,
        }"
        class="group flex items-center space-x-2.5 pl-3 pr-3.5 py-2 rounded-full bg-[#13151b]/95 hover:bg-[#181a23] border border-white/[0.14] hover:border-amber-500/50 shadow-2xl shadow-black/80 hover:shadow-amber-500/20 backdrop-blur-2xl transition-shadow duration-200 cursor-grab active:cursor-grabbing select-none"
        title="点击呼出量化回测工作舱 (⌘+B)，按住左键自由拖动"
      >
        <div class="relative flex items-center justify-center w-7 h-7 rounded-xl bg-gradient-to-br from-amber-500/25 via-red-500/20 to-transparent border border-amber-500/30 text-sm shadow-sm group-hover:border-amber-400/60 transition-colors pointer-events-none">
          <span class="text-amber-400">⚡</span>
          <span
            v-if="strategyStore.isBacktesting"
            class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-amber-400 animate-ping ring-2 ring-[#13151b]"
          ></span>
        </div>

        <div class="flex flex-col text-left pointer-events-none">
          <div class="flex items-center space-x-1.5">
            <span class="text-xs font-semibold text-zinc-100 group-hover:text-amber-300 transition-colors tracking-wide">量化回测工作舱</span>
          </div>
          <span class="text-[9px] text-zinc-400 font-mono flex items-center space-x-1">
            <span
              class="w-1.5 h-1.5 rounded-full inline-block"
              :class="strategyStore.isBacktesting ? 'bg-amber-400 animate-pulse' : 'bg-red-400 shadow-[0_0_8px_rgba(248,113,113,0.8)]'"
            ></span>
            <span>{{ strategyStore.isBacktesting ? '沙箱撮合推演中...' : '极客事件驱动引擎' }}</span>
          </span>
        </div>

        <div class="ml-1 pl-2 border-l border-white/[0.1] flex items-center pointer-events-none">
          <kbd class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.12] text-zinc-300 font-mono shadow-inner group-hover:border-amber-500/40 group-hover:text-amber-300 transition-colors">⌘B</kbd>
        </div>
      </div>
    </transition>

    <!-- ========================================================================= -->
    <!-- 2. 展开状态：极客暗黑风全站悬浮回测工作舱 (可拖拽 + 四角拉伸缩放 + 持久化) -->
    <!-- ========================================================================= -->
    <div
      v-if="strategyStore.isBacktestCockpitOpen"
      :style="isMaximized
        ? { position: 'fixed', left: '16px', top: '16px', width: 'calc(100vw - 32px)', height: 'calc(100vh - 32px)', zIndex: 9999 }
        : { position: 'fixed', left: `${cockpitPos?.x ?? 40}px`, top: `${cockpitPos?.y ?? 70}px`, width: `${cockpitSize?.width ?? 920}px`, height: `${cockpitSize?.height ?? 680}px`, zIndex: 9999 }"
      class="bg-[#101218]/96 backdrop-blur-3xl border border-white/[0.14] rounded-2xl shadow-[0_30px_90px_rgba(0,0,0,0.85)] flex flex-col overflow-hidden animate-fadeIn select-none"
    >
      <!-- 2.1 顶部拖拽标题栏 (Header Drag Bar) -->
      <div
        @mousedown="onHeaderMouseDown"
        class="h-12 px-4 bg-white/[0.025] border-b border-white/[0.08] flex items-center justify-between cursor-move shrink-0"
      >
        <!-- 左侧：Mac 交通灯控制 + 标题 + 自定义策略下拉弹窗 -->
        <div class="flex items-center space-x-3">
          <!-- 优雅极简红黄绿点控制 -->
          <div class="flex items-center space-x-1.5 pr-2 border-r border-white/[0.08]">
            <button
              @click="strategyStore.isBacktestCockpitOpen = false"
              class="w-3 h-3 rounded-full bg-red-500/80 hover:bg-red-500 transition-colors flex items-center justify-center text-[8px] text-black/60 hover:text-black font-bold cursor-pointer"
              title="关闭 (⌘+B)"
            >✕</button>
            <button
              @click="strategyStore.isBacktestCockpitOpen = false"
              class="w-3 h-3 rounded-full bg-amber-500/80 hover:bg-amber-500 transition-colors flex items-center justify-center text-[8px] text-black/60 hover:text-black font-bold cursor-pointer"
              title="最小化"
            >–</button>
            <button
              @click="isMaximized = !isMaximized"
              class="w-3 h-3 rounded-full bg-emerald-500/80 hover:bg-emerald-500 transition-colors flex items-center justify-center text-[8px] text-black/60 hover:text-black font-bold cursor-pointer"
              title="最大化 / 还原"
            >+</button>
          </div>

          <div class="flex items-center space-x-2">
            <span class="text-sm font-bold text-white tracking-tight">量化回测工作舱</span>
            <span class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-gradient-to-r from-red-500/20 to-amber-500/20 text-amber-300 font-bold border border-amber-500/30">
              PRO
            </span>
          </div>

          <!-- 自定义高质感策略切换下拉 (Custom Strategy Popover) -->
          <div class="relative no-drag" ref="strategyDropdownRef">
            <button
              @click="showStrategyDropdown = !showStrategyDropdown"
              class="flex items-center space-x-2 px-2.5 py-1 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.1] hover:border-amber-500/40 text-xs text-white transition-all cursor-pointer shadow-sm group"
              title="点击切换策略模板"
            >
              <span class="text-amber-400 font-mono text-[11px] bg-amber-400/10 px-1 py-0.2 rounded border border-amber-400/20">λ</span>
              <span class="font-medium max-w-[150px] sm:max-w-[200px] truncate text-zinc-200 group-hover:text-white">
                {{ currentStrategyName }}
              </span>
              <span
                class="text-zinc-400 text-[9px] group-hover:text-amber-300 transition-transform duration-200"
                :class="{ 'rotate-180': showStrategyDropdown }"
              >▼</span>
            </button>

            <!-- 策略弹窗卡片 -->
            <transition name="fade">
              <div
                v-if="showStrategyDropdown"
                class="absolute left-0 mt-2 w-80 max-h-96 overflow-y-auto rounded-2xl bg-[#14161f]/98 border border-white/[0.14] shadow-2xl backdrop-blur-3xl p-2 z-50 animate-fadeIn"
              >
                <div class="px-2.5 py-1.5 text-[10px] font-bold text-zinc-400 tracking-wider uppercase border-b border-white/[0.06]">
                  🏛️ 内置经典策略模板
                </div>
                <div class="space-y-1 py-1">
                  <div
                    v-for="st in strategyStore.userStrategies.filter((s) => s.id < 0)"
                    :key="st.id"
                    @click="selectStrategyTemplate(st)"
                    :class="strategyStore.activeStrategyId === st.id ? 'bg-amber-500/15 border-amber-500/40 text-amber-200' : 'hover:bg-white/[0.06] text-zinc-300 border-transparent'"
                    class="p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col space-y-0.5 group"
                  >
                    <div class="flex items-center justify-between text-xs font-semibold text-white group-hover:text-amber-300">
                      <span>{{ st.name }}</span>
                      <span v-if="strategyStore.activeStrategyId === st.id" class="text-amber-400 font-bold">✓</span>
                    </div>
                    <div class="text-[10px] text-zinc-400 line-clamp-1 leading-normal">
                      {{ st.description || '经典量化策略逻辑' }}
                    </div>
                  </div>
                </div>

                <template v-if="strategyStore.userStrategies.some((s) => s.id > 0)">
                  <div class="px-2.5 py-1.5 text-[10px] font-bold text-zinc-400 tracking-wider uppercase border-t border-b border-white/[0.06] mt-1">
                    ⭐ 我的云端策略
                  </div>
                  <div class="space-y-1 py-1">
                    <div
                      v-for="st in strategyStore.userStrategies.filter((s) => s.id > 0)"
                      :key="st.id"
                      @click="selectStrategyTemplate(st)"
                      :class="strategyStore.activeStrategyId === st.id ? 'bg-amber-500/15 border-amber-500/40 text-amber-200' : 'hover:bg-white/[0.06] text-zinc-300 border-transparent'"
                      class="p-2.5 rounded-xl border transition-all cursor-pointer flex flex-col space-y-0.5 group"
                    >
                      <div class="flex items-center justify-between text-xs font-semibold text-white group-hover:text-amber-300">
                        <span>{{ st.name }}</span>
                        <span v-if="strategyStore.activeStrategyId === st.id" class="text-amber-400 font-bold">✓</span>
                      </div>
                      <div class="text-[10px] text-zinc-400 line-clamp-1 leading-normal">
                        {{ st.description || '自定策略' }}
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </transition>
          </div>
        </div>

        <!-- 右侧：运行按钮、全功能代码台、最大化、关闭 -->
        <div class="flex items-center space-x-2 no-drag">
          <!-- 运行回测主按钮 -->
          <button
            @click="strategyStore.runBacktest"
            :disabled="strategyStore.isBacktesting"
            class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-50 text-white font-bold text-xs shadow-lg shadow-red-500/25 flex items-center space-x-1.5 transition-all cursor-pointer group"
            title="运行回测 (⌘+Enter)"
          >
            <span v-if="!strategyStore.isBacktesting">▶</span>
            <span v-else class="w-3 h-3 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
            <span>{{ strategyStore.isBacktesting ? '撮合中...' : '运行回测' }}</span>
            <span class="text-[10px] opacity-75 font-mono group-hover:opacity-100">⌘↵</span>
          </button>

          <!-- 展开全功能代码工作台 -->
          <button
            @click="router.push('/strategy'); showToast('已切换至全功能代码工作室')"
            class="px-2.5 py-1.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.08] text-zinc-300 hover:text-white transition-colors cursor-pointer text-xs flex items-center space-x-1"
            title="打开全功能 Python 策略代码编辑器"
          >
            <span>💻</span>
            <span class="hidden sm:inline">代码台</span>
          </button>
        </div>
      </div>

      <!-- 2.2 核心参数与起止时间区间工具条 (Date Range & Mode Controls) -->
      <div class="px-4 py-3 bg-white/[0.015] border-b border-white/[0.08] space-y-3 shrink-0">
        <!-- 第一行：三大回测模式切换 + 起止时间选择 + 本金设置 -->
        <div class="flex flex-wrap items-center justify-between gap-3 text-xs">
          <!-- 模式切换高质感分段器 -->
          <div class="flex items-center space-x-1 p-0.5 rounded-xl bg-black/60 border border-white/[0.08]">
            <button
              @click="strategyStore.backtestMode = 'single'"
              :class="strategyStore.backtestMode === 'single' ? 'bg-red-500/20 text-red-300 font-bold border border-red-500/30 shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
              class="px-2.5 py-1 rounded-lg text-xs transition-all cursor-pointer"
            >
              🎯 单标的
            </button>
            <button
              @click="strategyStore.backtestMode = 'basket'"
              :class="strategyStore.backtestMode === 'basket' ? 'bg-amber-500/20 text-amber-300 font-bold border border-amber-500/30 shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
              class="px-2.5 py-1 rounded-lg text-xs transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>📦 自选股票池</span>
              <span class="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.08] text-zinc-300 font-mono">
                {{ strategyStore.symbols.length }}
              </span>
            </button>
            <button
              @click="strategyStore.backtestMode = 'holdings'; strategyStore.applyHoldingsToBacktest()"
              :class="strategyStore.backtestMode === 'holdings' ? 'bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/30 shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
              class="px-2.5 py-1 rounded-lg text-xs transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>💼 我的持仓</span>
              <span class="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.08] text-zinc-300 font-mono">
                {{ strategyStore.userHoldings.length }}
              </span>
            </button>
          </div>

          <!-- 精致双向起止时间区间选择器 (Start Date ~ End Date) -->
          <div class="flex items-center space-x-2 text-zinc-300 font-mono">
            <div class="flex items-center space-x-1.5 px-2.5 py-1 rounded-xl bg-black/60 border border-white/[0.1] hover:border-amber-500/40 text-xs transition-colors">
              <span class="text-zinc-400 text-[11px] font-sans">📅</span>
              <input
                v-model="strategyStore.startDate"
                type="date"
                style="color-scheme: dark"
                class="bg-transparent text-white focus:outline-none cursor-pointer font-mono text-xs w-[105px]"
              />
              <span class="text-zinc-500">→</span>
              <input
                v-model="strategyStore.endDate"
                type="date"
                style="color-scheme: dark"
                placeholder="至今"
                class="bg-transparent text-white focus:outline-none cursor-pointer font-mono text-xs w-[105px]"
              />
            </div>

            <!-- 快捷日期胶囊 -->
            <div class="hidden sm:flex items-center space-x-1 text-[11px]">
              <button
                v-for="r in [{ l: '近半年', v: 'half_year' }, { l: '近1年', v: '1y' }, { l: '近2年', v: '2y' }, { l: '2023至今', v: '2023' }, { l: '全历史', v: 'all' }]"
                :key="r.v"
                @click="applyDateRange(r.v as any)"
                :class="selectedQuickRange === r.v ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 font-bold shadow-sm' : 'bg-white/[0.03] text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
                class="px-2 py-0.8 rounded-lg border transition-all cursor-pointer"
              >
                {{ r.l }}
              </button>
            </div>

            <!-- 初始本金 -->
            <div class="flex items-center space-x-1 ml-2">
              <div class="relative flex items-center">
                <span class="absolute left-2.5 text-zinc-500 font-mono text-[11px]">¥</span>
                <input
                  v-model.number="strategyStore.initialCash"
                  type="number"
                  step="10000"
                  class="w-24 pl-5 pr-2 py-1 bg-black/60 border border-white/[0.1] rounded-xl text-xs font-mono font-semibold text-white focus:outline-none focus:border-amber-500/50"
                  title="初始本金"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- 第二行：根据模式展示标的配置区 -->
        <!-- A. 单标的模式 -->
        <div v-if="strategyStore.backtestMode === 'single'" class="flex flex-wrap items-center justify-between gap-2 pt-0.5">
          <div class="flex items-center space-x-2 flex-1 max-w-md">
            <span class="text-xs text-zinc-400 shrink-0 font-medium">标的代码:</span>
            <input
              v-model="singleSymbolInput"
              @change="handleSingleSymbolChange"
              @keydown.enter.prevent="handleSingleSymbolChange"
              type="text"
              placeholder="如 600519.SH.STK / 510300.SH.ETF"
              class="w-full bg-black/60 border border-white/[0.12] rounded-xl px-3 py-1 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/60 font-mono"
            />
            <button
              @click="handleSingleSymbolChange"
              class="px-2.5 py-1 rounded-xl bg-white/[0.08] hover:bg-white/[0.14] text-xs text-white transition-colors cursor-pointer shrink-0 font-medium"
            >
              应用
            </button>
            <button
              @click="router.push(`/symbol/${encodeURIComponent(strategyStore.symbol)}`)"
              class="px-2.5 py-1 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-xs text-zinc-300 hover:text-white border border-white/[0.08] transition-colors cursor-pointer shrink-0"
              title="查看该标的独立日K线详情"
            >
              👁️ 看K线
            </button>
          </div>

          <!-- 快捷热门推荐 -->
          <div class="flex items-center space-x-1.5 overflow-x-auto text-[11px]">
            <span class="text-zinc-500 text-[10px] shrink-0">推荐:</span>
            <button
              v-for="item in singleQuickPresets"
              :key="item.value"
              @click="selectSinglePreset(item)"
              :class="strategyStore.symbol === item.value ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-white/[0.03] text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
              class="px-2 py-0.5 rounded-md border transition-all cursor-pointer shrink-0"
            >
              {{ item.label }}
            </button>
          </div>
        </div>

        <!-- B. 组合股票池模式 (包含自制无原生Select的下拉弹窗) -->
        <div v-else-if="strategyStore.backtestMode === 'basket'" class="space-y-2 pt-0.5">
          <div class="flex flex-wrap items-center gap-1.5 p-2 rounded-xl bg-black/50 border border-white/[0.08]">
            <!-- 标的胶囊 -->
            <div
              v-for="sym in strategyStore.symbols"
              :key="sym"
              class="inline-flex items-center space-x-1 px-2 py-0.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs font-mono"
            >
              <span
                @click="router.push(`/symbol/${encodeURIComponent(sym)}`)"
                class="cursor-pointer hover:underline"
                title="点击查看行情详情"
              >
                {{ sym }}
              </span>
              <button
                @click="strategyStore.removeSymbolTag(sym)"
                class="text-amber-500 hover:text-red-400 cursor-pointer text-xs ml-0.5"
              >
                ×
              </button>
            </div>

            <!-- 批量输入框 -->
            <div class="flex-1 min-w-[200px] flex items-center space-x-1">
              <input
                v-model="inputSymbolToAdd"
                @keydown.enter.prevent="handleAddSymbol"
                type="text"
                placeholder="+ 粘贴或输入标的代码 (回车添加)..."
                class="w-full bg-transparent text-xs text-white placeholder-zinc-500 focus:outline-none font-mono py-0.5 px-1"
              />
              <button
                v-if="inputSymbolToAdd.trim()"
                @click="handleAddSymbol"
                class="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-600 text-[10px] font-bold text-white cursor-pointer"
              >
                添加
              </button>
            </div>
          </div>

          <!-- 自定义载入用户组合下拉 (Custom Watchlist Popover) -->
          <div class="flex items-center justify-between gap-2 text-xs">
            <div class="flex items-center space-x-2">
              <span class="text-zinc-400 text-[11px]">快速载入我的组合:</span>
              <div class="relative no-drag" ref="watchlistDropdownRef">
                <button
                  @click="showWatchlistDropdown = !showWatchlistDropdown"
                  class="flex items-center space-x-2 px-3 py-1 rounded-xl bg-white/[0.05] hover:bg-white/[0.09] border border-white/[0.1] hover:border-amber-500/40 text-xs text-zinc-200 transition-all cursor-pointer shadow-sm group"
                >
                  <span>📁</span>
                  <span>{{ strategyStore.userWatchlists.length > 0 ? '选择我的自选组合...' : '暂无自选组合' }}</span>
                  <span
                    class="text-zinc-400 text-[9px] group-hover:text-amber-300 transition-transform duration-200"
                    :class="{ 'rotate-180': showWatchlistDropdown }"
                  >▼</span>
                </button>

                <transition name="fade">
                  <div
                    v-if="showWatchlistDropdown"
                    class="absolute left-0 mt-2 w-80 max-h-80 overflow-y-auto rounded-2xl bg-[#14161f]/98 border border-white/[0.14] shadow-2xl backdrop-blur-3xl p-2 z-50 animate-fadeIn"
                  >
                    <div class="px-2.5 py-1.5 text-[10px] font-bold text-zinc-400 tracking-wider uppercase border-b border-white/[0.06] flex items-center justify-between">
                      <span>⭐ 我的自选组合</span>
                      <span class="text-[10px] text-zinc-500 font-mono">{{ strategyStore.userWatchlists.length }} 个</span>
                    </div>

                    <div v-if="strategyStore.userWatchlists.length > 0" class="space-y-1 py-1">
                      <div
                        v-for="w in strategyStore.userWatchlists"
                        :key="w.id"
                        @click="selectWatchlistTemplate(w)"
                        class="p-2.5 rounded-xl hover:bg-white/[0.06] transition-all cursor-pointer flex flex-col space-y-0.5 group"
                      >
                        <div class="flex items-center justify-between text-xs font-semibold text-white group-hover:text-amber-300">
                          <span>{{ w.name }}</span>
                          <span class="px-1.5 py-0.2 rounded-full text-[10px] bg-white/[0.08] text-zinc-300 font-mono">
                            {{ w.symbols.length }} 标的
                          </span>
                        </div>
                        <div class="text-[10px] text-zinc-400 line-clamp-1 leading-normal">
                          {{ w.description || w.symbols.join(', ') }}
                        </div>
                      </div>
                    </div>
                    <div v-else class="p-4 text-center space-y-2 text-zinc-500">
                      <div class="text-xl">📭</div>
                      <div class="text-xs text-zinc-400">暂无自定义自选组合</div>
                      <div class="text-[11px] text-zinc-500 leading-normal">
                        可在上方手动添加标的代码，点击右侧「保存为组合」创建
                      </div>
                      <button
                        @click="router.push('/portfolio'); showWatchlistDropdown = false"
                        class="mt-1 px-3 py-1 rounded-lg bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 text-[11px] font-medium transition-colors"
                      >
                        前往组合中心管理
                      </button>
                    </div>
                  </div>
                </transition>
              </div>
            </div>

            <!-- 快捷另存当前标的池为新组合 -->
            <button
              v-if="strategyStore.symbols.length > 0"
              @click="handleSaveCurrentSymbolsAsWatchlist"
              class="px-2.5 py-1 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 hover:text-white text-xs transition-colors flex items-center space-x-1 cursor-pointer shrink-0"
              title="将当前股票池标的保存为一个新自选组合"
            >
              <span>💾</span>
              <span>保存为组合</span>
            </button>
          </div>
        </div>

        <!-- C. 持仓底仓模式 -->
        <div v-else class="flex flex-wrap items-center justify-between gap-2 p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
          <div class="flex items-center space-x-2 text-xs">
            <span class="text-emerald-300 font-bold">💼 已关联当前底仓 (共 {{ strategyStore.userHoldings.length }} 只标的)</span>
            <span class="px-2 py-0.5 rounded-lg bg-emerald-500/20 text-emerald-300 font-mono text-[11px]">
              总成本约 ¥{{ holdingTotalCost.toLocaleString() }}
            </span>
          </div>

          <div class="flex items-center space-x-2">
            <button
              @click="strategyStore.applyHoldingsToBacktest(); showToast('⚡ 已同步持仓到回测池！')"
              class="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs cursor-pointer shadow-sm"
            >
              重新同步底仓
            </button>
            <button
              @click="router.push('/portfolio'); showToast('前往组合与持仓管理')"
              class="px-2.5 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 text-xs border border-white/[0.08] cursor-pointer"
            >
              管理底仓
            </button>
          </div>
        </div>
      </div>

      <!-- 2.3 错误告警区 -->
      <div
        v-if="strategyStore.backtestError"
        class="m-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-300 space-y-1 animate-fadeIn"
      >
        <div class="flex items-center space-x-1.5 font-bold text-red-400">
          <span>⚠️ 回测中断告警</span>
        </div>
        <p class="font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap">
          {{ strategyStore.backtestError }}
        </p>
      </div>

      <!-- 2.3.1 回测诊断告警区 (资金不足、0成交标的等智能诊断) -->
      <div
        v-if="strategyStore.backtestResult?.warnings?.length"
        class="m-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-200 space-y-1.5 animate-fadeIn"
      >
        <div class="flex items-center space-x-1.5 font-bold text-amber-400">
          <span>💡 回测执行诊断提示 ({{ strategyStore.backtestResult.warnings.length }})</span>
        </div>
        <ul class="list-disc list-inside font-mono text-[11px] leading-relaxed space-y-1 text-zinc-300">
          <li v-for="(w, idx) in strategyStore.backtestResult.warnings" :key="idx">
            {{ w }}
          </li>
        </ul>
      </div>

      <!-- 2.4 标签页条与归档按钮 -->
      <div class="px-4 py-2 border-b border-white/[0.08] bg-white/[0.01] flex items-center justify-between shrink-0">
        <div class="flex items-center space-x-2">
          <button
            @click="activeTab = 'chart'"
            :class="activeTab === 'chart' ? 'text-white border-b-2 border-red-500 font-bold bg-white/[0.04]' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 text-xs rounded-t-lg transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>📈</span>
            <span>净值收益曲线</span>
          </button>
          <button
            @click="activeTab = 'trades'"
            :class="activeTab === 'trades' ? 'text-white border-b-2 border-red-500 font-bold bg-white/[0.04]' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 text-xs rounded-t-lg transition-all cursor-pointer flex items-center space-x-1.5"
          >
            <span>📑</span>
            <span>成交流水明细</span>
            <span v-if="strategyStore.backtestResult?.trades?.length" class="text-[10px] text-zinc-500 font-mono">
              ({{ strategyStore.backtestResult.trades.length }})
            </span>
          </button>
        </div>

        <div class="flex items-center space-x-2">
          <span v-if="strategyStore.backtestResult" class="text-[11px] text-zinc-400 font-mono hidden sm:inline">
            期末动态权益: <strong class="text-white font-mono">¥{{ strategyStore.backtestResult.summary.final_equity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}</strong>
          </span>
          <button
            v-if="strategyStore.backtestResult"
            @click="openArchiveModal"
            class="px-2.5 py-1 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 text-white font-semibold text-xs flex items-center space-x-1 cursor-pointer shadow-sm"
          >
            <span>💾 归档回测</span>
          </button>
        </div>
      </div>

      <!-- 2.5 主体内容区 (KPI 仪表盘 + 图表 / 成交流水) -->
      <div class="flex-1 overflow-y-auto p-4 space-y-4">
        <!-- 撮合中动画 -->
        <div v-if="strategyStore.isBacktesting" class="h-64 flex flex-col items-center justify-center text-center space-y-3">
          <div class="w-9 h-9 border-2 border-red-500/20 border-t-red-500 rounded-full animate-spin"></div>
          <span class="text-xs font-mono text-zinc-300">事件驱动撮合与多标的推演中...</span>
          <span class="text-[11px] text-zinc-500">正在生成策略净值与沪深300基准对照曲线</span>
        </div>

        <!-- 未回测空状态 -->
        <div v-else-if="!strategyStore.backtestResult" class="h-64 flex flex-col items-center justify-center text-center space-y-2 text-zinc-500">
          <span class="text-3xl">⚡</span>
          <span class="text-sm font-bold text-zinc-300">回测就绪</span>
          <span class="text-xs text-zinc-500">点击右上角「▶ 运行回测 (⌘+Enter)」，毫秒级在沙箱中推进并输出多因子收益表现</span>
        </div>

        <!-- 已出结果 -->
        <template v-else>
          <!-- 6 大核心 KPI 仪表网格 -->
          <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2.5">
            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">累计总收益</div>
              <div
                :class="strategyStore.backtestResult.summary.total_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                class="text-base font-bold font-mono mt-1"
              >
                {{ strategyStore.backtestResult.summary.total_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.total_return * 100).toFixed(2) }}%
              </div>
            </div>

            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">年化收益率</div>
              <div
                :class="strategyStore.backtestResult.summary.annualized_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
                class="text-base font-bold font-mono mt-1"
              >
                {{ strategyStore.backtestResult.summary.annualized_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.annualized_return * 100).toFixed(2) }}%
              </div>
            </div>

            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">最大动态回撤</div>
              <div class="text-base font-bold font-mono text-emerald-400 mt-1">
                -{{ (strategyStore.backtestResult.summary.max_drawdown * 100).toFixed(2) }}%
              </div>
            </div>

            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">夏普比率 (Sharpe)</div>
              <div class="text-base font-bold font-mono text-amber-300 mt-1">
                {{ strategyStore.backtestResult.summary.sharpe_ratio.toFixed(2) }}
              </div>
            </div>

            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">交易胜率</div>
              <div class="text-base font-bold font-mono text-white mt-1">
                {{ (strategyStore.backtestResult.summary.win_rate * 100).toFixed(1) }}%
              </div>
            </div>

            <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
              <div class="text-[11px] text-zinc-400">撮合成交笔数</div>
              <div class="text-base font-bold font-mono text-white mt-1">
                {{ strategyStore.backtestResult.summary.total_trades }} 笔
              </div>
            </div>
          </div>

          <!-- 图表视图 -->
          <div v-show="activeTab === 'chart'" class="w-full">
            <EChartWrapper :option="chartOption" height="270px" />
          </div>

          <!-- 成交流水视图 -->
          <div v-show="activeTab === 'trades'" class="overflow-x-auto max-h-64 rounded-xl border border-white/[0.08] bg-black/40">
            <table class="w-full text-left text-xs font-mono">
              <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08]">
                <tr>
                  <th class="p-2.5">时间</th>
                  <th class="p-2.5">标的代码</th>
                  <th class="p-2.5">买卖</th>
                  <th class="p-2.5">成交价格</th>
                  <th class="p-2.5">成交数量</th>
                  <th class="p-2.5">成交总额</th>
                  <th class="p-2.5">调仓理由</th>
                  <th class="p-2.5">手续费</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/[0.04]">
                <tr v-for="(t, idx) in strategyStore.backtestResult.trades" :key="idx" class="hover:bg-white/[0.02]">
                  <td class="p-2.5 text-zinc-400">{{ t.datetime_str }}</td>
                  <td class="p-2.5">
                    <span
                      @click="router.push(`/symbol/${encodeURIComponent(t.symbol)}`)"
                      class="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 font-bold border border-amber-500/20 cursor-pointer hover:bg-amber-500/30"
                      title="查看标的行情详情"
                    >
                      {{ t.symbol }}
                    </span>
                  </td>
                  <td class="p-2.5">
                    <span
                      :class="t.side.toUpperCase() === 'BUY' ? 'text-red-400 bg-red-500/10 border-red-500/20' : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'"
                      class="px-1.5 py-0.5 rounded border text-[11px] font-bold"
                    >
                      {{ t.side.toUpperCase() === 'BUY' ? '买入' : '卖出' }}
                    </span>
                  </td>
                  <td class="p-2.5 text-white font-bold">¥{{ t.price.toFixed(3) }}</td>
                  <td class="p-2.5 text-zinc-300">{{ t.quantity.toLocaleString() }} 股</td>
                  <td class="p-2.5 text-zinc-200 font-bold">¥{{ (t.amount || (t.price * t.quantity)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}</td>
                  <td class="p-2.5">
                    <span
                      class="px-2 py-0.5 rounded-lg bg-white/[0.04] text-zinc-300 text-[11px] font-sans border border-white/[0.06] truncate max-w-[150px] inline-block"
                      :title="t.reason || '策略信号'"
                    >
                      {{ t.reason || '策略信号' }}
                    </span>
                  </td>
                  <td class="p-2.5 text-zinc-400">¥{{ t.commission.toFixed(2) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- 2.6 四角与边缘拉伸手柄 (4-Corner Resizers) -->
      <div @mousedown="onCornerMouseDown('nw', $event)" class="absolute top-0 left-0 w-3 h-3 cursor-nwse-resize z-50"></div>
      <div @mousedown="onCornerMouseDown('ne', $event)" class="absolute top-0 right-0 w-3 h-3 cursor-nesw-resize z-50"></div>
      <div @mousedown="onCornerMouseDown('sw', $event)" class="absolute bottom-0 left-0 w-3 h-3 cursor-nesw-resize z-50"></div>
      <div @mousedown="onCornerMouseDown('se', $event)" class="absolute bottom-0 right-0 w-3 h-3 cursor-nwse-resize z-50"></div>
    </div>

    <!-- 3. 归档弹窗 -->
    <div
      v-if="showArchiveModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#181920] border border-white/[0.12] rounded-2xl p-5 space-y-4 shadow-2xl">
        <div class="flex items-center justify-between pb-2 border-b border-white/[0.08]">
          <h3 class="text-sm font-bold text-white">归档本次回测记录</h3>
          <button @click="showArchiveModal = false" class="text-zinc-400 hover:text-white cursor-pointer">✕</button>
        </div>
        <div class="text-xs space-y-2">
          <label class="block text-zinc-400">归档名称</label>
          <input
            v-model="archiveNameInput"
            type="text"
            class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white focus:outline-none focus:border-amber-500/50 font-mono"
          />
        </div>
        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.08]">
          <button @click="showArchiveModal = false" class="px-3 py-1.5 rounded-xl bg-white/[0.04] text-zinc-300 text-xs cursor-pointer">取消</button>
          <button @click="confirmArchiveBacktest" class="px-4 py-1.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-white font-bold text-xs cursor-pointer shadow-sm">确认归档</button>
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
  </teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
