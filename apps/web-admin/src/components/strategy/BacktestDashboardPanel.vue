<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useStrategyStore, type UserBacktestItem } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const activeTab = ref<'chart' | 'trades' | 'history'>('chart')
const toastMsg = ref('')
const showArchiveModal = ref(false)
const archiveNameInput = ref('')

// 快速标的预设
const symbolPresets = [
  { label: '沪深300 ETF', value: '510300.SH.ETF' },
  { label: '红利 ETF', value: '510880.SH.ETF' },
  { label: '中证500 ETF', value: '510500.SH.ETF' },
  { label: '黄金 ETF', value: '518880.SH.ETF' },
]

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 3000)
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
      data: ['策略累计收益', '标的基准收益'],
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
        name: '策略累计收益',
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
        name: '标的基准收益',
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
  archiveNameInput.value = `${strategyStore.activeStrategyName || '自定策略'} (${strategyStore.symbol.split('.')[0]})`
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

    <!-- 1. 顶部回测环境参数配置条 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-3 shrink-0">
      <!-- 标的选择 -->
      <div class="flex items-center space-x-2">
        <span class="text-xs text-zinc-400 font-medium">回测标的:</span>
        <select
          v-model="strategyStore.symbol"
          class="bg-black/50 border border-white/[0.1] rounded-lg px-2.5 py-1 text-xs text-white focus:outline-none focus:border-amber-500/50 cursor-pointer"
        >
          <option v-for="item in symbolPresets" :key="item.value" :value="item.value">
            {{ item.label }} ({{ item.value.split('.')[0] }})
          </option>
        </select>
      </div>

      <!-- 起止时间与资金 -->
      <div class="flex items-center space-x-3 text-xs text-zinc-400">
        <div class="flex items-center space-x-1">
          <span>起始:</span>
          <input
            v-model="strategyStore.startDate"
            type="date"
            class="bg-black/50 border border-white/[0.1] rounded-lg px-2 py-0.5 text-xs text-white focus:outline-none focus:border-amber-500/50 font-mono"
          />
        </div>
        <div class="hidden sm:flex items-center space-x-1">
          <span>本金:</span>
          <span class="font-mono text-white font-semibold">¥{{ strategyStore.initialCash.toLocaleString() }}</span>
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
                  <td class="p-2.5 text-zinc-200 font-semibold">{{ t.symbol }}</td>
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
  </div>
</template>
