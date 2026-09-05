<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useMarketStore, type SymbolItem, type KlineItem } from '@/stores/market'
import { useStrategyStore } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const marketStore = useMarketStore()
const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const currentSymbol = computed(() => (route.params.symbol as string) || '600519.SH.STK')
const adjustType = ref<'qfq' | 'raw'>('qfq')
const klineLimit = ref<number>(200)
const toastMsg = ref('')

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
  ])
}

watch(
  [() => route.params.symbol, adjustType, klineLimit],
  () => {
    loadData()
  },
  { immediate: true }
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
    // 找到刚创建的组合追加当前标的
    const created = strategyStore.userWatchlists[0]
    if (created) {
      await marketStore.addSymbolToWatchlist(created.id, currentSymbol.value)
      showToast(`⭐ 已创建「${newWatchlistName.value}」并加入该标的！`)
    }
    newWatchlistName.value = ''
  }
  isCreatingWatchlist.value = false
}

// ECharts 专业 K 线图 (Candlestick + MA5/10/20 + 成交量 Volume)
const klineOption = computed(() => {
  const list = marketStore.currentKline
  if (!list || list.length === 0) {
    return {}
  }

  const dates = list.map((item) => item.date)
  // ECharts candlestick format: [open, close, lowest, highest]
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
      textStyle: { color: '#ffffff', fontSize: 12 },
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        const date = params[0].name
        const kline = params.find((p: any) => p.seriesName === '日K线')
        let tip = `<div class="font-bold text-zinc-300 font-mono mb-1.5">${date}</div>`
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
              <span class="text-zinc-400">振幅/涨跌: <strong style="color: ${colorClass}">${chg >= 0 ? '+' : ''}${pct}%</strong></span>
            </div>
          `
        }
        params.forEach((p: any) => {
          if (p.seriesName.startsWith('MA') && p.value !== undefined && p.value !== null) {
            tip += `<div class="text-[10px] font-mono text-zinc-400 mt-0.5">${p.seriesName}: <span style="color:${p.color}">${p.value}</span></div>`
          }
        })
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
        <span class="text-zinc-200 font-mono font-bold">{{ currentSymbol }}</span>
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

            <!-- 组合列表复选 -->
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

            <!-- 快速新建组合输入框 -->
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
              <span>实时行情驱动</span>
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

      <!-- 核心指标网格 (今开、最高、最低、成交量、PE等) -->
      <div class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-2.5 pt-3 border-t border-white/[0.06] text-xs font-mono">
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
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">市盈率 (PE)</div>
          <div class="font-bold text-amber-300 mt-0.5">{{ marketStore.currentDetail?.pe || 'N/A' }}</div>
        </div>
        <div class="p-2 rounded-xl bg-black/30 border border-white/[0.04]">
          <div class="text-[10px] text-zinc-400">市净率 (PB)</div>
          <div class="font-bold text-blue-300 mt-0.5">{{ marketStore.currentDetail?.pb || 'N/A' }}</div>
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

    <!-- 5. 浮动 Toast 提示 -->
    <div
      v-if="toastMsg"
      class="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl bg-black/90 border border-white/[0.15] text-white font-bold text-xs shadow-2xl animate-fadeIn flex items-center space-x-2"
    >
      <span>{{ toastMsg }}</span>
    </div>
  </div>
</template>
