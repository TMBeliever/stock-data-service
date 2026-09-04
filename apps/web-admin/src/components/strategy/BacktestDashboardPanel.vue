<script setup lang="ts">
import { computed, ref } from 'vue'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useStrategyStore } from '@/stores/strategy'

const strategyStore = useStrategyStore()

const activeTab = ref<'chart' | 'trades'>('chart')

// 快速标的预设
const symbolPresets = [
  { label: '沪深300 ETF', value: '510300.SH.ETF' },
  { label: '红利 ETF', value: '510880.SH.ETF' },
  { label: '中证500 ETF', value: '510500.SH.ETF' },
  { label: '黄金 ETF', value: '518880.SH.ETF' },
]

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
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl">
    <!-- 1. 顶部回测环境参数配置条 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-3">
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

    <!-- 3. 主体内容区 -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- 空状态：等待运行 -->
      <div
        v-if="!strategyStore.backtestResult && !strategyStore.isBacktesting && !strategyStore.backtestError"
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

      <!-- 加载中动画 -->
      <div
        v-else-if="strategyStore.isBacktesting"
        class="h-full flex flex-col items-center justify-center text-center p-8 space-y-3"
      >
        <div class="w-10 h-10 border-2 border-red-500/20 border-t-red-500 rounded-full animate-spin"></div>
        <div class="text-xs font-mono text-zinc-300">
          <span>安全沙箱审计中 & 撮合事件驱动推进...</span>
        </div>
      </div>

      <!-- 回测完成：展示指标卡片、图表与明细 -->
      <template v-else-if="strategyStore.backtestResult">
        <!-- 3.1 核心 KPI 矩阵卡片 -->
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

        <!-- 3.2 标签页切换：收益曲线 vs 成交流水明细 -->
        <div class="flex items-center justify-between border-b border-white/[0.08] pb-2">
          <div class="flex items-center space-x-2">
            <button
              @click="activeTab = 'chart'"
              :class="activeTab === 'chart' ? 'text-white border-b-2 border-red-500 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
              class="px-2 py-1 text-xs transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>📈</span>
              <span>净值收益曲线</span>
            </button>
            <button
              @click="activeTab = 'trades'"
              :class="activeTab === 'trades' ? 'text-white border-b-2 border-red-500 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
              class="px-2 py-1 text-xs transition-all cursor-pointer flex items-center space-x-1"
            >
              <span>📑</span>
              <span>成交流水明细 ({{ strategyStore.backtestResult.trades?.length || 0 }})</span>
            </button>
          </div>

          <div class="text-[11px] text-zinc-500 font-mono">
            期末总资产: ¥{{ strategyStore.backtestResult.summary.final_equity.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}
          </div>
        </div>

        <!-- 3.3 图表视图 -->
        <div v-show="activeTab === 'chart'" class="w-full">
          <EChartWrapper :option="chartOption" height="280px" />
        </div>

        <!-- 3.4 成交流水记录表格 -->
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
    </div>
  </div>
</template>
