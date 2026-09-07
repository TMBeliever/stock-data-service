<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStrategyStore } from '@/stores/strategy'
import {
  parseStrategyParams,
  updateCodeParam,
  applyAllParamsToCode,
  type ParsedStrategyParam,
  type StrategyMetaInfo,
} from '@/utils/strategyParamParser'

const props = defineProps<{
  code: string
}>()

const emit = defineEmits<{
  (e: 'update:code', newCode: string): void
  (e: 'switchToCode'): void
  (e: 'runBacktest'): void
}>()

const strategyStore = useStrategyStore()

// 1. 实时解析代码提取元数据与参数列表
const parsedInfo = computed<StrategyMetaInfo>(() => {
  return parseStrategyParams(props.code)
})

// 分组配置与高端暗黑主题视觉定义
const GROUP_CONFIG: Record<string, { label: string; icon: string; border: string; bg: string; badge: string; accent: string }> = {
  buy: {
    label: '买入与建仓决策',
    icon: '🟢',
    border: 'border-emerald-500/25',
    bg: 'bg-emerald-500/[0.03]',
    badge: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30',
    accent: 'accent-emerald-400',
  },
  sell: {
    label: '卖出止盈与风控',
    icon: '🔴',
    border: 'border-rose-500/25',
    bg: 'bg-rose-500/[0.03]',
    badge: 'text-rose-400 bg-rose-500/15 border-rose-500/30',
    accent: 'accent-rose-400',
  },
  capital: {
    label: '资金仓位与规模',
    icon: '💰',
    border: 'border-amber-500/25',
    bg: 'bg-amber-500/[0.03]',
    badge: 'text-amber-400 bg-amber-500/15 border-amber-500/30',
    accent: 'accent-amber-400',
  },
  general: {
    label: '基础周期与参数',
    icon: '⚙️',
    border: 'border-sky-500/25',
    bg: 'bg-sky-500/[0.03]',
    badge: 'text-sky-400 bg-sky-500/15 border-sky-500/30',
    accent: 'accent-sky-400',
  },
}

// 自动分组计算
const groupedParams = computed(() => {
  const groups: Record<string, ParsedStrategyParam[]> = {
    buy: [],
    sell: [],
    capital: [],
    general: [],
  }

  for (const param of parsedInfo.value.params) {
    const g = param.group && groups[param.group] ? param.group : 'general'
    groups[g].push(param)
  }

  return Object.entries(groups)
    .filter(([_, list]) => list.length > 0)
    .map(([key, list]) => ({
      key,
      ...GROUP_CONFIG[key],
      params: list,
    }))
})

// 2. 界面数值与代码底层值的智能双向转换
// 百分比参数友好呈现 (如代码中 0.80 -> 界面展示 80%，滑块 0~100)
function getDisplayValue(param: ParsedStrategyParam): number {
  if (param.type === 'percent') {
    return Math.round(Number(param.value) * 10000) / 100
  }
  return Number(param.value)
}

function getSliderMin(param: ParsedStrategyParam): number {
  if (param.type === 'percent') {
    return Math.round((param.min ?? 0.01) * 100)
  }
  return param.min ?? 1
}

function getSliderMax(param: ParsedStrategyParam): number {
  if (param.type === 'percent') {
    return Math.round((param.max ?? 1.0) * 100)
  }
  return param.max ?? 100
}

function getSliderStep(param: ParsedStrategyParam): number {
  if (param.type === 'percent') {
    const s = (param.step ?? 0.01) * 100
    return s >= 1 ? Math.round(s) : Math.round(s * 10) / 10
  }
  return param.step ?? 1
}

function formatBound(param: ParsedStrategyParam, boundVal: number): string {
  if (param.type === 'percent') {
    return `${Math.round(boundVal * 100)}%`
  }
  return `${boundVal}${param.unit || ''}`
}

// 修改参数并回写 Python 源码
const updateToast = ref('')
let toastTimer: any = null

function triggerToast(msg: string) {
  updateToast.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    updateToast.value = ''
  }, 2500)
}

function onInputValueChange(param: ParsedStrategyParam, rawVal: number) {
  if (isNaN(rawVal)) return
  let actualVal = rawVal
  if (param.type === 'percent') {
    actualVal = Math.round((rawVal / 100) * 10000) / 10000 // 80 -> 0.80
  } else if (param.type === 'int') {
    actualVal = Math.round(rawVal)
  }
  handleParamChange(param, actualVal)
}

function handleParamChange(param: ParsedStrategyParam, newVal: any) {
  const updatedCode = updateCodeParam(props.code, param.name, newVal)
  emit('update:code', updatedCode)
  strategyStore.updateCode(updatedCode)
  const displayVal = param.type === 'percent' ? `${Math.round(newVal * 100)}%` : `${newVal}${param.unit || ''}`
  triggerToast(`⚡ [${param.label}] 已同步代码: ${displayVal}`)
}

// 3. 一键网格寻优状态与弹窗
const showOptimizeModal = ref(false)
const selectedMetric = ref<'sharpe_ratio' | 'total_return' | 'calmar_ratio' | 'win_rate'>('sharpe_ratio')
const maxCombos = ref(36)

// 寻优测算标的与时段配置
const optSymbol = ref('510300.SH.ETF')
const optStartDate = ref('')
const optEndDate = ref('')
const optInitialCash = ref(100000)

// 快捷推荐标的预设
const PRESET_OPT_SYMBOLS = [
  { label: '腾讯控股', symbol: '00700.HK', badge: '港股核心' },
  { label: '沪深300 ETF', symbol: '510300.SH.ETF', badge: '核心宽基' },
  { label: '红利 ETF', symbol: '510880.SH.ETF', badge: '高股息' },
  { label: '创业板 ETF', symbol: '159915.SZ.ETF', badge: '成长弹性' },
  { label: '纳指 ETF', symbol: '513100.SH.ETF', badge: '全球科技' },
  { label: '贵州茅台', symbol: '600519.SH', badge: '消费龙头' },
  { label: '宁德时代', symbol: '300750.SZ', badge: '新能源' },
]

function formatSymbolInput(raw: string): string {
  let s = (raw || '').trim().toUpperCase()
  if (!s) return s
  if (/^\d{5}$/.test(s)) {
    return `${s}.HK`
  }
  if (/^\d{6}$/.test(s)) {
    if (s.startsWith('6') || s.startsWith('5')) {
      return s.startsWith('5') ? `${s}.SH.ETF` : `${s}.SH`
    } else if (s.startsWith('0') || s.startsWith('3') || s.startsWith('1')) {
      return s.startsWith('1') ? `${s}.SZ.ETF` : `${s}.SZ`
    }
  }
  return s
}

function handleOptSymbolBlur() {
  optSymbol.value = formatSymbolInput(optSymbol.value)
}

function selectPresetSymbol(item: { label: string; symbol: string }) {
  optSymbol.value = item.symbol
}

function setOptTimeRange(years: number) {
  const end = new Date()
  const todayStr = end.toISOString().split('T')[0]
  const start = new Date()
  start.setFullYear(start.getFullYear() - years)
  const startStr = start.toISOString().split('T')[0]
  optStartDate.value = startStr
  optEndDate.value = todayStr
}

interface ParamOptCandidate {
  name: string
  label: string
  desc?: string
  type: string
  unit: string
  enabled: boolean
  candidateStr: string
}

const optimizeCandidates = ref<ParamOptCandidate[]>([])

function initOptimizeModal() {
  optSymbol.value = strategyStore.symbol || '510300.SH.ETF'
  optStartDate.value = strategyStore.startDate || ''
  optEndDate.value = strategyStore.endDate || ''
  optInitialCash.value = strategyStore.initialCash || 100000
  if (!optStartDate.value) {
    setOptTimeRange(1)
  }

  const candidates: ParamOptCandidate[] = []
  const numParams = parsedInfo.value.params.filter((p) => p.type === 'int' || p.type === 'float' || p.type === 'percent')

  numParams.forEach((p, idx) => {
    const enabled = idx < 2
    let list: any[] = []
    const val = Number(p.value)

    if (p.type === 'int') {
      const step = Math.max(1, Math.round(p.step || 5))
      list = [Math.max(p.min ?? 1, val - step), val, val + step]
    } else if (p.type === 'percent') {
      const pctVal = Math.round(val * 100)
      const pctStep = Math.max(1, Math.round((p.step || 0.05) * 100))
      list = [
        Math.max(Math.round((p.min ?? 0.05) * 100), pctVal - pctStep),
        pctVal,
        Math.min(Math.round((p.max ?? 0.95) * 100), pctVal + pctStep),
      ]
    } else {
      const step = p.step || 0.5
      list = [Math.max(p.min ?? 0.1, val - step), val, val + step]
    }

    const unique = Array.from(new Set(list))
    candidates.push({
      name: p.name,
      label: p.label,
      desc: p.desc || p.description || '',
      type: p.type,
      unit: p.unit,
      enabled,
      candidateStr: p.type === 'percent' ? unique.map((n) => `${n}%`).join(', ') : unique.join(', '),
    })
  })

  optimizeCandidates.value = candidates
  showOptimizeModal.value = true
}

// 计算预计总测试组合数
const calculatedCombosCount = computed(() => {
  const active = optimizeCandidates.value.filter((c) => c.enabled)
  if (active.length === 0) return 0
  let prod = 1
  for (const item of active) {
    const items = item.candidateStr
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    if (items.length > 0) {
      prod *= items.length
    }
  }
  return prod
})

// 执行寻优
async function startGridOptimization() {
  const active = optimizeCandidates.value.filter((c) => c.enabled)
  if (active.length === 0) {
    alert('请至少勾选一个需要寻优的参数！')
    return
  }

  const cleanSymbol = formatSymbolInput(optSymbol.value)
  if (!cleanSymbol) {
    alert('请输入有效的测算标的代码！')
    return
  }
  optSymbol.value = cleanSymbol

  const grid: Record<string, any[]> = {}
  for (const item of active) {
    const origParam = parsedInfo.value.params.find((p) => p.name === item.name)
    const rawItems = item.candidateStr
      .split(',')
      .map((s) => s.trim().replace(/%$/, ''))
      .filter((s) => s.length > 0)

    const parsedValues = rawItems.map((valStr) => {
      const num = parseFloat(valStr)
      if (origParam?.type === 'percent') {
        return num > 1 ? Math.round((num / 100) * 10000) / 10000 : num
      } else if (origParam?.type === 'int') {
        return Math.round(num)
      }
      return num
    })

    if (parsedValues.length > 0) {
      grid[item.name] = parsedValues
    }
  }

  await strategyStore.runGridOptimization({
    param_grid: grid,
    metric: selectedMetric.value,
    max_combinations: maxCombos.value,
    customCode: props.code,
    customSymbol: cleanSymbol,
    customStart: optStartDate.value,
    customEnd: optEndDate.value,
    customInitialCash: optInitialCash.value,
  })
}

// 应用寻优得到的某组参数
function applyOptimizedParams(paramsMap: Record<string, any>) {
  const updatedCode = applyAllParamsToCode(props.code, paramsMap)
  emit('update:code', updatedCode)
  strategyStore.updateCode(updatedCode)
  triggerToast(`🎉 已成功将参数组合无损写入策略「${strategyStore.activeStrategyName}」！`)
  showOptimizeModal.value = false
}

// 决策穿透与买卖点诊断状态
interface DrilldownDetail {
  comboId: number
  params: Record<string, any>
  loading: boolean
  error: string | null
  trades: any[]
  summary: any
  dailyRecords: any[]
  activeTradeFilter: 'all' | 'buy' | 'sell'
}

const activeDrilldown = ref<DrilldownDetail | null>(null)

// 穿透测算某组参数的买卖点流水与决策动因
async function inspectComboTrades(comboId: number, params: Record<string, any>) {
  if (activeDrilldown.value?.comboId === comboId) {
    activeDrilldown.value = null
    return
  }

  activeDrilldown.value = {
    comboId,
    params,
    loading: true,
    error: null,
    trades: [],
    summary: null,
    dailyRecords: [],
    activeTradeFilter: 'all',
  }

  try {
    const updatedCode = applyAllParamsToCode(props.code, params)
    const cleanSymbol = formatSymbolInput(optSymbol.value) || '510300.SH.ETF'
    const resp = await fetch('/api/v1/backtest/run-custom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: updatedCode,
        symbol: cleanSymbol,
        symbols: [cleanSymbol],
        start: optStartDate.value || '2021-01-01',
        end: optEndDate.value || null,
        initial_cash: optInitialCash.value || 100000,
        dry_run: false,
      }),
    })

    const data = await resp.json()
    if (!resp.ok) {
      throw new Error(data.detail || '获取买卖点明细失败')
    }

    if (activeDrilldown.value && activeDrilldown.value.comboId === comboId) {
      activeDrilldown.value.loading = false
      activeDrilldown.value.trades = data.trades || []
      activeDrilldown.value.summary = data.summary || {}
      activeDrilldown.value.dailyRecords = data.daily_records || []
    }
  } catch (err: any) {
    if (activeDrilldown.value && activeDrilldown.value.comboId === comboId) {
      activeDrilldown.value.loading = false
      activeDrilldown.value.error = err.message || '回测买卖点请求异常'
    }
  }
}

// 一键应用并直达主看板全量复盘 (带大图与买卖点标记)
async function applyAndLaunchBacktest(paramsMap: Record<string, any>) {
  const updatedCode = applyAllParamsToCode(props.code, paramsMap)
  emit('update:code', updatedCode)
  strategyStore.updateCode(updatedCode)

  const cleanSymbol = formatSymbolInput(optSymbol.value) || '510300.SH.ETF'
  strategyStore.symbol = cleanSymbol
  strategyStore.symbols = [cleanSymbol]
  if (optStartDate.value) strategyStore.startDate = optStartDate.value
  if (optEndDate.value) strategyStore.endDate = optEndDate.value
  strategyStore.initialCash = optInitialCash.value

  showOptimizeModal.value = false
  triggerToast(`🚀 已应用参数并直达全量回测！正在绘制大图与买卖点标记...`)

  emit('runBacktest')
  await strategyStore.runBacktest()
}

// 生成迷你 SVG 收益率走势折线图
function generateSvgData(records: any[], width = 460, height = 75) {
  if (!records || records.length < 2) {
    return { path: '', areaPath: '', isProfit: true }
  }
  const vals = records.map((r) => Number(r.return_pct ?? r.equity ?? 0))
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1e-6
  const isProfit = vals[vals.length - 1] >= vals[0]

  const points = vals.map((val, idx) => {
    const x = (idx / (vals.length - 1)) * (width - 12) + 6
    const y = height - 8 - ((val - min) / range) * (height - 16)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const path = `M ${points.join(' L ')}`
  const firstX = 6
  const lastX = width - 6
  const areaPath = `M ${points.join(' L ')} L ${lastX},${height} L ${firstX},${height} Z`
  return { path, areaPath, isProfit }
}

// 在寻优弹窗中快捷切换测算策略
function switchStrategyInModal(strat: any) {
  strategyStore.loadUserStrategy(strat)
  emit('update:code', strat.code)
  setTimeout(() => {
    initOptimizeModal()
  }, 50)
}

// 快捷键 Esc 关闭寻优弹窗
function handleGlobalKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && showOptimizeModal.value) {
    e.preventDefault()
    showOptimizeModal.value = false
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] text-zinc-100 overflow-hidden relative font-sans select-none">
    <!-- 参数保存微动效 Toast -->
    <Transition name="fade">
      <div
        v-if="updateToast"
        class="absolute top-3 right-4 z-40 px-3.5 py-1.5 rounded-xl bg-emerald-500/90 text-white font-mono text-xs shadow-lg backdrop-blur-md flex items-center space-x-2 animate-pulse"
      >
        <span>{{ updateToast }}</span>
      </div>
    </Transition>

    <!-- 调参台专属顶部工具条 -->
    <div class="px-4 py-2.5 bg-white/[0.02] border-b border-white/[0.08] flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center space-x-2.5 min-w-0">
        <span class="text-base">🎛️</span>
        <div class="flex items-center space-x-2 min-w-0">
          <span class="text-xs font-bold text-white tracking-wide">量化视觉调参台</span>
          <span
            v-if="parsedInfo.className"
            class="px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px] font-mono shrink-0"
          >
            {{ parsedInfo.className }}
          </span>
          <span class="text-[11px] text-zinc-400 hidden lg:inline">· 源码双向毫秒级反射引擎</span>
        </div>
      </div>

      <div class="flex items-center space-x-2 shrink-0">
        <!-- 一键参数网格寻优按钮 -->
        <button
          @click="initOptimizeModal"
          :disabled="parsedInfo.params.length === 0"
          class="px-3.5 py-1 rounded-lg bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-rose-500/20 hover:from-amber-500/30 hover:to-rose-500/30 border border-amber-500/40 text-amber-300 hover:text-amber-200 text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-sm cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          title="对当前策略的关键阈值进行多组笛卡尔积测试，评选最优收益"
        >
          <span class="text-amber-400">🎯</span>
          <span>一键参数寻优</span>
        </button>

        <!-- 切换回源码 -->
        <button
          @click="emit('switchToCode')"
          class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 hover:text-white text-xs transition-all flex items-center space-x-1 cursor-pointer"
          title="查看与手动编辑 Python 源码"
        >
          <span>💻</span>
          <span class="hidden md:inline">源码视图</span>
        </button>
      </div>
    </div>

    <!-- 滚动主体区 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- 1. 白话逻辑透视卡片 (Logic Insight Card) -->
      <div class="p-4 rounded-xl bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/[0.08] backdrop-blur-sm relative overflow-hidden group">
        <div class="absolute -right-6 -bottom-6 w-28 h-28 bg-amber-500/5 rounded-full blur-2xl pointer-events-none group-hover:bg-amber-500/10 transition-all"></div>
        
        <div class="space-y-2.5">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="text-amber-400">💡</span>
              <span class="text-xs font-bold text-white tracking-wide">策略核心逻辑概述</span>
            </div>
            <span class="text-[10px] text-zinc-500 font-mono">从源码 Docstring 自动提取</span>
          </div>

          <p class="text-xs text-zinc-300 leading-relaxed font-sans">
            {{ parsedInfo.plainSummary }}
          </p>

          <!-- 规则清单胶囊 (如果有规则列表) -->
          <div v-if="parsedInfo.rules && parsedInfo.rules.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
            <div
              v-for="(rule, rIdx) in parsedInfo.rules"
              :key="rIdx"
              class="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-black/40 border border-white/[0.06] text-xs text-zinc-300"
            >
              <span class="text-amber-400 text-xs shrink-0">✦</span>
              <span class="truncate" :title="rule">{{ rule }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 2. 分组参数控制群 (买入/卖出/资金/基础) -->
      <div v-if="groupedParams.length > 0" class="space-y-4">
        <div
          v-for="group in groupedParams"
          :key="group.key"
          :class="['p-4 rounded-xl border backdrop-blur-sm space-y-3.5', group.border, group.bg]"
        >
          <!-- 分组标题栏 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="text-sm">{{ group.icon }}</span>
              <span class="text-xs font-bold text-zinc-100 tracking-wide">{{ group.label }}</span>
              <span :class="['px-2 py-0.2 text-[10px] rounded-md border font-mono font-medium', group.badge]">
                {{ group.params.length }} 个调控项
              </span>
            </div>
          </div>

          <!-- 参数控制行网格 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            <div
              v-for="param in group.params"
              :key="param.name"
              class="p-4 rounded-xl bg-black/40 border border-white/[0.06] hover:border-white/[0.14] transition-all space-y-3"
            >
              <!-- 参数名与数值展示输入框 -->
              <div class="flex items-center justify-between gap-2">
                <div class="min-w-0">
                  <div class="flex items-center space-x-2">
                    <span class="text-xs font-semibold text-zinc-100 truncate" :title="param.label">
                      {{ param.label }}
                    </span>
                    <span class="text-[10px] text-zinc-400 font-mono px-1.5 py-0.5 rounded bg-white/[0.05] border border-white/[0.05] shrink-0">
                      self.{{ param.name }}
                    </span>
                  </div>
                </div>

                <!-- 数值显示徽标 / 输入框 -->
                <div class="flex items-center space-x-1.5 shrink-0">
                  <input
                    v-if="param.type === 'int' || param.type === 'float' || param.type === 'percent'"
                    type="number"
                    :min="getSliderMin(param)"
                    :max="getSliderMax(param)"
                    :step="getSliderStep(param)"
                    :value="getDisplayValue(param)"
                    @change="(e: any) => onInputValueChange(param, parseFloat(e.target.value))"
                    class="w-20 px-2 py-1 rounded-lg bg-white/[0.08] border border-white/[0.15] text-xs font-mono font-bold text-amber-300 text-right focus:outline-none focus:border-amber-500 focus:bg-white/[0.12] transition-all"
                  />
                  <span class="text-xs text-zinc-400 font-mono font-medium w-4">
                    {{ param.type === 'percent' ? '%' : (param.unit || '') }}
                  </span>
                </div>
              </div>

              <!-- 小白通俗人话解释说明条 (Plain-English Explainer) -->
              <div
                v-if="param.desc || param.description"
                class="flex items-start space-x-2 px-2.5 py-2 rounded-lg bg-white/[0.03] border border-white/[0.05] text-[11px] text-zinc-300 leading-relaxed font-sans"
              >
                <span class="text-amber-400 shrink-0 text-xs mt-0.5">💡</span>
                <span class="text-zinc-300/90" :title="param.desc || param.description">{{ param.desc || param.description }}</span>
              </div>

              <!-- 滑块控件 (针对数值型参数) -->
              <div v-if="param.type === 'int' || param.type === 'float' || param.type === 'percent'" class="pt-1">
                <input
                  type="range"
                  :min="getSliderMin(param)"
                  :max="getSliderMax(param)"
                  :step="getSliderStep(param)"
                  :value="getDisplayValue(param)"
                  @input="(e: any) => onInputValueChange(param, parseFloat(e.target.value))"
                  :class="['w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer transition-all', group.accent]"
                />
                <div class="flex justify-between text-[10px] text-zinc-500 font-mono mt-1.5">
                  <span>{{ formatBound(param, param.min) }}</span>
                  <span class="text-zinc-400 font-medium">当前: {{ getDisplayValue(param) }}{{ param.type === 'percent' ? '%' : param.unit }}</span>
                  <span>{{ formatBound(param, param.max) }}</span>
                </div>
              </div>

              <!-- 布尔值开关控件 -->
              <div v-else-if="param.type === 'bool'" class="flex items-center justify-between pt-1">
                <span class="text-xs text-zinc-400 font-sans">规则开关状态</span>
                <button
                  @click="handleParamChange(param, !param.value)"
                  :class="[
                    'px-3.5 py-1.5 rounded-lg text-xs font-mono font-medium transition-all cursor-pointer border flex items-center space-x-1.5',
                    param.value ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm shadow-emerald-500/10' : 'bg-white/5 text-zinc-400 border-white/10 hover:bg-white/10',
                  ]"
                >
                  <span>{{ param.value ? '🟢' : '⚪' }}</span>
                  <span>{{ param.value ? '已开启 (True)' : '已关闭 (False)' }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 3. 无参数提示空态 -->
      <div v-else class="p-8 text-center rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-3">
        <div class="text-3xl">🧩</div>
        <div class="text-sm font-medium text-zinc-300">当前策略暂未解析到初始化参数</div>
        <p class="text-xs text-zinc-500 max-w-md mx-auto leading-relaxed">
          你可以在 Python 策略类的 <code class="text-amber-400">def __init__(self, fast=5, slow=20):</code> 中声明形参默认值，或添加
          <code class="text-amber-400"># @param label="..." min=.. max=..</code> 注解，调参台将实时为你生成可视化控制滑块。
        </p>
        <button
          @click="emit('switchToCode')"
          class="px-4 py-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-300 text-xs font-medium transition-all cursor-pointer inline-flex items-center space-x-1.5"
        >
          <span>💻</span>
          <span>去源码中为参数添加默认值</span>
        </button>
      </div>
    </div>

    <!-- 一键参数网格寻优弹窗 (Grid Optimization Modal) -->
    <Teleport to="body">
      <div
        v-if="showOptimizeModal"
        class="fixed inset-0 z-[9999] overflow-y-auto bg-black/80 backdrop-blur-md p-3 sm:p-6 flex justify-center items-start sm:items-center select-none animate-fadeIn"
        @click.self="showOptimizeModal = false"
      >
        <div class="w-full max-w-3xl my-auto bg-[#16171c] border border-white/[0.14] rounded-2xl shadow-[0_25px_60px_-15px_rgba(0,0,0,0.95)] overflow-hidden flex flex-col max-h-[88vh]">
          <!-- 弹窗 Header (单行清爽，绝不折行截断) -->
          <div class="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02] shrink-0">
            <div class="flex items-center space-x-2.5">
              <span class="text-lg shrink-0">🎯</span>
              <div>
                <div class="flex items-center space-x-2">
                  <h3 class="text-sm font-bold text-white tracking-wide">一键参数网格寻优 (Grid Optimization)</h3>
                  <span class="text-[10px] text-amber-400/90 font-mono px-1.5 py-0.2 rounded bg-amber-500/10 border border-amber-500/20">
                    ⚡ 内存极速测算
                  </span>
                </div>
                <p class="text-[11px] text-zinc-400 mt-0.5">单次行情切片内存高速测算，发掘夏普比率与收益率最优参数组合</p>
              </div>
            </div>
            <button
              @click="showOptimizeModal = false"
              class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm p-1.5 rounded-lg hover:bg-white/[0.06] shrink-0"
              title="关闭 (Esc)"
            >
              ✕
            </button>
          </div>

          <!-- 弹窗主体 -->
          <div class="flex-1 overflow-y-auto p-5 space-y-5 text-xs">
            <!-- 0. 测算策略、标的与数据时段总控卡片 (清晰对齐，绝不重叠) -->
            <div class="p-4 rounded-xl bg-white/[0.03] border border-amber-500/20 space-y-3.5">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                  <span class="text-amber-400 font-bold">🎯</span>
                  <span class="font-bold text-zinc-200 text-xs">测算策略、标的与数据时段</span>
                </div>
                <span class="text-[10px] text-zinc-400">单次行情切片极速测算 · 自动联动主工作台</span>
              </div>

              <!-- 1. 测算策略行 -->
              <div class="flex flex-col sm:flex-row sm:items-center gap-2 pb-3 border-b border-white/[0.05]">
                <div class="flex items-center space-x-2 shrink-0">
                  <span class="text-zinc-400 text-[11px] shrink-0 w-16">测算策略:</span>
                  <!-- 策略下拉选择器：宽度固定自适应，右侧带指示箭头，绝不挤压 -->
                  <div class="relative">
                    <select
                      :value="strategyStore.activeStrategyId"
                      @change="(e: any) => {
                        const found = strategyStore.userStrategies.find(s => s.id === Number(e.target.value))
                        if (found) switchStrategyInModal(found)
                      }"
                      class="w-64 max-w-xs px-2.5 py-1.5 rounded-lg bg-black/50 border border-amber-500/40 text-xs font-semibold text-amber-300 focus:outline-none focus:border-amber-400 cursor-pointer appearance-none pr-8 transition-all"
                    >
                      <option
                        v-for="s in strategyStore.userStrategies"
                        :key="s.id"
                        :value="s.id"
                      >
                        {{ s.name }}
                      </option>
                    </select>
                    <span class="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-amber-400/60 pointer-events-none">▼</span>
                  </div>
                </div>

                <!-- 类名与状态徽章 -->
                <div class="flex items-center space-x-2 flex-wrap gap-1 min-w-0">
                  <span
                    v-if="parsedInfo.className"
                    class="px-2 py-1 rounded-md bg-white/[0.04] border border-white/[0.08] text-[11px] text-zinc-300 font-mono truncate"
                    :title="`Python 策略类: class ${parsedInfo.className}`"
                  >
                    <span class="text-amber-400/80 font-bold">class</span> {{ parsedInfo.className }}
                  </span>
                  <span
                    v-if="strategyStore.activeStrategyId && strategyStore.activeStrategyId > 0"
                    class="px-2 py-0.5 rounded text-[10px] bg-emerald-500/15 border border-emerald-500/25 text-emerald-400 shrink-0"
                  >
                    云端策略
                  </span>
                  <span
                    v-else
                    class="px-2 py-0.5 rounded text-[10px] bg-amber-500/15 border border-amber-500/25 text-amber-300 shrink-0"
                  >
                    草稿策略
                  </span>
                </div>
              </div>

              <!-- 2. 目标标的选择行 -->
              <div class="flex flex-col sm:flex-row sm:items-center gap-2">
                <div class="flex items-center space-x-2 shrink-0">
                  <span class="text-zinc-400 text-[11px] shrink-0 w-16">目标标的:</span>
                  <input
                    type="text"
                    v-model="optSymbol"
                    @blur="handleOptSymbolBlur"
                    placeholder="输入代码如 00700.HK / 510300"
                    class="px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/[0.12] text-xs font-mono font-bold text-amber-300 w-48 focus:outline-none focus:border-amber-500 transition-all"
                  />
                </div>

                <!-- 热门推荐标的胶囊按钮 -->
                <div class="flex flex-wrap items-center gap-1.5 flex-1">
                  <button
                    v-for="preset in PRESET_OPT_SYMBOLS"
                    :key="preset.symbol"
                    @click="selectPresetSymbol(preset)"
                    type="button"
                    :class="[
                      'px-2 py-0.5 rounded-md text-[11px] font-sans transition-all cursor-pointer border flex items-center space-x-1',
                      optSymbol === preset.symbol
                        ? 'bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm'
                        : 'bg-white/[0.02] text-zinc-400 border-white/[0.08] hover:text-zinc-200 hover:border-white/[0.16]',
                    ]"
                  >
                    <span>{{ preset.label }}</span>
                    <span class="text-[9px] opacity-60 font-mono">({{ preset.symbol.split('.')[0] }})</span>
                  </button>
                </div>
              </div>

              <!-- 3. 回测时段行 -->
              <div class="flex flex-col sm:flex-row sm:items-center gap-2 pt-1 border-t border-white/[0.04]">
                <div class="flex items-center space-x-2 shrink-0">
                  <span class="text-zinc-400 text-[11px] shrink-0 w-16">回测时段:</span>
                  <input
                    type="date"
                    v-model="optStartDate"
                    class="px-2 py-1 rounded-lg bg-black/40 border border-white/[0.12] text-[11px] font-mono text-zinc-200 focus:outline-none focus:border-amber-500 transition-all"
                  />
                  <span class="text-zinc-500 text-xs">至</span>
                  <input
                    type="date"
                    v-model="optEndDate"
                    class="px-2 py-1 rounded-lg bg-black/40 border border-white/[0.12] text-[11px] font-mono text-zinc-200 focus:outline-none focus:border-amber-500 transition-all"
                  />
                </div>

                <!-- 快捷区间胶囊 -->
                <div class="flex items-center space-x-1.5">
                  <button
                    v-for="yr in [1, 3, 5, 10]"
                    :key="yr"
                    @click="setOptTimeRange(yr)"
                    type="button"
                    class="px-2 py-0.5 rounded-md text-[11px] bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] hover:border-white/[0.15] text-zinc-400 hover:text-zinc-200 transition-all cursor-pointer font-sans"
                  >
                    近{{ yr }}年
                  </button>
                </div>
              </div>

              <!-- 4. 初始本金行 -->
              <div class="flex flex-col sm:flex-row sm:items-center gap-2 pt-2 border-t border-white/[0.04]">
                <div class="flex items-center space-x-2 shrink-0">
                  <span class="text-zinc-400 text-[11px] shrink-0 w-16">初始本金:</span>
                  <div class="relative flex items-center">
                    <span class="absolute left-2.5 text-amber-400/80 font-mono text-xs">¥</span>
                    <input
                      type="number"
                      v-model.number="optInitialCash"
                      min="10000"
                      step="10000"
                      placeholder="如 100000"
                      class="pl-6 pr-2.5 py-1 rounded-lg bg-black/40 border border-white/[0.12] text-xs font-mono font-bold text-amber-300 w-36 focus:outline-none focus:border-amber-500 transition-all"
                    />
                  </div>
                </div>

                <!-- 快捷本金预设胶囊 -->
                <div class="flex flex-wrap items-center gap-1.5">
                  <button
                    v-for="preset in [
                      { label: '10万 (默认)', val: 100000 },
                      { label: '30万', val: 300000 },
                      { label: '50万 (蓝筹港股推荐)', val: 500000 },
                      { label: '100万', val: 1000000 },
                    ]"
                    :key="preset.val"
                    @click="optInitialCash = preset.val"
                    type="button"
                    :class="[
                      'px-2 py-0.5 rounded-md text-[11px] font-sans transition-all cursor-pointer border flex items-center',
                      optInitialCash === preset.val
                        ? 'bg-amber-500/20 text-amber-300 border-amber-500/50 shadow-sm'
                        : 'bg-white/[0.02] text-zinc-400 border-white/[0.08] hover:text-zinc-200 hover:border-white/[0.16]',
                    ]"
                  >
                    {{ preset.label }}
                  </button>
                </div>
              </div>
            </div>

            <!-- 1. 参数网格候选配置 -->
            <div class="space-y-3">
              <div class="flex items-center justify-between">
                <span class="font-bold text-zinc-200 text-xs flex items-center space-x-1.5">
                  <span>1. 选择待测试参数与候选取值</span>
                </span>
                <span class="text-[11px] text-amber-400 font-mono">
                  预计测算: {{ calculatedCombosCount }} 组组合 (上限 {{ maxCombos }} 组)
                </span>
              </div>

              <div class="space-y-2">
                <div
                  v-for="cand in optimizeCandidates"
                  :key="cand.name"
                  class="p-2.5 rounded-lg bg-black/30 border border-white/[0.06] flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                >
                  <div class="flex items-center space-x-2.5 shrink-0">
                    <input
                      type="checkbox"
                      v-model="cand.enabled"
                      class="w-4 h-4 rounded bg-white/10 border-white/20 accent-amber-500 cursor-pointer"
                    />
                    <div>
                      <div class="flex items-center space-x-1.5">
                        <span class="font-semibold text-zinc-200">{{ cand.label }}</span>
                        <span class="text-zinc-500 font-mono text-[10px]">({{ cand.name }})</span>
                      </div>
                      <div v-if="cand.desc" class="text-[10px] text-zinc-400 font-sans truncate max-w-xs mt-0.5" :title="cand.desc">
                        💡 {{ cand.desc }}
                      </div>
                    </div>
                  </div>

                  <!-- 候选值输入框 -->
                  <div class="flex-1 max-w-md">
                    <input
                      type="text"
                      v-model="cand.candidateStr"
                      :disabled="!cand.enabled"
                      :placeholder="cand.type === 'percent' ? '如 10%, 20%, 30%' : '如 5, 10, 20'"
                      class="w-full px-2.5 py-1 rounded bg-white/[0.04] border border-white/[0.1] text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500 disabled:opacity-30"
                    />
                  </div>
                </div>
              </div>
            </div>

            <!-- 2. 优化目标指标配置 -->
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              <div class="space-y-1.5">
                <label class="text-[11px] font-medium text-zinc-300">排序评选核心指标 (Metric)</label>
                <select
                  v-model="selectedMetric"
                  class="w-full px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.1] text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                >
                  <option value="sharpe_ratio">夏普比率 (Sharpe Ratio · 风险收益综合最优)</option>
                  <option value="total_return">累计总收益率 (Total Return · 进攻收益优先)</option>
                  <option value="calmar_ratio">卡玛比率 (Calmar Ratio · 收益回撤比)</option>
                  <option value="win_rate">胜率 (Win Rate · 胜率优先)</option>
                </select>
              </div>

              <div class="space-y-1.5">
                <label class="text-[11px] font-medium text-zinc-300">最大计算组合数限制</label>
                <input
                  type="number"
                  v-model.number="maxCombos"
                  min="4"
                  max="100"
                  step="4"
                  class="w-full px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.1] text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>
            </div>

            <!-- 3. 开始寻优主操作 -->
            <div class="pt-2 flex items-center justify-between">
              <button
                @click="startGridOptimization"
                :disabled="strategyStore.isOptimizing || calculatedCombosCount === 0"
                class="px-5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white font-bold text-xs flex items-center space-x-2 shadow-lg shadow-amber-500/20 transition-all cursor-pointer disabled:opacity-50"
              >
                <span v-if="!strategyStore.isOptimizing">
                  🚀 对「{{ strategyStore.activeStrategyName }}」开展 [{{ optSymbol }}] 网格寻优 (¥{{ Number(optInitialCash).toLocaleString() }})
                </span>
                <span v-else class="flex items-center space-x-1.5">
                  <span class="w-3.5 h-3.5 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
                  <span>正在测算「{{ strategyStore.activeStrategyName }}」...</span>
                </span>
              </button>

              <span v-if="strategyStore.optimizationResult" class="text-[11px] text-zinc-400 font-mono">
                ⚡ 本次寻优耗时: {{ strategyStore.optimizationResult.elapsed_ms }}ms ({{ strategyStore.optimizationResult.executed_combinations }} 组已跑通)
              </span>
            </div>

            <!-- 4. 寻优结果排行榜展示 -->
            <div v-if="strategyStore.optimizationResult && strategyStore.optimizationResult.ranking.length > 0" class="space-y-3 pt-3 border-t border-white/[0.08]">
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                  <span class="font-bold text-zinc-200 text-xs">「{{ strategyStore.activeStrategyName }}」寻优排行榜</span>
                  <span class="px-2 py-0.5 rounded-full text-[10px] bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono">
                    本金: ¥{{ Number(optInitialCash).toLocaleString() }}
                  </span>
                  <span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                    共 {{ strategyStore.optimizationResult.ranking.length }} 组已跑通
                  </span>
                </div>

                <!-- 一键应用最优组合按钮 -->
                <button
                  v-if="strategyStore.optimizationResult.best_params"
                  @click="applyOptimizedParams(strategyStore.optimizationResult.best_params)"
                  class="px-3 py-1 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white font-semibold text-xs shadow-md shadow-emerald-500/20 transition-all cursor-pointer flex items-center space-x-1"
                >
                  <span>🏆 一键应用最优组合</span>
                </button>
              </div>

              <!-- 排行榜表格 -->
              <div class="overflow-x-auto rounded-xl border border-white/[0.08] bg-black/40">
                <table class="w-full text-left border-collapse">
                  <thead>
                    <tr class="border-b border-white/[0.08] text-[11px] text-zinc-400 font-mono bg-white/[0.02]">
                      <th class="py-2 px-3">排名</th>
                      <th class="py-2 px-3">参数组合</th>
                      <th class="py-2 px-3 text-right">总收益率</th>
                      <th class="py-2 px-3 text-right">年化收益</th>
                      <th class="py-2 px-3 text-right">最大回撤</th>
                      <th class="py-2 px-3 text-right">夏普比率</th>
                      <th class="py-2 px-3 text-right">交易笔数</th>
                      <th class="py-2 px-3 text-center">操作</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-white/[0.04] text-xs font-mono">
                    <template
                      v-for="(item, idx) in strategyStore.optimizationResult.ranking.slice(0, 15)"
                      :key="item.combo_id"
                    >
                      <tr
                        :class="[
                          'hover:bg-white/[0.04] transition-colors',
                          idx === 0 ? 'bg-amber-500/[0.06] text-amber-200' : '',
                          activeDrilldown?.comboId === item.combo_id ? 'bg-amber-500/10' : '',
                        ]"
                      >
                        <td class="py-2 px-3">
                          <span v-if="idx === 0" class="text-amber-400 font-bold">🥇 Top 1</span>
                          <span v-else-if="idx === 1" class="text-zinc-300">🥈 Top 2</span>
                          <span v-else-if="idx === 2" class="text-amber-600">🥉 Top 3</span>
                          <span v-else class="text-zinc-500">#{{ idx + 1 }}</span>
                        </td>
                        <td class="py-2 px-3 text-zinc-300">
                          <span class="text-amber-300/90 font-medium">
                            {{ Object.entries(item.params).map(([k, v]) => `${k}=${v}`).join(', ') }}
                          </span>
                        </td>
                        <td class="py-2 px-3 text-right font-bold" :class="Number(item.total_return || 0) >= 0 ? 'text-red-400' : 'text-emerald-400'">
                          {{ ((item.total_return || 0) * 100).toFixed(2) }}%
                        </td>
                        <td class="py-2 px-3 text-right text-zinc-300">
                          {{ ((item.annualized_return || 0) * 100).toFixed(2) }}%
                        </td>
                        <td class="py-2 px-3 text-right text-emerald-400">
                          {{ ((item.max_drawdown || 0) * 100).toFixed(2) }}%
                        </td>
                        <td class="py-2 px-3 text-right font-bold text-amber-300">
                          {{ (item.sharpe_ratio || 0).toFixed(2) }}
                        </td>
                        <td class="py-2 px-3 text-right text-zinc-400">
                          {{ item.total_trades || 0 }}
                        </td>
                        <td class="py-2 px-3 text-center">
                          <div class="flex items-center justify-center space-x-1.5">
                            <!-- 穿透买卖点按钮 -->
                            <button
                              @click="inspectComboTrades(item.combo_id, item.params)"
                              :class="[
                                'px-2 py-0.5 rounded text-[11px] transition-all cursor-pointer flex items-center space-x-1 border',
                                activeDrilldown?.comboId === item.combo_id
                                  ? 'bg-amber-500 text-black font-bold border-amber-400 shadow-sm'
                                  : 'bg-amber-500/15 hover:bg-amber-500/25 border-amber-500/30 text-amber-300 hover:text-white',
                              ]"
                              title="穿透查看买卖点流水、决策动因与迷你净值走势"
                            >
                              <span>🔍 {{ activeDrilldown?.comboId === item.combo_id ? '收起' : '买卖明细' }}</span>
                            </button>

                            <!-- 一键直达主看板全量复盘 -->
                            <button
                              @click="applyAndLaunchBacktest(item.params)"
                              class="px-2 py-0.5 rounded bg-gradient-to-r from-emerald-600/80 to-teal-600/80 hover:from-emerald-500 hover:to-teal-500 border border-emerald-500/40 text-[11px] text-white font-semibold shadow-sm transition-all cursor-pointer flex items-center space-x-1"
                              title="应用此参数并关闭弹窗，立即在主看板启动全量回测与大图复盘"
                            >
                              <span>🚀 直达回测</span>
                            </button>

                            <!-- 仅写入代码 -->
                            <button
                              @click="applyOptimizedParams(item.params)"
                              class="px-1.5 py-0.5 rounded bg-white/[0.06] hover:bg-white/[0.12] border border-white/[0.1] text-[10px] text-zinc-400 hover:text-zinc-200 transition-all cursor-pointer"
                              title="仅将参数写回策略源码"
                            >
                              应用代码
                            </button>
                          </div>
                        </td>
                      </tr>

                      <!-- 展开子行：决策穿透与买卖点诊断抽屉 -->
                      <tr v-if="activeDrilldown?.comboId === item.combo_id" class="bg-black/70 border-y-2 border-amber-500/40">
                        <td colspan="8" class="p-4 space-y-3 font-sans">
                          <!-- 抽屉顶部状态栏 -->
                          <div class="flex items-center justify-between pb-2 border-b border-white/[0.08]">
                            <div class="flex items-center space-x-2 flex-wrap gap-1">
                              <span class="text-sm font-bold text-amber-300">🔍 #{{ item.combo_id }} 决策穿透诊断</span>
                              <span class="text-xs text-zinc-400 font-mono">
                                ({{ Object.entries(item.params).map(([k, v]) => `${k}=${v}`).join(', ') }})
                              </span>
                              <span class="px-2 py-0.5 rounded text-[10px] bg-white/[0.06] text-zinc-300 font-mono">
                                标的: {{ optSymbol }} | 本金: ¥{{ Number(optInitialCash).toLocaleString() }}
                              </span>
                            </div>

                            <div class="flex items-center space-x-2">
                              <button
                                @click="applyAndLaunchBacktest(item.params)"
                                class="px-3 py-1 rounded-lg bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white font-bold text-xs shadow-md shadow-amber-500/20 transition-all cursor-pointer flex items-center space-x-1"
                              >
                                <span>🚀 立即应用并直达主面板全量复盘</span>
                              </button>
                              <button
                                @click="activeDrilldown = null"
                                class="text-zinc-400 hover:text-white text-xs px-2 py-1 rounded hover:bg-white/[0.08] cursor-pointer"
                              >
                                ✕ 收起
                              </button>
                            </div>
                          </div>

                          <!-- 穿透测算加载中 -->
                          <div v-if="activeDrilldown.loading" class="py-8 flex flex-col items-center justify-center space-y-2 text-zinc-400">
                            <div class="w-6 h-6 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
                            <span class="text-xs font-mono">正在极速穿透回测该组合买卖流水与决策动因...</span>
                          </div>

                          <!-- 错误提示 -->
                          <div v-else-if="activeDrilldown.error" class="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
                            ⚠️ 穿透回测失败: {{ activeDrilldown.error }}
                          </div>

                          <!-- 穿透详情卡片与成交流水账 -->
                          <div v-else class="space-y-3">
                            <!-- 1. 走势与指标摘要 -->
                            <div class="grid grid-cols-1 lg:grid-cols-3 gap-3">
                              <!-- 迷你净值曲线走势 -->
                              <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
                                <div class="flex items-center justify-between mb-1">
                                  <span class="text-[11px] font-bold text-zinc-300">📈 净值与收益走势</span>
                                  <span
                                    class="text-[11px] font-mono font-bold"
                                    :class="Number(activeDrilldown.summary?.total_return || 0) >= 0 ? 'text-red-400' : 'text-emerald-400'"
                                  >
                                    {{ Number(activeDrilldown.summary?.total_return || 0) >= 0 ? '+' : '' }}{{ ((activeDrilldown.summary?.total_return || 0) * 100).toFixed(2) }}%
                                  </span>
                                </div>

                                <!-- SVG 走势图 -->
                                <div v-if="activeDrilldown.dailyRecords.length > 1" class="w-full h-16 relative overflow-hidden flex items-center">
                                  <svg class="w-full h-full" viewBox="0 0 460 75" preserveAspectRatio="none">
                                    <defs>
                                      <linearGradient :id="`grad-${item.combo_id}`" x1="0%" y1="0%" x2="0%" y2="100%">
                                        <stop offset="0%" :stop-color="generateSvgData(activeDrilldown.dailyRecords).isProfit ? 'rgba(239, 68, 68, 0.25)' : 'rgba(16, 185, 129, 0.25)'" />
                                        <stop offset="100%" stop-color="rgba(0,0,0,0)" />
                                      </linearGradient>
                                    </defs>
                                    <path
                                      :d="generateSvgData(activeDrilldown.dailyRecords).areaPath"
                                      :fill="`url(#grad-${item.combo_id})`"
                                    />
                                    <path
                                      :d="generateSvgData(activeDrilldown.dailyRecords).path"
                                      fill="none"
                                      :stroke="generateSvgData(activeDrilldown.dailyRecords).isProfit ? '#ef4444' : '#10b981'"
                                      stroke-width="1.8"
                                      stroke-linecap="round"
                                      stroke-linejoin="round"
                                    />
                                  </svg>
                                </div>
                                <div v-else class="text-zinc-500 text-xs text-center py-4">
                                  暂无连续每日净值记录
                                </div>

                                <div class="flex items-center justify-between text-[10px] text-zinc-500 font-mono mt-1">
                                  <span>{{ activeDrilldown.dailyRecords[0]?.date || optStartDate || '起点' }}</span>
                                  <span>{{ activeDrilldown.dailyRecords[activeDrilldown.dailyRecords.length - 1]?.date || optEndDate || '最新日' }}</span>
                                </div>
                              </div>

                              <!-- 2. 交易决策质量统计卡 -->
                              <div class="lg:col-span-2 grid grid-cols-2 sm:grid-cols-4 gap-2">
                                <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
                                  <span class="text-[10px] text-zinc-400">总成交流水</span>
                                  <div class="text-sm font-bold text-white font-mono mt-1">
                                    {{ activeDrilldown.trades.length }} <span class="text-[10px] text-zinc-400 font-normal">笔</span>
                                  </div>
                                  <span class="text-[9px] text-zinc-500 font-mono mt-0.5">
                                    买 {{ activeDrilldown.trades.filter(t => t.side.toUpperCase() === 'BUY').length }} / 卖 {{ activeDrilldown.trades.filter(t => t.side.toUpperCase() === 'SELL').length }}
                                  </span>
                                </div>

                                <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
                                  <span class="text-[10px] text-zinc-400">决策胜率 (Win Rate)</span>
                                  <div class="text-sm font-bold text-amber-300 font-mono mt-1">
                                    {{ ((activeDrilldown.summary?.win_rate || 0) * 100).toFixed(1) }}%
                                  </div>
                                  <span class="text-[9px] text-zinc-500 font-mono mt-0.5">
                                    盈利概率
                                  </span>
                                </div>

                                <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
                                  <span class="text-[10px] text-zinc-400">盈亏比 (Profit Factor)</span>
                                  <div class="text-sm font-bold text-sky-400 font-mono mt-1">
                                    {{ Number(activeDrilldown.summary?.profit_factor || 1).toFixed(2) }}
                                  </div>
                                  <span class="text-[9px] text-zinc-500 font-mono mt-0.5">
                                    总盈利 / 总亏损
                                  </span>
                                </div>

                                <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
                                  <span class="text-[10px] text-zinc-400">交易手续费磨损</span>
                                  <div class="text-sm font-bold text-zinc-300 font-mono mt-1">
                                    ¥{{ activeDrilldown.trades.reduce((acc, t) => acc + Number(t.commission || 0), 0).toFixed(2) }}
                                  </div>
                                  <span class="text-[9px] text-zinc-500 font-mono mt-0.5">
                                    佣金+规费合计
                                  </span>
                                </div>
                              </div>
                            </div>

                            <!-- 2. 买卖点成交流水账明细表 -->
                            <div class="space-y-2 pt-1">
                              <div class="flex items-center justify-between">
                                <div class="flex items-center space-x-2">
                                  <span class="text-[11px] font-bold text-zinc-200">📋 买卖成交流水明细</span>
                                  <!-- 筛选器 -->
                                  <div class="flex items-center space-x-1">
                                    <button
                                      @click="activeDrilldown.activeTradeFilter = 'all'"
                                      type="button"
                                      class="px-2 py-0.5 rounded text-[10px] font-mono transition-all cursor-pointer"
                                      :class="activeDrilldown.activeTradeFilter === 'all' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40' : 'text-zinc-400 hover:text-zinc-200'"
                                    >
                                      全部 ({{ activeDrilldown.trades.length }})
                                    </button>
                                    <button
                                      @click="activeDrilldown.activeTradeFilter = 'buy'"
                                      type="button"
                                      class="px-2 py-0.5 rounded text-[10px] font-mono transition-all cursor-pointer"
                                      :class="activeDrilldown.activeTradeFilter === 'buy' ? 'bg-red-500/20 text-red-400 border border-red-500/40' : 'text-zinc-400 hover:text-zinc-200'"
                                    >
                                      仅买入 ({{ activeDrilldown.trades.filter(t => t.side.toUpperCase() === 'BUY').length }})
                                    </button>
                                    <button
                                      @click="activeDrilldown.activeTradeFilter = 'sell'"
                                      type="button"
                                      class="px-2 py-0.5 rounded text-[10px] font-mono transition-all cursor-pointer"
                                      :class="activeDrilldown.activeTradeFilter === 'sell' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'text-zinc-400 hover:text-zinc-200'"
                                    >
                                      仅卖出 ({{ activeDrilldown.trades.filter(t => t.side.toUpperCase() === 'SELL').length }})
                                    </button>
                                  </div>
                                </div>

                                <span class="text-[10px] text-zinc-500 font-mono">
                                  共 {{ activeDrilldown.trades.length }} 笔买卖动作
                                </span>
                              </div>

                              <!-- 流水表格 -->
                              <div v-if="activeDrilldown.trades.length > 0" class="max-h-56 overflow-y-auto rounded-lg border border-white/[0.08] bg-black/40 text-[11px] font-mono">
                                <table class="w-full text-left border-collapse">
                                  <thead class="sticky top-0 bg-[#16171d] text-[10px] text-zinc-400 border-b border-white/[0.08]">
                                    <tr>
                                      <th class="py-1.5 px-2.5">#</th>
                                      <th class="py-1.5 px-2.5">成交时间</th>
                                      <th class="py-1.5 px-2.5">买卖动作</th>
                                      <th class="py-1.5 px-2.5 text-right">成交价</th>
                                      <th class="py-1.5 px-2.5 text-right">成交量</th>
                                      <th class="py-1.5 px-2.5 text-right">成交金额</th>
                                      <th class="py-1.5 px-2.5 text-right">手续费</th>
                                      <th class="py-1.5 px-3">策略决策动因 / 触发原因</th>
                                    </tr>
                                  </thead>
                                  <tbody class="divide-y divide-white/[0.04]">
                                    <tr
                                      v-for="(t, tIdx) in activeDrilldown.trades.filter(trade => {
                                        if (activeDrilldown?.activeTradeFilter === 'buy') return trade.side.toUpperCase() === 'BUY'
                                        if (activeDrilldown?.activeTradeFilter === 'sell') return trade.side.toUpperCase() === 'SELL'
                                        return true
                                      })"
                                      :key="tIdx"
                                      class="hover:bg-white/[0.04] transition-colors"
                                    >
                                      <td class="py-1 px-2.5 text-zinc-500">{{ tIdx + 1 }}</td>
                                      <td class="py-1 px-2.5 text-zinc-300 whitespace-nowrap">{{ t.datetime_str || t.date || '-' }}</td>
                                      <td class="py-1 px-2.5">
                                        <span
                                          class="px-1.5 py-0.5 rounded text-[10px] font-bold inline-flex items-center space-x-1"
                                          :class="t.side.toUpperCase() === 'BUY' ? 'bg-red-500/15 text-red-400 border border-red-500/30' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'"
                                        >
                                          <span>{{ t.side.toUpperCase() === 'BUY' ? '🟢 买入建仓' : '🔴 卖出平仓' }}</span>
                                        </span>
                                      </td>
                                      <td class="py-1 px-2.5 text-right text-zinc-200">
                                        ¥{{ Number(t.price || 0).toFixed(2) }}
                                      </td>
                                      <td class="py-1 px-2.5 text-right text-zinc-200">
                                        {{ t.quantity }} 股
                                      </td>
                                      <td class="py-1 px-2.5 text-right text-zinc-300">
                                        ¥{{ Number(t.amount || (t.price * t.quantity) || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                                      </td>
                                      <td class="py-1 px-2.5 text-right text-zinc-400">
                                        ¥{{ Number(t.commission || 0).toFixed(2) }}
                                      </td>
                                      <td class="py-1 px-3 text-zinc-300">
                                        <span v-if="t.reason" class="text-amber-300/90 font-sans">
                                          💡 {{ t.reason }}
                                        </span>
                                        <span v-else class="text-zinc-500 font-sans">
                                          {{ t.side.toUpperCase() === 'BUY' ? '指标超卖/金叉达成下单' : '指标超买/止盈平仓触发' }}
                                        </span>
                                      </td>
                                    </tr>
                                  </tbody>
                                </table>
                              </div>

                              <div v-else class="p-6 rounded-lg bg-black/30 border border-white/[0.06] text-center space-y-1.5">
                                <div class="text-amber-400 text-base">⚠️ 测算区间内未产生任何成交撮合</div>
                                <div class="text-xs text-zinc-400 font-sans max-w-md mx-auto">
                                  可能原因：该参数组合设定的买卖指标阈值过严（未满足触发条件），或由于高单价股票单手资金门槛（如腾讯一手需约4万元）超出单笔下单分配资金。
                                </div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
