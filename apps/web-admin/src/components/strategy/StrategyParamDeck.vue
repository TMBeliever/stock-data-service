<script setup lang="ts">
import { ref, computed, watch } from 'vue'
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

// 分组标签与图标
const GROUP_CONFIG: Record<string, { label: string; icon: string; border: string; bg: string; badge: string }> = {
  buy: {
    label: '买入与建仓决策',
    icon: '🟢',
    border: 'border-emerald-500/20',
    bg: 'bg-emerald-500/[0.03]',
    badge: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  },
  sell: {
    label: '卖出止盈与风控',
    icon: '🔴',
    border: 'border-rose-500/20',
    bg: 'bg-rose-500/[0.03]',
    badge: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
  },
  capital: {
    label: '资金仓位与规模',
    icon: '💰',
    border: 'border-amber-500/20',
    bg: 'bg-amber-500/[0.03]',
    badge: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  },
  general: {
    label: '基础周期与参数',
    icon: '⚙️',
    border: 'border-blue-500/20',
    bg: 'bg-blue-500/[0.03]',
    badge: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  },
}

// 参数分组计算
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

  // 仅返回非空的分组
  return Object.entries(groups)
    .filter(([_, list]) => list.length > 0)
    .map(([key, list]) => ({
      key,
      ...GROUP_CONFIG[key],
      params: list,
    }))
})

// 2. 修改参数并回写 Python 源码
const updateToast = ref('')
let toastTimer: any = null

function triggerToast(msg: string) {
  updateToast.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    updateToast.value = ''
  }, 2500)
}

function handleParamChange(param: ParsedStrategyParam, newVal: any) {
  const updatedCode = updateCodeParam(props.code, param.name, newVal)
  emit('update:code', updatedCode)
  strategyStore.updateCode(updatedCode)
  triggerToast(`⚡ 已更新参数 [${param.label} = ${newVal}]`)
}

// 3. 一键网格寻优状态与弹窗
const showOptimizeModal = ref(false)
const selectedMetric = ref<'sharpe_ratio' | 'total_return' | 'calmar_ratio' | 'win_rate'>('sharpe_ratio')
const maxCombos = ref(36)

// 选中的待优化参数及候选值 (字符串形式方便用户手动微调)
interface ParamOptCandidate {
  name: string
  label: string
  enabled: boolean
  candidateStr: string
}

const optimizeCandidates = ref<ParamOptCandidate[]>([])

// 当打开寻优弹窗时，根据当前参数初始化候选网格
function initOptimizeModal() {
  const candidates: ParamOptCandidate[] = []
  const numParams = parsedInfo.value.params.filter((p) => p.type === 'int' || p.type === 'float' || p.type === 'percent')

  numParams.forEach((p, idx) => {
    // 默认启用前两个参数进行网格测试
    const enabled = idx < 2
    let list: any[] = []
    const val = Number(p.value)

    if (p.type === 'int') {
      const step = Math.max(1, Math.round((p.step || 5)))
      list = [Math.max(p.min ?? 1, val - step), val, val + step]
    } else if (p.type === 'percent') {
      const step = p.step || 0.05
      list = [
        Math.max(p.min ?? 0.05, Math.round((val - step) * 100) / 100),
        Math.round(val * 100) / 100,
        Math.min(p.max ?? 0.95, Math.round((val + step) * 100) / 100),
      ]
    } else {
      const step = p.step || 0.5
      list = [Math.max(p.min ?? 0.1, val - step), val, val + step]
    }

    // 去重去非法
    const unique = Array.from(new Set(list))
    candidates.push({
      name: p.name,
      label: p.label,
      enabled,
      candidateStr: unique.join(', '),
    })
  })

  optimizeCandidates.value = candidates
  showOptimizeModal.value = true
}

// 计算当前预计总组合数
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

  const grid: Record<string, any[]> = {}
  for (const item of active) {
    const origParam = parsedInfo.value.params.find((p) => p.name === item.name)
    const rawItems = item.candidateStr
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)

    const parsedValues = rawItems.map((valStr) => {
      const num = parseFloat(valStr)
      if (origParam?.type === 'int') {
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
    customSymbol: strategyStore.symbol,
  })
}

// 应用寻优得到的某组参数
function applyOptimizedParams(paramsMap: Record<string, any>) {
  const updatedCode = applyAllParamsToCode(props.code, paramsMap)
  emit('update:code', updatedCode)
  strategyStore.updateCode(updatedCode)
  triggerToast('🎉 已成功将最优参数组合应用至策略代码！')
  showOptimizeModal.value = false
}
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] text-zinc-100 overflow-hidden relative">
    <!-- 参数保存微动效 Toast -->
    <Transition name="fade">
      <div
        v-if="updateToast"
        class="absolute top-3 right-4 z-40 px-3.5 py-1.5 rounded-xl bg-emerald-500/90 text-white font-mono text-xs shadow-lg backdrop-blur-md flex items-center space-x-2 animate-pulse"
      >
        <span>{{ updateToast }}</span>
      </div>
    </Transition>

    <!-- 顶部操作栏 -->
    <div class="px-4 py-2.5 bg-white/[0.02] border-b border-white/[0.08] flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center space-x-2">
        <span class="text-sm">🎛️</span>
        <span class="text-xs font-bold text-white tracking-wide">视觉化调参台</span>
        <span class="text-[11px] text-zinc-400 hidden sm:inline">代码双向无损绑定</span>
        <span
          v-if="parsedInfo.className"
          class="px-2 py-0.5 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px] font-mono"
        >
          {{ parsedInfo.className }}
        </span>
      </div>

      <div class="flex items-center space-x-2">
        <!-- 一键参数网格寻优按钮 -->
        <button
          @click="initOptimizeModal"
          :disabled="parsedInfo.params.length === 0"
          class="px-3 py-1 rounded-lg bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-rose-500/20 hover:from-amber-500/30 hover:to-rose-500/30 border border-amber-500/40 text-amber-300 hover:text-amber-200 text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-sm cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
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
      <!-- 1. 白话逻辑透视卡片 (Logic Insight) -->
      <div class="p-3.5 rounded-xl bg-gradient-to-br from-white/[0.04] to-white/[0.01] border border-white/[0.08] backdrop-blur-sm relative overflow-hidden group">
        <div class="absolute -right-6 -bottom-6 w-24 h-24 bg-amber-500/5 rounded-full blur-xl pointer-events-none group-hover:bg-amber-500/10 transition-all"></div>
        <div class="flex items-start space-x-3">
          <div class="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-base shrink-0 mt-0.5">
            💡
          </div>
          <div class="space-y-1 flex-1 min-w-0">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-zinc-200">策略逻辑概述</span>
              <span class="text-[10px] text-zinc-500 font-mono">从源码 Docstring 自动提取</span>
            </div>
            <p class="text-xs text-zinc-400 leading-relaxed break-words whitespace-pre-line font-sans">
              {{ parsedInfo.summary || '当前策略暂未声明类文档描述。你可以在 Python 类名下方添加多行文档注释 """..."""，调参台将在此处呈现自然语言逻辑透视。' }}
            </p>
          </div>
        </div>
      </div>

      <!-- 2. 分组参数卡片群 -->
      <div v-if="groupedParams.length > 0" class="space-y-4">
        <div
          v-for="group in groupedParams"
          :key="group.key"
          :class="['p-4 rounded-xl border backdrop-blur-sm space-y-3', group.border, group.bg]"
        >
          <!-- 分组标题栏 -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span>{{ group.icon }}</span>
              <span class="text-xs font-bold text-zinc-200">{{ group.label }}</span>
              <span :class="['px-1.5 py-0.2 text-[10px] rounded-md border font-mono', group.badge]">
                {{ group.params.length }} 个调控项
              </span>
            </div>
          </div>

          <!-- 参数控制行网格 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
            <div
              v-for="param in group.params"
              :key="param.name"
              class="p-3 rounded-lg bg-black/40 border border-white/[0.06] hover:border-white/[0.12] transition-colors space-y-2.5"
            >
              <!-- 参数名与数值展示 -->
              <div class="flex items-center justify-between">
                <div class="min-w-0">
                  <div class="text-xs font-semibold text-zinc-200 truncate" :title="param.label">
                    {{ param.label }}
                  </div>
                  <div class="text-[10px] text-zinc-500 font-mono truncate" :title="param.name">
                    self.{{ param.name }}
                  </div>
                </div>

                <!-- 数值显示徽章 -->
                <div class="flex items-center space-x-1 shrink-0 ml-2">
                  <input
                    v-if="param.type === 'int' || param.type === 'float' || param.type === 'percent'"
                    type="number"
                    :min="param.min"
                    :max="param.max"
                    :step="param.step"
                    :value="param.value"
                    @change="(e: any) => handleParamChange(param, parseFloat(e.target.value))"
                    class="w-20 px-2 py-0.5 rounded bg-white/[0.06] border border-white/[0.12] text-xs font-mono text-amber-300 text-right focus:outline-none focus:border-amber-500"
                  />
                  <span v-if="param.unit" class="text-[11px] text-zinc-400 font-mono">
                    {{ param.unit }}
                  </span>
                </div>
              </div>

              <!-- 滑块控件 (针对数值型参数) -->
              <div v-if="param.type === 'int' || param.type === 'float' || param.type === 'percent'" class="pt-1">
                <input
                  type="range"
                  :min="param.min ?? (param.type === 'percent' ? 0.01 : 1)"
                  :max="param.max ?? (param.type === 'percent' ? 1.0 : 100)"
                  :step="param.step ?? (param.type === 'percent' ? 0.01 : 1)"
                  :value="param.value"
                  @input="(e: any) => handleParamChange(param, parseFloat(e.target.value))"
                  class="w-full h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-amber-400 hover:accent-amber-300 transition-all"
                />
                <div class="flex justify-between text-[9px] text-zinc-500 font-mono mt-1">
                  <span>{{ param.min ?? 0 }}</span>
                  <span>{{ param.max ?? (param.type === 'percent' ? 1 : 100) }}</span>
                </div>
              </div>

              <!-- 布尔值开关控件 -->
              <div v-else-if="param.type === 'bool'" class="flex items-center justify-between pt-1">
                <span class="text-[11px] text-zinc-400">是否启用</span>
                <button
                  @click="handleParamChange(param, !param.value)"
                  :class="[
                    'px-3 py-1 rounded-md text-xs font-mono font-medium transition-all cursor-pointer',
                    param.value ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40' : 'bg-white/5 text-zinc-400 border border-white/10',
                  ]"
                >
                  {{ param.value ? '已开启 (True)' : '已关闭 (False)' }}
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
    <div
      v-if="showOptimizeModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fadeIn"
    >
      <div class="w-full max-w-3xl bg-[#16171c] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        <!-- 弹窗 Header -->
        <div class="px-5 py-3.5 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
          <div class="flex items-center space-x-2">
            <span class="text-base">🎯</span>
            <div>
              <h3 class="text-sm font-bold text-white">一键参数网格寻优 (Grid Optimization)</h3>
              <p class="text-[11px] text-zinc-400">单次行情切片内存并行测算，自动发掘夏普比率与收益率最高组合</p>
            </div>
          </div>
          <button
            @click="showOptimizeModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm p-1"
          >
            ✕
          </button>
        </div>

        <!-- 弹窗主体 -->
        <div class="flex-1 overflow-y-auto p-5 space-y-5 text-xs">
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
                    <span class="font-semibold text-zinc-200">{{ cand.label }}</span>
                    <span class="text-zinc-500 font-mono text-[10px] ml-1">({{ cand.name }})</span>
                  </div>
                </div>

                <!-- 候选值输入框 -->
                <div class="flex-1 max-w-md">
                  <input
                    type="text"
                    v-model="cand.candidateStr"
                    :disabled="!cand.enabled"
                    placeholder="逗号分隔候选值，如 5, 10, 20"
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
                <option value="total_return">累计总收益率 (Total Return · 进攻激进最优)</option>
                <option value="calmar_ratio">卡玛比率 (Calmar Ratio · 回撤收益比)</option>
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
              <span v-if="!strategyStore.isOptimizing">🚀 开始极速寻优测算</span>
              <span v-else class="flex items-center space-x-1.5">
                <span class="w-3.5 h-3.5 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
                <span>内存极速回测中...</span>
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
                <span class="font-bold text-zinc-200 text-xs">寻优排行榜 (Top Candidates)</span>
                <span class="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                  共 {{ strategyStore.optimizationResult.ranking.length }} 组
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
                  <tr
                    v-for="(item, idx) in strategyStore.optimizationResult.ranking.slice(0, 15)"
                    :key="item.combo_id"
                    :class="[
                      'hover:bg-white/[0.04] transition-colors',
                      idx === 0 ? 'bg-amber-500/[0.06] text-amber-200' : '',
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
                      <button
                        @click="applyOptimizedParams(item.params)"
                        class="px-2 py-0.5 rounded bg-white/[0.06] hover:bg-white/[0.12] border border-white/[0.1] text-[11px] text-zinc-200 hover:text-white transition-all cursor-pointer"
                      >
                        应用
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
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
