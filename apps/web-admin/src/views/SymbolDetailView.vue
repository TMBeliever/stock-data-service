<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useMarketStore, type ValuationHistoryItem } from '@/stores/market'
import { useStrategyStore } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const marketStore = useMarketStore()
const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const currentSymbol = computed(() => (route.params.symbol as string) || '600519.SH.STK')
const adjustType = ref<'qfq' | 'raw'>('qfq')
const klineLimit = ref<number>(250)
const toastMsg = ref('')

// 估值分析窗口与河流图 Tab 控制
const valuationWindow = ref<'1y' | '3y' | '5y' | '10y' | 'all'>('3y')
const valuationChartTab = ref<'pe' | 'pb' | 'erp' | 'dividend'>('pe')

// 自选组合下拉浮层
const showWatchlistPopover = ref(false)
const newWatchlistName = ref('')
const isCreatingWatchlist = ref(false)

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2500)
}

async function loadData() {
  const sym = currentSymbol.value
  if (!sym) return
  await Promise.all([
    marketStore.fetchSymbolDetail(sym),
    marketStore.fetchSymbolKline(sym, klineLimit.value, '1d', adjustType.value),
    marketStore.fetchSymbolValuation(sym, valuationWindow.value),
  ])
}

watch(
  [() => route.params.symbol, adjustType, klineLimit],
  () => {
    loadData()
  },
  { immediate: true }
)

watch(
  valuationWindow,
  () => {
    const sym = currentSymbol.value
    if (sym) {
      marketStore.fetchSymbolValuation(sym, valuationWindow.value)
    }
  }
)

onMounted(() => {
  if (authStore.isLoggedIn && strategyStore.userWatchlists.length === 0) {
    strategyStore.fetchUserWatchlists()
  }
})

// 快捷唤起悬浮回测工作舱
function runBacktest() {
  const sym = currentSymbol.value
  strategyStore.openBacktestCockpit({
    symbol: sym,
    mode: 'single',
    autoRun: true,
  })
  showToast(`⚡ 已唤起回测工作舱并载入 ${marketStore.currentDetail?.name || sym}！`)
}

// 加入或移出自选组合
async function toggleWatchlist(watchlistId: number) {
  const sym = currentSymbol.value
  const target = strategyStore.userWatchlists.find((w) => w.id === watchlistId)
  if (!target) return

  if (target.symbols.includes(sym)) {
    const ok = await marketStore.removeSymbolFromWatchlist(watchlistId, sym)
    if (ok) showToast(`已从「${target.name}」移出`)
  } else {
    const ok = await marketStore.addSymbolToWatchlist(watchlistId, sym)
    if (ok) showToast(`⭐ 已成功加入「${target.name}」！`)
  }
}

// 快速新建组合并加入当前标的
async function handleCreateWatchlist() {
  if (!newWatchlistName.value.trim()) return
  isCreatingWatchlist.value = true
  const ok = await strategyStore.saveUserWatchlist(newWatchlistName.value.trim(), '标的详情页快速创建')
  if (ok) {
    const created = strategyStore.userWatchlists[0]
    if (created) {
      await marketStore.addSymbolToWatchlist(created.id, currentSymbol.value)
      showToast(`⭐ 已创建「${newWatchlistName.value}」并加入该标的！`)
    }
    newWatchlistName.value = ''
  }
  isCreatingWatchlist.value = false
}

// 建立日期 -> 历史估值指标的 O(1) 映射，供 K 线 Tooltip 秒级精准联动
const valuationDateMap = computed(() => {
  const map = new Map<string, ValuationHistoryItem>()
  const list = marketStore.currentValuation?.history || []
  for (const item of list) {
    if (item.date) {
      map.set(item.date, item)
    }
  }
  return map
})

// 估值状态徽标工具函数
function getValuationBadge(pct?: number, status?: string) {
  if (pct !== undefined && pct !== null) {
    if (pct <= 0.10) return { label: '极度低估', color: 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' }
    if (pct <= 0.20) return { label: '低估击球区', color: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30' }
    if (pct >= 0.90) return { label: '极度泡沫', color: 'text-red-400 bg-red-500/20 border-red-500/40' }
    if (pct >= 0.80) return { label: '高估预警', color: 'text-amber-300 bg-amber-500/20 border-amber-500/30' }
    return { label: '估值合理', color: 'text-blue-300 bg-blue-500/15 border-blue-500/30' }
  }
  if (status === 'extreme_bubble') return { label: '极度泡沫', color: 'text-red-400 bg-red-500/20 border-red-500/40' }
  if (status === 'overvalued') return { label: '高估预警', color: 'text-amber-300 bg-amber-500/20 border-amber-500/30' }
  if (status === 'extremely_undervalued') return { label: '极度低估', color: 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' }
  if (status === 'undervalued') return { label: '低估击球区', color: 'text-emerald-400 bg-emerald-500/15 border-emerald-500/30' }
  return { label: '估值合理', color: 'text-blue-300 bg-blue-500/15 border-blue-500/30' }
}

// 1. ECharts 专业 K 线图 (Candlestick + MA5/10/20 + 成交量 Volume + Tooltip 当期估值联动)
const klineOption = computed(() => {
  const list = marketStore.currentKline
  if (!list || list.length === 0) {
    return {}
  }

  const dates = list.map((item) => item.date)
  const candlestickData = list.map((item) => [item.open, item.close, item.low, item.high])
  const volumes = list.map((item) => [item.date, item.volume, item.close >= item.open ? 1 : -1])
  const ma5 = list.map((item) => item.ma5)
  const ma10 = list.map((item) => item.ma10)
  const ma20 = list.map((item) => item.ma20)

  return {
    backgroundColor: 'transparent',
    animation: true,
    legend: {
      data: ['日K线', 'MA5', 'MA10', 'MA20'],
      textStyle: { color: 'rgba(255, 255, 255, 0.65)', fontSize: 11 },
      top: 0,
      right: 20,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255, 255, 255, 0.25)', type: 'dashed' } },
      backgroundColor: 'rgba(18, 19, 24, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      padding: [10, 14],
      textStyle: { color: '#ffffff', fontSize: 12 },
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        const date = params[0].name
        const kline = params.find((p: any) => p.seriesName === '日K线')
        let tip = `<div class="font-bold text-zinc-300 font-mono mb-1.5 pb-1 border-b border-white/10 flex items-center justify-between">
          <span>${date}</span>
          <span class="text-[10px] text-zinc-500 font-normal">日K线行情</span>
        </div>`

        if (kline && kline.data) {
          const [open, close, low, high] = kline.data.slice(1)
          const chg = close - open
          const pct = ((chg / open) * 100).toFixed(2)
          const colorClass = chg >= 0 ? '#ef4444' : '#10b981'
          tip += `
            <div class="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] font-mono">
              <span class="text-zinc-400">开盘: <strong class="text-white">${open}</strong></span>
              <span class="text-zinc-400">收盘: <strong style="color: ${colorClass}">${close}</strong></span>
              <span class="text-zinc-400">最高: <strong class="text-red-300">${high}</strong></span>
              <span class="text-zinc-400">最低: <strong class="text-emerald-300">${low}</strong></span>
              <span class="text-zinc-400 col-span-2">振幅/涨跌: <strong style="color: ${colorClass}">${chg >= 0 ? '+' : ''}${pct}%</strong></span>
            </div>
          `
        }

        // 均线
        params.forEach((p: any) => {
          if (p.seriesName.startsWith('MA') && p.value !== undefined && p.value !== null) {
            tip += `<div class="text-[10px] font-mono text-zinc-400 mt-0.5">${p.seriesName}: <span style="color:${p.color}">${p.value}</span></div>`
          }
        })

        // ⭐ 联动注入当期全维估值指标 (PE, 分位数, 击球标签, PB, 股债利差)
        const val = valuationDateMap.value.get(date)
        if (val) {
          const badge = getValuationBadge(val.pe_pct)
          const peText = val.pe !== undefined && val.pe !== null ? `PE(TTM): <strong class="text-amber-300 font-mono">${val.pe}</strong>` : ''
          const pePct = val.pe_pct !== undefined && val.pe_pct !== null ? `<span class="text-zinc-400 text-[10px]">(${Math.round(val.pe_pct * 100)}%分位)</span>` : ''
          const pbText = val.pb !== undefined && val.pb !== null ? `PB: <strong class="text-blue-300 font-mono">${val.pb}</strong>` : ''
          const erpText = val.erp !== undefined && val.erp !== null ? `股债利差: <strong class="text-purple-300 font-mono">${val.erp}%</strong>` : ''

          tip += `
            <div class="mt-2 pt-2 border-t border-white/10 space-y-1">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-zinc-400 flex items-center space-x-1">
                  <span>📊</span>
                  <span>当日估值与分位:</span>
                </span>
                <span class="px-1.5 py-0.2 rounded text-[10px] border ${badge.color}">${badge.label}</span>
              </div>
              <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] font-mono">
                ${peText ? `<div>${peText} ${pePct}</div>` : ''}
                ${pbText ? `<div>${pbText}</div>` : ''}
                ${erpText ? `<div>${erpText}</div>` : ''}
              </div>
            </div>
          `
        }

        return tip
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: { backgroundColor: '#27272a' },
    },
    grid: [
      { left: 55, right: 30, top: 40, height: '58%' },
      { left: 55, right: 30, top: '74%', height: '18%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
        splitLine: { show: false },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { color: 'rgba(255, 255, 255, 0.35)', fontSize: 9 },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.03)' } },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: Math.max(0, 100 - Math.round((90 / list.length) * 100)),
        end: 100,
      },
      {
        show: true,
        xAxisIndex: [0, 1],
        type: 'slider',
        bottom: 5,
        height: 14,
        borderColor: 'rgba(255,255,255,0.06)',
        fillerColor: 'rgba(239, 68, 68, 0.15)',
        textStyle: { color: 'rgba(255,255,255,0.35)', fontSize: 9 },
      },
    ],
    series: [
      {
        name: '日K线',
        type: 'candlestick',
        data: candlestickData,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: {
          color: '#ef4444',
          color0: '#10b981',
          borderColor: '#ef4444',
          borderColor0: '#10b981',
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#f59e0b' },
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#3b82f6' },
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#a855f7' },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes.map((v) => ({
          value: v[1],
          itemStyle: {
            color: v[2] === 1 ? 'rgba(239, 68, 68, 0.6)' : 'rgba(16, 185, 129, 0.6)',
          },
        })),
      },
    ],
  }
})

// 2. ECharts 估值通道河流图 (Valuation River Bands)
// 展现收盘价与估值理论通道带 (P20/P50/P80) 或 ERP / 股息率曲线
const valuationRiverOption = computed(() => {
  const valData = marketStore.currentValuation
  if (!valData || !valData.history || valData.history.length === 0) {
    return {}
  }

  const history = valData.history
  const dates = history.map((h) => h.date)
  const tab = valuationChartTab.value

  if (tab === 'pe' || tab === 'pb') {
    const isPE = tab === 'pe'
    const metricName = isPE ? 'PE(TTM)' : 'PB'

    // 根据当期指标与收盘价推算理论价格通道：
    // Price_P20 = Close * (Metric_P20 / Metric)
    // Price_P50 = Close * (Metric_P50 / Metric)
    // Price_P80 = Close * (Metric_P80 / Metric)
    const closeSeries: (number | null)[] = []
    const p20Series: (number | null)[] = []
    const p50Series: (number | null)[] = []
    const p80Series: (number | null)[] = []

    history.forEach((h) => {
      const curMetric = isPE ? h.pe : h.pb
      const curP20 = isPE ? h.pe_p20 : h.pb_p20
      const curP50 = isPE ? h.pe_p50 : h.pb_p50
      const curP80 = isPE ? h.pe_p80 : h.pb_p80
      const close = h.close || 0

      closeSeries.push(close > 0 ? Number(close.toFixed(2)) : null)

      if (close > 0 && curMetric && curMetric > 0) {
        p20Series.push(curP20 ? Number(((close * curP20) / curMetric).toFixed(2)) : null)
        p50Series.push(curP50 ? Number(((close * curP50) / curMetric).toFixed(2)) : null)
        p80Series.push(curP80 ? Number(((close * curP80) / curMetric).toFixed(2)) : null)
      } else {
        p20Series.push(null)
        p50Series.push(null)
        p80Series.push(null)
      }
    })

    return {
      backgroundColor: 'transparent',
      animation: true,
      legend: {
        data: ['真实收盘价', 'P80 压力线 (高估)', 'P50 中枢线 (合理)', 'P20 支撑线 (击球区)'],
        textStyle: { color: 'rgba(255, 255, 255, 0.7)', fontSize: 11 },
        top: 4,
        right: 20,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255, 255, 255, 0.2)', type: 'dashed' } },
        backgroundColor: 'rgba(18, 19, 24, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.15)',
        padding: [10, 14],
        textStyle: { color: '#ffffff', fontSize: 12 },
        formatter: (params: any) => {
          if (!params || !params.length) return ''
          const date = params[0].name
          const h = valuationDateMap.value.get(date)
          let tip = `<div class="font-bold text-zinc-300 font-mono mb-1.5 pb-1 border-b border-white/10 flex items-center justify-between">
            <span>${date}</span>
            <span class="text-zinc-400 font-normal text-[11px]">${metricName} 估值河流</span>
          </div>`

          params.forEach((p: any) => {
            if (p.value !== undefined && p.value !== null) {
              tip += `<div class="text-[11px] font-mono flex items-center justify-between space-x-3 mt-0.5">
                <span class="text-zinc-400">${p.seriesName}:</span>
                <span style="color:${p.color}" class="font-bold">¥${p.value}</span>
              </div>`
            }
          })

          if (h) {
            const curVal = isPE ? h.pe : h.pb
            const curPct = isPE ? h.pe_pct : h.pb_pct
            tip += `
              <div class="mt-2 pt-1.5 border-t border-white/10 text-[10px] text-zinc-400 font-mono flex items-center justify-between">
                <span>当期 ${metricName}: <strong class="text-white">${curVal || '--'}</strong></span>
                <span>历史分位: <strong class="text-blue-300">${curPct !== undefined ? Math.round(curPct * 100) + '%' : '--'}</strong></span>
              </div>
            `
          }
          return tip
        },
      },
      grid: { left: 55, right: 30, top: 45, bottom: 40 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
      },
      yAxis: {
        scale: true,
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
      },
      dataZoom: [
        { type: 'inside', start: Math.max(0, 100 - Math.round((120 / dates.length) * 100)), end: 100 },
        {
          show: true,
          type: 'slider',
          bottom: 5,
          height: 14,
          borderColor: 'rgba(255,255,255,0.06)',
          fillerColor: 'rgba(59, 130, 246, 0.15)',
          textStyle: { color: 'rgba(255,255,255,0.35)', fontSize: 9 },
        },
      ],
      series: [
        {
          name: 'P80 压力线 (高估)',
          type: 'line',
          data: p80Series,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.2, color: 'rgba(239, 68, 68, 0.85)', type: 'dashed' },
        },
        {
          name: 'P50 中枢线 (合理)',
          type: 'line',
          data: p50Series,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.2, color: 'rgba(59, 130, 246, 0.85)', type: 'dotted' },
        },
        {
          name: 'P20 支撑线 (击球区)',
          type: 'line',
          data: p20Series,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.4, color: 'rgba(16, 185, 129, 0.95)', type: 'dashed' },
          areaStyle: {
            color: 'rgba(16, 185, 129, 0.06)',
          },
        },
        {
          name: '真实收盘价',
          type: 'line',
          data: closeSeries,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2.2, color: '#ffffff' },
        },
      ],
    }
  } else if (tab === 'erp') {
    // ERP 股债利差曲线
    const erpSeries = history.map((h) => (h.erp !== undefined && h.erp !== null ? h.erp : null))
    return {
      backgroundColor: 'transparent',
      animation: true,
      legend: {
        data: ['ERP 股债利差 (%)', '0% 平衡线'],
        textStyle: { color: 'rgba(255, 255, 255, 0.7)', fontSize: 11 },
        top: 4,
        right: 20,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255, 255, 255, 0.2)', type: 'dashed' } },
        backgroundColor: 'rgba(18, 19, 24, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.15)',
        formatter: (params: any) => {
          if (!params || !params.length) return ''
          const date = params[0].name
          const erpVal = params[0].value
          return `
            <div class="font-bold text-zinc-300 font-mono mb-1">${date}</div>
            <div class="text-xs text-purple-300 font-mono font-bold">股债利差 (ERP): ${erpVal !== null && erpVal !== undefined ? erpVal + '%' : '--'}</div>
            <div class="text-[10px] text-zinc-400 mt-1">ERP = 盈利收益率(1/PE) - 10Y国债基准</div>
          `
        },
      },
      grid: { left: 55, right: 30, top: 45, bottom: 40 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
      },
      yAxis: {
        scale: true,
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
      },
      series: [
        {
          name: 'ERP 股债利差 (%)',
          type: 'line',
          data: erpSeries,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: '#c084fc' },
          areaStyle: {
            color: 'rgba(192, 132, 252, 0.12)',
          },
          markLine: {
            data: [{ yAxis: 0, name: '0% 平衡线', lineStyle: { color: 'rgba(255,255,255,0.3)', type: 'dashed' } }],
          },
        },
      ],
    }
  } else {
    // 股息率曲线
    const divSeries = history.map((h) => (h.dividend_yield !== undefined && h.dividend_yield !== null ? h.dividend_yield : null))
    return {
      backgroundColor: 'transparent',
      animation: true,
      legend: {
        data: ['股息率 (%)'],
        textStyle: { color: 'rgba(255, 255, 255, 0.7)', fontSize: 11 },
        top: 4,
        right: 20,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(18, 19, 24, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.15)',
        formatter: (params: any) => {
          if (!params || !params.length) return ''
          return `
            <div class="font-bold text-zinc-300 font-mono mb-1">${params[0].name}</div>
            <div class="text-xs text-amber-300 font-mono font-bold">股息率: ${params[0].value !== null ? params[0].value + '%' : '--'}</div>
          `
        },
      },
      grid: { left: 55, right: 30, top: 45, bottom: 40 },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
      },
      yAxis: {
        scale: true,
        axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
      },
      series: [
        {
          name: '股息率 (%)',
          type: 'line',
          data: divSeries,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: '#fbbf24' },
          areaStyle: {
            color: 'rgba(251, 191, 36, 0.12)',
          },
        },
      ],
    }
  }
})
</script>

<template>
  <div class="space-y-4 max-w-7xl mx-auto pb-12 animate-fadeIn">
    <!-- 1. 面包屑与快捷导航 -->
    <div class="flex items-center justify-between text-xs text-zinc-400">
      <div class="flex items-center space-x-2">
        <router-link to="/" class="hover:text-white transition-colors">首页</router-link>
        <span>/</span>
        <span class="text-zinc-500">标的行情中枢</span>
        <span>/</span>
        <span class="text-zinc-200 font-bold flex items-center space-x-1.5">
          <span>{{ marketStore.currentDetail?.name || marketStore.getSymbolName(currentSymbol) }}</span>
          <span class="text-zinc-500 font-mono font-normal text-[11px]">({{ currentSymbol.split('.')[0] }})</span>
        </span>
      </div>

      <!-- 右侧投研操作按钮 -->
      <div class="flex items-center space-x-2">
        <!-- ⭐ 加入我的组合下拉浮层 -->
        <div class="relative">
          <button
            @click="showWatchlistPopover = !showWatchlistPopover"
            class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.12] text-zinc-200 hover:text-white border border-white/[0.08] text-xs font-semibold flex items-center space-x-1.5 transition-all cursor-pointer"
          >
            <span>⭐</span>
            <span>加入自选组合</span>
            <span class="text-[10px] text-zinc-400">▼</span>
          </button>

          <!-- 组合选择浮层 -->
          <div
            v-if="showWatchlistPopover"
            class="absolute right-0 top-full mt-2 w-64 bg-[#181920] border border-white/[0.12] rounded-2xl shadow-2xl p-3 z-50 animate-fadeIn space-y-2.5"
          >
            <div class="flex items-center justify-between pb-1.5 border-b border-white/[0.08]">
              <span class="text-xs font-bold text-white">管理我的自选组合</span>
              <button @click="showWatchlistPopover = false" class="text-zinc-400 hover:text-white text-xs cursor-pointer">✕</button>
            </div>

            <div class="max-h-48 overflow-y-auto space-y-1">
              <div
                v-for="wl in strategyStore.userWatchlists"
                :key="wl.id"
                @click="toggleWatchlist(wl.id)"
                class="px-2.5 py-1.5 rounded-xl hover:bg-white/[0.04] flex items-center justify-between cursor-pointer text-xs transition-colors"
              >
                <div class="flex items-center space-x-2 truncate">
                  <span
                    :class="wl.symbols.includes(currentSymbol) ? 'bg-blue-500 text-white' : 'border border-white/[0.2]'"
                    class="w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold"
                  >
                    {{ wl.symbols.includes(currentSymbol) ? '✓' : '' }}
                  </span>
                  <span class="text-zinc-200 truncate">{{ wl.name }}</span>
                </div>
                <span class="text-[10px] text-zinc-500 font-mono">{{ wl.symbols.length }}只</span>
              </div>
            </div>

            <div class="pt-1.5 border-t border-white/[0.08] flex items-center space-x-1.5">
              <input
                v-model="newWatchlistName"
                type="text"
                placeholder="+ 新建自选组合"
                @keydown.enter="handleCreateWatchlist"
                class="w-full bg-black/40 border border-white/[0.1] rounded-lg px-2 py-1 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
              />
              <button
                @click="handleCreateWatchlist"
                :disabled="!newWatchlistName.trim() || isCreatingWatchlist"
                class="px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-bold text-xs shrink-0 cursor-pointer"
              >
                创建
              </button>
            </div>
          </div>
        </div>

        <!-- ⚡ 载入策略回测 -->
        <button
          @click="runBacktest"
          class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-bold text-xs shadow-lg shadow-red-500/20 flex items-center space-x-1.5 transition-all cursor-pointer"
        >
          <span>⚡</span>
          <span>载入策略回测</span>
        </button>
      </div>
    </div>

    <!-- 2. 标的行情核心头部看板 (Quote Board) -->
    <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] backdrop-blur-md space-y-4">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <!-- 标的名称、代码与市场标签 -->
        <div class="flex items-center space-x-3.5">
          <div class="w-12 h-12 rounded-2xl bg-black/50 border border-white/[0.1] flex items-center justify-center text-xl font-bold">
            <span v-if="marketStore.currentDetail?.asset_type === 'ETF'" class="text-blue-400">基</span>
            <span v-else-if="marketStore.currentDetail?.market === 'US'" class="text-amber-400">美</span>
            <span v-else-if="marketStore.currentDetail?.market === 'HK'" class="text-purple-400">港</span>
            <span v-else class="text-red-400">A</span>
          </div>

          <div>
            <div class="flex items-center space-x-2">
              <h1 class="text-2xl font-bold text-white tracking-tight">
                {{ marketStore.currentDetail?.name || currentSymbol }}
              </h1>
              <span class="px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-white/[0.06] text-zinc-300 border border-white/[0.08]">
                {{ marketStore.currentDetail?.ticker || currentSymbol.split('.')[0] }}
              </span>
              <span class="px-2 py-0.5 rounded-md text-[11px] font-mono bg-red-500/15 text-red-300 border border-red-500/20 font-bold">
                {{ marketStore.currentDetail?.market || 'SH' }}
              </span>
              <span class="px-2 py-0.5 rounded-md text-[11px] font-mono bg-blue-500/15 text-blue-300 border border-blue-500/20">
                {{ marketStore.currentDetail?.asset_type || 'STK' }}
              </span>
            </div>
            <div class="text-xs text-zinc-400 font-mono mt-1 flex items-center space-x-2">
              <span>全代码: {{ currentSymbol }}</span>
              <span>•</span>
              <span class="text-emerald-400">全维估值湖仓加速</span>
            </div>
          </div>
        </div>

        <!-- 现价大字报盘区 -->
        <div class="flex items-baseline space-x-4 font-mono">
          <div class="text-3xl sm:text-4xl font-black tracking-tight text-white">
            ¥{{ marketStore.currentDetail?.latest_price !== undefined && marketStore.currentDetail?.latest_price !== null ? marketStore.currentDetail.latest_price.toFixed(marketStore.currentDetail.latest_price > 10 ? 2 : 3) : '--' }}
          </div>

          <div
            v-if="marketStore.currentDetail?.pct_change !== undefined && marketStore.currentDetail?.pct_change !== null"
            :class="marketStore.currentDetail.pct_change >= 0 ? 'text-red-400' : 'text-emerald-400'"
            class="text-base sm:text-lg font-bold flex items-center space-x-1"
          >
            <span>{{ marketStore.currentDetail.pct_change >= 0 ? '▲ +' : '▼ ' }}{{ marketStore.currentDetail.pct_change.toFixed(2) }}%</span>
            <span v-if="marketStore.currentDetail.change !== undefined && marketStore.currentDetail.change !== null" class="text-xs text-zinc-400">
              ({{ marketStore.currentDetail.change >= 0 ? '+' : '' }}{{ marketStore.currentDetail.change.toFixed(2) }})
            </span>
          </div>
        </div>
      </div>

      <!-- 行情基础指标网格 (今开、最高、最低、成交量、成交额等) -->
      <div class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2.5 pt-3 border-t border-white/[0.06] text-xs font-mono">
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">今开</div>
          <div class="font-bold text-white mt-0.5">¥{{ marketStore.currentDetail?.open || '--' }}</div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">最高</div>
          <div class="font-bold text-red-400 mt-0.5">¥{{ marketStore.currentDetail?.high || '--' }}</div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">最低</div>
          <div class="font-bold text-emerald-400 mt-0.5">¥{{ marketStore.currentDetail?.low || '--' }}</div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">昨收</div>
          <div class="font-bold text-zinc-300 mt-0.5">¥{{ marketStore.currentDetail?.pre_close || '--' }}</div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">成交量</div>
          <div class="font-bold text-white mt-0.5">
            {{ marketStore.currentDetail?.volume ? (marketStore.currentDetail.volume / 10000).toFixed(2) + '万股' : '--' }}
          </div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">成交额</div>
          <div class="font-bold text-white mt-0.5">
            {{ marketStore.currentDetail?.amount ? (marketStore.currentDetail.amount / 100000000).toFixed(2) + '亿' : '--' }}
          </div>
        </div>
      </div>
    </div>

    <!-- ⭐ 2.5 全维估值态势核心仪表盘 (Multi-Dimensional Valuation Radar) -->
    <div class="p-5 rounded-2xl bg-gradient-to-b from-white/[0.04] to-white/[0.01] border border-white/[0.08] backdrop-blur-md space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
        <div class="flex items-center space-x-2">
          <span class="text-base font-bold text-white flex items-center space-x-1.5">
            <span>💎</span>
            <span>全维估值态势看板</span>
          </span>
          <span class="text-[11px] text-zinc-400 font-mono">
            (基于 {{ valuationWindow }} 回溯区间 • {{ marketStore.currentValuation?.sample_count || '--' }} 个交易日样本)
          </span>
        </div>

        <!-- 回溯时间窗口切换 -->
        <div class="flex items-center space-x-1">
          <span class="text-[11px] text-zinc-400 mr-1.5">分位窗口:</span>
          <button
            v-for="w in (['1y', '3y', '5y', 'all'] as const)"
            :key="w"
            @click="valuationWindow = w"
            :class="valuationWindow === w ? 'bg-blue-600 text-white font-bold' : 'bg-white/[0.05] text-zinc-400 hover:text-zinc-200'"
            class="px-2.5 py-0.8 rounded-lg text-xs font-mono transition-all cursor-pointer"
          >
            {{ w.toUpperCase() }}
          </button>
        </div>
      </div>

      <!-- 四维核心估值卡片栅格 (PE / PB / ERP / PB-ROE) -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <!-- 卡片 1: PE(TTM) 市盈率与历史分位数 -->
        <div class="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-2.5 relative overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-zinc-400 font-medium">PE(TTM) 估值分位</span>
            <span
              v-if="marketStore.currentValuation?.latest?.pe_ttm"
              :class="getValuationBadge(marketStore.currentValuation.latest.pe_ttm.percentile).color"
              class="px-2 py-0.5 rounded-md text-[10px] font-bold border"
            >
              {{ getValuationBadge(marketStore.currentValuation.latest.pe_ttm.percentile).label }}
            </span>
          </div>

          <div class="flex items-baseline space-x-2 font-mono">
            <span class="text-2xl font-black text-amber-300">
              {{ marketStore.currentValuation?.latest?.pe_ttm?.current !== undefined ? marketStore.currentValuation.latest.pe_ttm.current : '--' }}
            </span>
            <span class="text-xs text-zinc-400">
              ({{ marketStore.currentValuation?.latest?.pe_ttm?.percentile !== undefined ? (marketStore.currentValuation.latest.pe_ttm.percentile * 100).toFixed(1) + '%' : '--' }}分位)
            </span>
          </div>

          <!-- 分位指示进度条 (0% 绿 -> 50% 蓝 -> 100% 红) -->
          <div class="space-y-1">
            <div class="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden relative">
              <div
                class="h-full bg-gradient-to-r from-emerald-400 via-blue-400 to-red-400 rounded-full transition-all duration-500"
                :style="{ width: `${Math.min(100, Math.max(0, (marketStore.currentValuation?.latest?.pe_ttm?.percentile || 0.5) * 100))}%` }"
              ></div>
            </div>
            <div class="flex justify-between text-[10px] font-mono text-zinc-400 pt-0.5">
              <span>P20支撑: {{ marketStore.currentValuation?.latest?.pe_ttm?.p20 || '--' }}</span>
              <span>P50中枢: {{ marketStore.currentValuation?.latest?.pe_ttm?.p50 || '--' }}</span>
              <span>P80压力: {{ marketStore.currentValuation?.latest?.pe_ttm?.p80 || '--' }}</span>
            </div>
          </div>
        </div>

        <!-- 卡片 2: PB 市净率与资产通道 -->
        <div class="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-2.5 relative overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-zinc-400 font-medium">PB 市净率分位</span>
            <span
              v-if="marketStore.currentValuation?.latest?.pb"
              :class="getValuationBadge(marketStore.currentValuation.latest.pb.percentile).color"
              class="px-2 py-0.5 rounded-md text-[10px] font-bold border"
            >
              {{ getValuationBadge(marketStore.currentValuation.latest.pb.percentile).label }}
            </span>
          </div>

          <div class="flex items-baseline space-x-2 font-mono">
            <span class="text-2xl font-black text-blue-300">
              {{ marketStore.currentValuation?.latest?.pb?.current !== undefined ? marketStore.currentValuation.latest.pb.current : '--' }}
            </span>
            <span class="text-xs text-zinc-400">
              ({{ marketStore.currentValuation?.latest?.pb?.percentile !== undefined ? (marketStore.currentValuation.latest.pb.percentile * 100).toFixed(1) + '%' : '--' }}分位)
            </span>
          </div>

          <div class="space-y-1">
            <div class="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden relative">
              <div
                class="h-full bg-gradient-to-r from-emerald-400 via-blue-400 to-red-400 rounded-full transition-all duration-500"
                :style="{ width: `${Math.min(100, Math.max(0, (marketStore.currentValuation?.latest?.pb?.percentile || 0.5) * 100))}%` }"
              ></div>
            </div>
            <div class="flex justify-between text-[10px] font-mono text-zinc-400 pt-0.5">
              <span>P20: {{ marketStore.currentValuation?.latest?.pb?.p20 || '--' }}</span>
              <span>P50: {{ marketStore.currentValuation?.latest?.pb?.p50 || '--' }}</span>
              <span>P80: {{ marketStore.currentValuation?.latest?.pb?.p80 || '--' }}</span>
            </div>
          </div>
        </div>

        <!-- 卡片 3: ERP 股债利差 (股权风险溢价) -->
        <div class="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-2 relative overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-zinc-400 font-medium flex items-center space-x-1">
              <span>股债利差 (ERP)</span>
            </span>
            <span
              v-if="marketStore.currentValuation?.latest?.equity_risk_premium"
              :class="marketStore.currentValuation.latest.equity_risk_premium.equity_risk_premium_pct >= 2.0 ? 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' : 'text-blue-300 bg-blue-500/20 border-blue-500/40'"
              class="px-2 py-0.5 rounded-md text-[10px] font-bold border"
            >
              {{ marketStore.currentValuation.latest.equity_risk_premium.equity_risk_premium_pct >= 2.0 ? '股票高性价比' : '股债中性' }}
            </span>
          </div>

          <div class="flex items-baseline space-x-2 font-mono">
            <span
              :class="marketStore.currentValuation?.latest?.equity_risk_premium?.equity_risk_premium_pct && marketStore.currentValuation.latest.equity_risk_premium.equity_risk_premium_pct >= 0 ? 'text-purple-300' : 'text-zinc-300'"
              class="text-2xl font-black"
            >
              {{ marketStore.currentValuation?.latest?.equity_risk_premium?.equity_risk_premium_pct !== undefined ? (marketStore.currentValuation.latest.equity_risk_premium.equity_risk_premium_pct > 0 ? '+' : '') + marketStore.currentValuation.latest.equity_risk_premium.equity_risk_premium_pct.toFixed(2) + '%' : '--' }}
            </span>
            <span class="text-xs text-zinc-400">
              (利差水平)
            </span>
          </div>

          <div class="text-[10px] text-zinc-400 font-mono space-y-0.5 pt-1 border-t border-white/[0.04]">
            <div class="flex justify-between">
              <span>盈利收益率 (1/PE):</span>
              <span class="text-white">{{ marketStore.currentValuation?.latest?.equity_risk_premium?.earning_yield_pct || '--' }}%</span>
            </div>
            <div class="flex justify-between">
              <span>10Y国债基准:</span>
              <span class="text-zinc-400">{{ marketStore.currentValuation?.latest?.equity_risk_premium?.benchmark_10y_bond_pct || '--' }}%</span>
            </div>
          </div>
        </div>

        <!-- 卡片 4: PB-ROE 质量安全与周期防御 -->
        <div class="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-2 relative overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-zinc-400 font-medium">PB-ROE 质量防御</span>
            <span
              v-if="marketStore.currentValuation?.latest?.pb_roe_quality"
              :class="marketStore.currentValuation.latest.pb_roe_quality.is_asset_quality_safe ? 'text-emerald-300 bg-emerald-500/20 border-emerald-500/40' : 'text-amber-300 bg-amber-500/20 border-amber-500/40'"
              class="px-2 py-0.5 rounded-md text-[10px] font-bold border"
            >
              {{ marketStore.currentValuation.latest.pb_roe_quality.is_asset_quality_safe ? '安全垫扎实' : '低ROE关注' }}
            </span>
          </div>

          <div class="flex items-baseline space-x-2 font-mono">
            <span class="text-2xl font-black text-emerald-400">
              {{ marketStore.currentValuation?.latest?.pb_roe_quality?.implied_roe_pct !== undefined ? marketStore.currentValuation.latest.pb_roe_quality.implied_roe_pct.toFixed(2) + '%' : '--' }}
            </span>
            <span class="text-xs text-zinc-400">
              (隐含 ROE)
            </span>
          </div>

          <div class="text-[10px] text-zinc-400 font-mono space-y-0.5 pt-1 border-t border-white/[0.04]">
            <div class="flex justify-between">
              <span>股息率(Yield):</span>
              <span class="text-amber-300 font-bold">{{ marketStore.currentValuation?.latest?.dividend_yield_pct ? marketStore.currentValuation.latest.dividend_yield_pct + '%' : '暂无' }}</span>
            </div>
            <div class="flex justify-between">
              <span>资产安全诊断:</span>
              <span class="text-zinc-300">{{ marketStore.currentValuation?.latest?.pb_roe_quality?.is_asset_quality_safe ? '防价值陷阱OK' : '建议搭配现金流' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. K 线图控制工具条 -->
    <div class="flex items-center justify-between px-2 pt-2">
      <div class="flex items-center space-x-1.5">
        <span class="text-xs font-bold text-white flex items-center space-x-1 mr-2">
          <span>📈</span>
          <span>历史日 K 走势 (Candlestick)</span>
        </span>

        <button
          @click="adjustType = 'qfq'"
          :class="adjustType === 'qfq' ? 'bg-red-500/20 text-red-400 border-red-500/30 font-bold' : 'text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
          class="px-2.5 py-1 rounded-lg border text-[11px] transition-all cursor-pointer"
        >
          前复权 (QFQ)
        </button>

        <button
          @click="adjustType = 'raw'"
          :class="adjustType === 'raw' ? 'bg-red-500/20 text-red-400 border-red-500/30 font-bold' : 'text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
          class="px-2.5 py-1 rounded-lg border text-[11px] transition-all cursor-pointer"
        >
          不复权 (Raw)
        </button>
      </div>

      <!-- K线长度切换 -->
      <div class="flex items-center space-x-1 text-[11px]">
        <button
          v-for="len in [120, 250, 500]"
          :key="len"
          @click="klineLimit = len"
          :class="klineLimit === len ? 'bg-white/10 text-white font-bold' : 'text-zinc-500 hover:text-zinc-300'"
          class="px-2 py-0.8 rounded-md transition-all cursor-pointer font-mono"
        >
          {{ len }}天
        </button>
      </div>
    </div>

    <!-- 4. ECharts K 线图主视口 -->
    <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08] relative min-h-[460px]">
      <!-- 加载动画 -->
      <div
        v-if="marketStore.isKlineLoading"
        class="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/40 backdrop-blur-xs space-y-2"
      >
        <div class="w-8 h-8 border-2 border-red-500/20 border-t-red-500 rounded-full animate-spin"></div>
        <span class="text-xs text-zinc-400 font-mono">加载 K 线数据与指标推进中...</span>
      </div>

      <!-- 空数据提示 -->
      <div
        v-else-if="marketStore.currentKline.length === 0"
        class="h-96 flex flex-col items-center justify-center text-center space-y-2 text-zinc-500"
      >
        <span class="text-2xl">📊</span>
        <span>暂无该标的的日 K 线行情数据</span>
      </div>

      <!-- 图表挂载 -->
      <div v-else class="w-full">
        <EChartWrapper :option="klineOption" height="460px" />
      </div>
    </div>

    <!-- ⭐ 5. 独立估值通道河流图 (Valuation River Bands Chart) -->
    <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] backdrop-blur-md space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
        <div>
          <div class="flex items-center space-x-2">
            <span class="text-base font-bold text-white flex items-center space-x-1.5">
              <span>🌊</span>
              <span>多维估值通道河流图 (Valuation River Bands)</span>
            </span>
            <span class="px-2 py-0.5 rounded-full text-[10px] font-mono bg-blue-500/15 text-blue-300 border border-blue-500/20">
              带状安全边际
            </span>
          </div>
          <div class="text-xs text-zinc-400 mt-1">
            动态描绘收盘价在估值带状区间中的穿越轨迹，跌破 P20 支撑线触发黄金击球，突破 P80 压力线警惕高估泡沫
          </div>
        </div>

        <!-- 估值维度切换 Tab -->
        <div class="flex items-center space-x-1 bg-black/40 p-1 rounded-xl border border-white/[0.06]">
          <button
            @click="valuationChartTab = 'pe'"
            :class="valuationChartTab === 'pe' ? 'bg-blue-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 rounded-lg text-xs transition-all cursor-pointer"
          >
            PE 估值河流
          </button>
          <button
            @click="valuationChartTab = 'pb'"
            :class="valuationChartTab === 'pb' ? 'bg-blue-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 rounded-lg text-xs transition-all cursor-pointer"
          >
            PB 估值河流
          </button>
          <button
            @click="valuationChartTab = 'erp'"
            :class="valuationChartTab === 'erp' ? 'bg-blue-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 rounded-lg text-xs transition-all cursor-pointer"
          >
            股债利差 (ERP)
          </button>
          <button
            @click="valuationChartTab = 'dividend'"
            :class="valuationChartTab === 'dividend' ? 'bg-blue-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-3 py-1 rounded-lg text-xs transition-all cursor-pointer"
          >
            股息率走势
          </button>
        </div>
      </div>

      <!-- 河流图挂载视口 -->
      <div class="relative min-h-[380px]">
        <div
          v-if="marketStore.isValuationLoading"
          class="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/40 backdrop-blur-xs space-y-2"
        >
          <div class="w-8 h-8 border-2 border-blue-500/20 border-t-blue-500 rounded-full animate-spin"></div>
          <span class="text-xs text-zinc-400 font-mono">加载估值河流与滚动分位数据中...</span>
        </div>

        <div
          v-else-if="!marketStore.currentValuation || !marketStore.currentValuation.history || marketStore.currentValuation.history.length === 0"
          class="h-80 flex flex-col items-center justify-center text-center space-y-2 text-zinc-500"
        >
          <span class="text-2xl">📉</span>
          <span>该标的暂无足够的历史估值样本以构建通道河流</span>
        </div>

        <div v-else class="w-full">
          <EChartWrapper :option="valuationRiverOption" height="380px" />
        </div>
      </div>
    </div>

    <!-- 6. 浮动 Toast 提示 -->
    <div
      v-if="toastMsg"
      class="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl bg-black/90 border border-white/[0.15] text-white font-bold text-xs shadow-2xl animate-fadeIn flex items-center space-x-2"
    >
      <span>{{ toastMsg }}</span>
    </div>
  </div>
</template>
