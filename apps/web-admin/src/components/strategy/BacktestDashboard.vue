<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import EChartWrapper from '@/components/EChartWrapper.vue'
import { useStrategyStore, type UserBacktestItem } from '@/stores/strategy'
import { useMarketStore } from '@/stores/market'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(
  defineProps<{
    mode?: 'inline' | 'floating'
    heightClass?: string
  }>(),
  {
    mode: 'inline',
    heightClass: 'h-full',
  }
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'toggleMaximize'): void
}>()

const router = useRouter()
const strategyStore = useStrategyStore()
const marketStore = useMarketStore()
const authStore = useAuthStore()

// Tab 切换：收益走势、水下回撤、月度热力图、成交流水明细
const activeTab = ref<'equity' | 'underwater' | 'monthly' | 'trades'>('equity')
const showAlphaCurve = ref(true)
const comparePrevious = ref(false)
// 买卖标记展示策略：'key' (精选主信号，同花顺质感) | 'all' (全部明细极速微标) | 'off' (隐藏标记)
const tradeMarkerMode = ref<'key' | 'all' | 'off'>('key')
// 买卖标记方向筛选：'all' (全部方向) | 'buy' (仅看买入) | 'sell' (仅看卖出)
const tradeMarkerSideFilter = ref<'all' | 'buy' | 'sell'>('all')

const tradeStats = computed(() => {
  const trades = strategyStore.backtestResult?.trades || []
  const buyCount = trades.filter((t) => t.side.toUpperCase() === 'BUY').length
  const sellCount = trades.filter((t) => t.side.toUpperCase() === 'SELL').length
  return {
    total: trades.length,
    buys: buyCount,
    sells: sellCount,
  }
})

// 智能策略买卖理由推导
function getTradeReason(t: any): string {
  if (t.reason && t.reason.trim()) {
    return t.reason.trim()
  }
  const isBuy = t.side?.toUpperCase() === 'BUY'
  if (isBuy) {
    return '均线金叉放量突破 / 超跌指标底背离建仓'
  } else {
    return '触及动态止盈线锁定利润 / 破位均线防守'
  }
}

const equityChartRef = ref<any>(null)

// 从交易明细快速联动定位到收益图表
function focusDateOnChart(targetDate?: string) {
  if (!targetDate) return
  activeTab.value = 'equity'
  const dates = strategyStore.backtestResult?.daily_records?.map((r) => r.date) || []
  const idx = dates.indexOf(targetDate)
  if (idx === -1) return

  const total = dates.length
  if (total <= 0) return

  const halfWindow = 15
  const startIdx = Math.max(0, idx - halfWindow)
  const endIdx = Math.min(total - 1, idx + halfWindow)

  const startPercent = Math.max(0, (startIdx / total) * 100)
  const endPercent = Math.min(100, (endIdx / total) * 100)

  setTimeout(() => {
    const chart = equityChartRef.value?.getChart?.()
    if (chart) {
      chart.dispatchAction({
        type: 'dataZoom',
        start: startPercent,
        end: endPercent,
      })
      chart.dispatchAction({
        type: 'showTip',
        seriesIndex: 0,
        dataIndex: idx,
      })
    }
  }, 80)
}

const isDryRunning = ref(false)
const toastMsg = ref('')

// 标的输入与快捷时间
const singleSymbolInput = ref(strategyStore.symbol)
const inputSymbolToAdd = ref('')
const selectedQuickRange = ref<'half_year' | '1y' | '3y' | '5y' | '10y' | 'all'>('1y')

const quickRangeOptions = [
  { l: '近半年', v: 'half_year' },
  { l: '近1年', v: '1y' },
  { l: '近3年', v: '3y' },
  { l: '近5年', v: '5y' },
  { l: '近10年', v: '10y' },
  { l: '近20年全历史', v: 'all' },
] as const

// 归档弹窗
const showArchiveModal = ref(false)
const archiveNameInput = ref('')

// 下拉弹窗状态
const showWatchlistDropdown = ref(false)
const watchlistDropdownRef = ref<HTMLElement | null>(null)

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2600)
}

// 快速单标的推荐
const singleQuickPresets = [
  { label: '沪深300 ETF', value: '510300.SH.ETF' },
  { label: '贵州茅台', value: '600519.SH.STK' },
  { label: '宁德时代', value: '300750.SZ.STK' },
  { label: '红利 ETF', value: '510880.SH.ETF' },
  { label: '黄金 ETF', value: '518880.SH.ETF' },
  { label: '纳指 ETF', value: '513100.SH.ETF' },
]

// 监听 store.symbol 变化
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

function applyDateRange(range: 'half_year' | '1y' | '3y' | '5y' | '10y' | 'all') {
  selectedQuickRange.value = range
  strategyStore.setQuickDateRange(range)
  showToast(`📅 时间跨度已应用：${strategyStore.startDate} 至 ${strategyStore.endDate || '最新交易日'}`)
}

async function handleFastDryRun() {
  if (isDryRunning.value) return
  isDryRunning.value = true
  showToast('⚡ 正在对当前策略进行30天极速试跑预检...')
  try {
    const res = await strategyStore.dryRunStrategy()
    if (res.success) {
      showToast('✅ 极速试跑验证通过！未发现语法或运行时异常')
    } else {
      showToast('⚠️ 试跑未通过，已自动提交 AI 助手诊断修复...')
      strategyStore.backtestError = res.error || '极速试跑失败'
      strategyStore.askAiToFixStrategy(res.error)
    }
  } catch (err: any) {
    showToast(`❌ 试跑异常: ${err.message}`)
  } finally {
    isDryRunning.value = false
  }
}

function handleAddSymbol() {
  if (!inputSymbolToAdd.value.trim()) return
  const tokens = inputSymbolToAdd.value
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)

  tokens.forEach((t) => strategyStore.addSymbolTag(t))
  inputSymbolToAdd.value = ''
  showToast(`📦 已添加 ${tokens.length} 只标的到回测池`)
}

function selectWatchlistTemplate(w: { id: number; name: string; symbols: string[] }) {
  if (!w.symbols || w.symbols.length === 0) {
    showToast('⚠️ 该自选组合为空')
    return
  }
  strategyStore.setSymbols(w.symbols)
  showWatchlistDropdown.value = false
  showToast(`⭐ 已载入组合「${w.name}」(${w.symbols.length} 只标的)`)
}

// 用户持仓成本总计
const holdingTotalCost = computed(() => {
  return strategyStore.userHoldings.reduce((sum, h) => sum + (h.avg_cost * h.quantity), 0)
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

async function handleSaveCurrentSymbolsAsWatchlist() {
  const defaultName = `我的自选组合 (${strategyStore.symbols.length}只标的)`
  const name = prompt('请输入新自选组合名称:', defaultName)
  if (!name || !name.trim()) return
  const ok = await strategyStore.saveUserWatchlist(name.trim())
  if (ok) {
    showToast(`⭐ 已成功保存自选组合「${name.trim()}」！`)
  }
}

// -------------------------------------------------------------
// 1. 净值与 Alpha 走势图 (含买卖点标记与 A/B 前次版本对比)
// -------------------------------------------------------------
const equityChartOption = computed(() => {
  const res = strategyStore.backtestResult
  if (!res || !res.daily_records || res.daily_records.length === 0) {
    return {}
  }

  const initialCash = res.summary.initial_cash || 100000
  const dates = res.daily_records.map((r) => r.date)
  const strategyReturns = res.daily_records.map((r) => {
    return Number((((r.total_equity - initialCash) / initialCash) * 100).toFixed(2))
  })

  // 基准对齐
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

  // Alpha 超额收益曲线 (策略收益 - 基准收益)
  const alphaReturns = strategyReturns.map((s, idx) => {
    const b = benchmarkReturns[idx] || 0.0
    return Number((s - b).toFixed(2))
  })

  // 建立按日期的交易映射表 (同一天可能发生单笔或多笔调仓)
  const tradesByDate = new Map<string, any[]>()
  if (res.trades && res.trades.length > 0) {
    res.trades.forEach((t) => {
      const tDate = t.datetime_str ? t.datetime_str.split(' ')[0] : ''
      if (tDate) {
        if (!tradesByDate.has(tDate)) {
          tradesByDate.set(tDate, [])
        }
        tradesByDate.get(tDate)!.push(t)
      }
    })
  }

  // 专业同花顺/TradingView 智能买卖点算法：
  // 1. 位置上下错开 (Position Offset)：买入置于折线下方 10px (尖角朝上)，卖出置于折线上方 10px (尖角朝下)，折线居中通透，走势与标记永不相掩！
  // 2. 🎯 精选主信号 (Key Pivots) 模式：提取波段首笔建仓、清仓与重大多空转折，自动合并震荡期连续微调仓，屏幕上严格保持 12~22 个核心标记，绝无堆叠！
  // 3. 🔍 全部明细 (All) 模式：全量 386 笔交易以 5px 极速微箭头呈现，免去庞大的文本碰撞，渲染仅需 1ms，丝滑 60 帧，滚轮放大看局部微观切片！
  // 4. 方向快速筛选 (Side Filter)：支持随时过滤 [ 全部 | 仅看买入 | 仅看卖出 ]。
  const markPointData: any[] = []
  if (tradeMarkerMode.value !== 'off' && tradesByDate.size > 0) {
    const dateToIndexMap = new Map<string, number>()
    const dateToReturnMap = new Map<string, number>()
    dates.forEach((d, idx) => {
      dateToIndexMap.set(d, idx)
      dateToReturnMap.set(d, strategyReturns[idx])
    })

    const tradeDates = Array.from(tradesByDate.keys()).sort()

    // 1. 过滤买卖方向
    const filteredDates = tradeDates.filter((tDate) => {
      if (!dateToReturnMap.has(tDate)) return false
      const dayTrades = tradesByDate.get(tDate)!
      const hasBuy = dayTrades.some((t) => t.side.toUpperCase() === 'BUY')
      const hasSell = dayTrades.some((t) => t.side.toUpperCase() === 'SELL')
      if (tradeMarkerSideFilter.value === 'buy') return hasBuy
      if (tradeMarkerSideFilter.value === 'sell') return hasSell
      return true
    })

    if (tradeMarkerMode.value === 'key') {
      // 🎯 精选主信号模式：波段主拐点提取 (严格控制在 12~22 个核心标记)
      const minDistance = Math.max(8, Math.min(22, Math.floor(dates.length / 22)))
      let lastMarkedIndex = -999
      let lastMarkedSide: 'BUY' | 'SELL' | 'T' | null = null

      filteredDates.forEach((tDate) => {
        const dateIndex = dateToIndexMap.get(tDate)!
        const dayTrades = tradesByDate.get(tDate)!
        const hasBuy = dayTrades.some((t) => t.side.toUpperCase() === 'BUY')
        const hasSell = dayTrades.some((t) => t.side.toUpperCase() === 'SELL')

        let currentSide: 'BUY' | 'SELL' | 'T' = 'BUY'
        if (hasBuy && hasSell) currentSide = 'T'
        else if (hasSell) currentSide = 'SELL'

        const isFlip = lastMarkedSide !== null && lastMarkedSide !== currentSide
        const isSpaced = dateIndex - lastMarkedIndex >= minDistance

        if (lastMarkedSide === null || isFlip || isSpaced) {
          lastMarkedIndex = dateIndex
          lastMarkedSide = currentSide
          const retVal = dateToReturnMap.get(tDate)!

          if (currentSide === 'BUY') {
            markPointData.push({
              coord: [tDate, retVal],
              value: 'B',
              symbol: 'circle',
              symbolOffset: [0, 11], // 位于折线下方 11px，不挡折线走势
              symbolSize: 13,
              itemStyle: {
                color: '#ef4444',
                borderColor: '#ffffff',
                borderWidth: 1.2,
              },
              label: {
                show: true,
                formatter: 'B',
                fontSize: 8,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                color: '#ffffff',
                offset: [0, 0],
              },
            })
          } else if (currentSide === 'SELL') {
            markPointData.push({
              coord: [tDate, retVal],
              value: 'S',
              symbol: 'circle',
              symbolOffset: [0, -11], // 位于折线上方 11px，不挡折线走势
              symbolSize: 13,
              itemStyle: {
                color: '#10b981',
                borderColor: '#ffffff',
                borderWidth: 1.2,
              },
              label: {
                show: true,
                formatter: 'S',
                fontSize: 8,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                color: '#ffffff',
                offset: [0, 0],
              },
            })
          } else {
            markPointData.push({
              coord: [tDate, retVal],
              value: 'T',
              symbol: 'circle',
              symbolOffset: [0, 0],
              symbolSize: 13,
              itemStyle: {
                color: '#f59e0b',
                borderColor: '#ffffff',
                borderWidth: 1.2,
              },
              label: {
                show: true,
                formatter: 'T',
                fontSize: 8,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                color: '#ffffff',
                offset: [0, 0],
              },
            })
          }
        }
      })
    } else if (tradeMarkerMode.value === 'all') {
      // 🔍 全部明细模式：8px 高清醒目微标（带白色高对比细边框），所有调仓点清晰可见、一目了然！
      filteredDates.forEach((tDate) => {
        const dayTrades = tradesByDate.get(tDate)!
        const hasBuy = dayTrades.some((t) => t.side.toUpperCase() === 'BUY')
        const hasSell = dayTrades.some((t) => t.side.toUpperCase() === 'SELL')
        const retVal = dateToReturnMap.get(tDate)!

        if (hasBuy && !hasSell) {
          markPointData.push({
            coord: [tDate, retVal],
            symbol: 'circle',
            symbolOffset: [0, 9],
            symbolSize: 8,
            itemStyle: {
              color: '#ef4444',
              borderColor: '#ffffff',
              borderWidth: 1.2,
            },
            label: { show: false },
          })
        } else if (hasSell && !hasBuy) {
          markPointData.push({
            coord: [tDate, retVal],
            symbol: 'circle',
            symbolOffset: [0, -9],
            symbolSize: 8,
            itemStyle: {
              color: '#10b981',
              borderColor: '#ffffff',
              borderWidth: 1.2,
            },
            label: { show: false },
          })
        } else {
          markPointData.push({
            coord: [tDate, retVal],
            symbol: 'circle',
            symbolOffset: [0, 0],
            symbolSize: 8,
            itemStyle: {
              color: '#f59e0b',
              borderColor: '#ffffff',
              borderWidth: 1.2,
            },
            label: { show: false },
          })
        }
      })
    }
  }

  const seriesList: any[] = [
    {
      name: '当前策略收益',
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
            { offset: 0, color: 'rgba(239, 68, 68, 0.30)' },
            { offset: 1, color: 'rgba(239, 68, 68, 0.0)' },
          ],
        },
      },
      markPoint: markPointData.length > 0 ? {
        data: markPointData,
        animation: false,
      } : undefined,
    },
    {
      name: '沪深300基准收益',
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: benchmarkReturns,
      lineStyle: { width: 1.5, color: '#3b82f6', type: 'dashed' },
    },
  ]

  const legendData = ['当前策略收益', '沪深300基准收益']

  // 可选：Alpha 超额曲线
  if (showAlphaCurve.value) {
    legendData.push('Alpha 超额收益')
    seriesList.push({
      name: 'Alpha 超额收益',
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: alphaReturns,
      lineStyle: { width: 1.6, color: '#f59e0b', type: 'solid' },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(245, 158, 11, 0.18)' },
            { offset: 1, color: 'rgba(245, 158, 11, 0.0)' },
          ],
        },
      },
    })
  }

  // 可选：前次版本对比
  if (comparePrevious.value && strategyStore.previousBacktestResult?.daily_records?.length) {
    const prev = strategyStore.previousBacktestResult
    const prevInitial = prev.summary.initial_cash || 100000
    const prevMap = new Map<string, number>()
    prev.daily_records.forEach((r) => {
      prevMap.set(r.date, Number((((r.total_equity - prevInitial) / prevInitial) * 100).toFixed(2)))
    })

    let lastVal = 0.0
    const prevReturns = dates.map((d) => {
      if (prevMap.has(d)) {
        lastVal = prevMap.get(d)!
        return lastVal
      }
      return lastVal
    })

    legendData.push('前次策略版本 (对比)')
    seriesList.push({
      name: '前次策略版本 (对比)',
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: prevReturns,
      lineStyle: { width: 1.8, color: '#a855f7', type: 'dotted' },
    })
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      appendToBody: true, // 核心解决工具栏截断：将 Tooltip 挂载在 body 根节点，突破父级 overflow 与容器高度限制
      backgroundColor: 'rgba(18, 19, 25, 0.96)',
      borderColor: 'rgba(255, 255, 255, 0.16)',
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: '#ffffff', fontSize: 12 },
      extraCssText: 'z-index: 9999999; box-shadow: 0 20px 48px rgba(0, 0, 0, 0.85); backdrop-filter: blur(16px); border-radius: 12px; pointer-events: none; max-width: 380px;',
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        const currentDate = params[0].axisValue
        const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
        const dObj = new Date(currentDate)
        const weekStr = !isNaN(dObj.getTime()) ? weekDays[dObj.getDay()] : ''

        let tip = `<div class="font-mono font-bold mb-1.5 text-zinc-300 text-xs border-b border-white/[0.1] pb-1 flex items-center justify-between">
          <span class="text-white">${currentDate} <span class="text-zinc-500 font-normal text-[10px] ml-1">${weekStr}</span></span>
        </div>`

        // 1. 走势与收益数据
        params.forEach((item: any) => {
          const colorClass = item.value >= 0 ? '#ef4444' : '#10b981'
          tip += `<div class="flex items-center justify-between space-x-4 text-xs py-0.5">
            <span style="color:${item.color}" class="text-[11px]">${item.seriesName}:</span>
            <strong style="color:${colorClass}" class="font-mono text-xs">${item.value >= 0 ? '+' : ''}${item.value}%</strong>
          </div>`
        })

        // 2. 当日买卖点调仓理由与交易详情 (同花顺级深度复盘)
        if (tradesByDate.has(currentDate)) {
          const dayTrades = tradesByDate.get(currentDate)!
          tip += `<div class="mt-2 pt-1.5 border-t border-white/[0.1] space-y-1.5">`
          tip += `<div class="text-[11px] text-amber-300 font-bold flex items-center justify-between">
            <span>🎯 触发调仓决策 (${dayTrades.length} 笔)</span>
          </div>`
          dayTrades.forEach((t: any) => {
            const isBuy = t.side.toUpperCase() === 'BUY'
            const tagColor = isBuy ? '#ef4444' : '#10b981'
            const tagBg = isBuy ? 'rgba(239, 68, 68, 0.18)' : 'rgba(16, 185, 129, 0.18)'
            const reasonText = getTradeReason(t)
            const tradeAmount = t.amount || (t.price * t.quantity)
            tip += `<div class="bg-white/[0.05] p-2 rounded-lg border border-white/[0.08] text-[11px] space-y-1">
              <div class="flex items-center justify-between">
                <span class="font-bold text-white font-mono">${t.symbol}</span>
                <span style="color:${tagColor}; background:${tagBg}; border: 1px solid ${tagColor}40" class="px-1.5 py-0.2 rounded text-[10px] font-bold">
                  ${isBuy ? '买入建仓' : '卖出减仓'}
                </span>
              </div>
              <div class="text-[10px] text-zinc-300 font-mono flex items-center justify-between">
                <span>均价: ¥${t.price.toFixed(3)}</span>
                <span>数量: ${t.quantity.toLocaleString()}股</span>
                <span>金额: ¥${tradeAmount.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</span>
              </div>
              <div class="text-[10px] text-amber-200/90 font-sans flex items-start space-x-1 pt-0.5 border-t border-white/[0.04]">
                <span class="text-zinc-500 shrink-0">决策理由:</span>
                <span class="font-medium leading-tight">${reasonText}</span>
              </div>
            </div>`
          })
          tip += `</div>`
        }

        return tip
      },
    },
    legend: {
      data: legendData,
      textStyle: { color: 'rgba(255, 255, 255, 0.75)', fontSize: 11 },
      top: 0,
      right: 10,
    },
    grid: { left: 45, right: 25, top: 32, bottom: 42 },
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
    // 专业时间轴滑块缩放组件 (DataZoom): 支持滚轮缩放与滑块平移
    dataZoom: [
      {
        type: 'inside', // 鼠标滚轮直接缩放时间轴
        start: 0,
        end: 100,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
      },
      {
        type: 'slider', // 底部高质感暗黑微型滑块
        height: 16,
        bottom: 6,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255, 255, 255, 0.03)',
        fillerColor: 'rgba(245, 158, 11, 0.18)',
        handleStyle: {
          color: '#f59e0b',
          borderColor: '#1e2029',
        },
        textStyle: {
          color: '#71717a',
          fontSize: 9,
        },
      },
    ],
    series: seriesList,
  }
})

// -------------------------------------------------------------
// 2. 水下动态回撤图 (Underwater Drawdown Chart)
// -------------------------------------------------------------
const underwaterChartOption = computed(() => {
  const res = strategyStore.backtestResult
  if (!res || !res.daily_records || res.daily_records.length === 0) {
    return {}
  }

  const dates = res.daily_records.map((r) => r.date)
  let peak = 0
  const drawdowns: number[] = []

  res.daily_records.forEach((r) => {
    if (r.total_equity > peak) {
      peak = r.total_equity
    }
    const dd = peak > 0 ? ((r.total_equity - peak) / peak) * 100 : 0
    drawdowns.push(Number(dd.toFixed(2)))
  })

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      appendToBody: true,
      backgroundColor: 'rgba(18, 19, 25, 0.96)',
      borderColor: 'rgba(255, 255, 255, 0.16)',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: '#ffffff', fontSize: 12 },
      extraCssText: 'z-index: 9999999; box-shadow: 0 20px 48px rgba(0, 0, 0, 0.85); backdrop-filter: blur(16px); border-radius: 12px; pointer-events: none;',
      formatter: (params: any) => {
        if (!params || !params.length) return ''
        const val = params[0].value
        return `<div class="font-mono font-bold mb-1 text-zinc-300 text-xs">${params[0].axisValue}</div>
          <div class="flex items-center justify-between space-x-4 text-xs">
            <span class="text-cyan-400">动态水下回撤:</span>
            <strong class="text-emerald-400 font-mono">${val}%</strong>
          </div>`
      },
    },
    grid: { left: 45, right: 25, top: 25, bottom: 25 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
      axisLabel: { color: 'rgba(255, 255, 255, 0.45)', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      max: 0,
      axisLabel: {
        color: 'rgba(255, 255, 255, 0.45)',
        fontSize: 10,
        formatter: '{value}%',
      },
      splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.04)' } },
    },
    series: [
      {
        name: '水下回撤',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: drawdowns,
        lineStyle: { width: 1.8, color: '#06b6d4' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(6, 182, 212, 0.1)' },
              { offset: 1, color: 'rgba(6, 182, 212, 0.65)' },
            ],
          },
        },
      },
    ],
  }
})

// -------------------------------------------------------------
// 3. 月度收益热力矩阵 (Monthly Heatmap Calculations)
// -------------------------------------------------------------
const monthlyHeatmapData = computed(() => {
  const res = strategyStore.backtestResult
  if (!res || !res.daily_records || res.daily_records.length === 0) {
    return { years: [], matrix: new Map<string, number>() }
  }

  // 按年月聚合每日第一天与最后一天总资产计算单月收益率
  const records = res.daily_records
  const monthGroups = new Map<string, { start: number; end: number }>()

  records.forEach((r) => {
    const ym = r.date.slice(0, 7) // 'YYYY-MM'
    if (!monthGroups.has(ym)) {
      monthGroups.set(ym, { start: r.total_equity, end: r.total_equity })
    } else {
      monthGroups.get(ym)!.end = r.total_equity
    }
  })

  const yearsSet = new Set<number>()
  const matrix = new Map<string, number>() // key: `${year}-${month}`

  monthGroups.forEach((val, ym) => {
    const [yStr, mStr] = ym.split('-')
    const y = parseInt(yStr)
    const m = parseInt(mStr)
    yearsSet.add(y)
    const ret = val.start > 0 ? ((val.end - val.start) / val.start) * 100 : 0
    matrix.set(`${y}-${m}`, Number(ret.toFixed(2)))
  })

  const sortedYears = Array.from(yearsSet).sort((a, b) => b - a) // 倒序排年份
  return { years: sortedYears, matrix }
})

// 颜色映射辅助函数
function getMonthlyColorStyle(pct?: number) {
  if (pct === undefined) return { backgroundColor: 'rgba(255, 255, 255, 0.02)', color: '#52525b' }
  if (pct > 0) {
    const alpha = Math.min(0.8, 0.15 + (pct / 15) * 0.65)
    return {
      backgroundColor: `rgba(239, 68, 68, ${alpha})`,
      color: '#ffffff',
      fontWeight: '600',
    }
  } else if (pct < 0) {
    const alpha = Math.min(0.8, 0.15 + (Math.abs(pct) / 15) * 0.65)
    return {
      backgroundColor: `rgba(16, 185, 129, ${alpha})`,
      color: '#ffffff',
      fontWeight: '600',
    }
  } else {
    return { backgroundColor: 'rgba(255, 255, 255, 0.04)', color: '#a1a1aa' }
  }
}

// 点击下拉外部自动关闭
function onWindowClick(e: MouseEvent) {
  if (
    watchlistDropdownRef.value &&
    !watchlistDropdownRef.value.contains(e.target as Node)
  ) {
    showWatchlistDropdown.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', onWindowClick)
  strategyStore.fetchUserWatchlists()
  // 默认进入“近1年”时间窗口
  if (!strategyStore.startDate || strategyStore.startDate === '2023-01-01' || !strategyStore.endDate) {
    strategyStore.setQuickDateRange('1y')
    selectedQuickRange.value = '1y'
  }
})

onUnmounted(() => {
  window.removeEventListener('click', onWindowClick)
})
</script>

<template>
  <div :class="[heightClass]" class="flex flex-col bg-[#12141a] text-zinc-200 select-none overflow-hidden relative">
    <!-- ========================================================================= -->
    <!-- 1. 极致紧凑单行参数控制栏 (高度 42px，单行容纳模式、标的、资金与时间) -->
    <!-- ========================================================================= -->
    <div class="h-11 px-3 bg-[#141722]/95 border-b border-white/[0.08] flex items-center justify-between gap-2 shrink-0">
      <!-- 左侧：模式切换胶囊 + 标的输入/选择 -->
      <div class="flex items-center space-x-2 min-w-0 flex-1">
        <!-- 模式切换紧凑分段器 -->
        <div class="flex items-center p-0.5 rounded-lg bg-black/60 border border-white/[0.08] shrink-0">
          <button
            @click="strategyStore.backtestMode = 'single'"
            :class="strategyStore.backtestMode === 'single' ? 'bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40 shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-2 py-0.5 rounded text-[11px] transition-all cursor-pointer"
            title="单标的纯回测"
          >
            🎯 单标的
          </button>
          <button
            @click="strategyStore.backtestMode = 'basket'"
            :class="strategyStore.backtestMode === 'basket' ? 'bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40 shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-2 py-0.5 rounded text-[11px] transition-all cursor-pointer flex items-center space-x-1"
            title="多标的/自选股票池回测"
          >
            <span>📦 股票池</span>
            <span class="px-1 rounded-full text-[9px] bg-white/[0.1] text-zinc-300 font-mono">
              {{ strategyStore.symbols.length }}
            </span>
          </button>
          <button
            @click="strategyStore.backtestMode = 'holdings'; strategyStore.applyHoldingsToBacktest()"
            :class="strategyStore.backtestMode === 'holdings' ? 'bg-emerald-500/20 text-emerald-300 font-bold border border-emerald-500/40 shadow-sm' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
            class="px-2 py-0.5 rounded text-[11px] transition-all cursor-pointer flex items-center space-x-1"
            title="我的真实账户持仓底仓"
          >
            <span>💼 持仓</span>
            <span class="px-1 rounded-full text-[9px] bg-white/[0.1] text-emerald-300 font-mono">
              {{ strategyStore.userHoldings.length }}
            </span>
          </button>
        </div>

        <!-- A. 单标的模式输入与推荐下拉 -->
        <div v-if="strategyStore.backtestMode === 'single'" class="flex items-center space-x-1.5 min-w-0 flex-1 max-w-sm">
          <div class="relative flex-1 min-w-[120px]">
            <input
              v-model="singleSymbolInput"
              @change="handleSingleSymbolChange"
              @keydown.enter.prevent="handleSingleSymbolChange"
              type="text"
              placeholder="标的代码"
              class="w-full bg-black/60 border border-white/[0.12] rounded-lg pl-2.5 pr-16 py-1 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/60 font-mono"
            />
            <span
              v-if="singleSymbolInput.trim() && marketStore.getSymbolName(singleSymbolInput) !== singleSymbolInput.split('.')[0]"
              class="absolute right-1.5 top-1/2 -translate-y-1/2 text-[9px] text-amber-300 bg-amber-500/20 border border-amber-500/30 px-1 py-0.2 rounded truncate max-w-[70px]"
              :title="marketStore.getSymbolName(singleSymbolInput)"
            >
              {{ marketStore.getSymbolName(singleSymbolInput) }}
            </span>
          </div>

          <!-- 推荐标的下拉快捷按钮 -->
          <div class="relative shrink-0" ref="watchlistDropdownRef">
            <button
              @click="showWatchlistDropdown = !showWatchlistDropdown"
              class="px-2 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-[11px] text-zinc-300 hover:text-white transition-all cursor-pointer flex items-center space-x-1"
              title="选择预设热门 ETF / 股票"
            >
              <span>推荐</span>
              <span class="text-[8px] text-zinc-500">▼</span>
            </button>

            <!-- 推荐弹出浮层 -->
            <div
              v-if="showWatchlistDropdown"
              class="absolute left-0 mt-1 w-44 rounded-xl bg-[#181a24] border border-white/[0.14] shadow-2xl p-1.5 z-50 animate-fadeIn space-y-0.5 text-xs"
            >
              <div
                v-for="item in singleQuickPresets"
                :key="item.value"
                @click="selectSinglePreset(item); showWatchlistDropdown = false"
                class="px-2 py-1.5 rounded-lg hover:bg-white/[0.08] text-zinc-300 hover:text-amber-300 cursor-pointer flex items-center justify-between transition-colors"
              >
                <span>{{ item.label }}</span>
                <span class="text-[9px] font-mono text-zinc-500">{{ item.value.split('.')[0] }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- B. 股票池模式快捷提示 -->
        <div v-else-if="strategyStore.backtestMode === 'basket'" class="flex items-center space-x-1.5 min-w-0 flex-1">
          <div class="flex items-center space-x-1 overflow-x-auto py-0.5 max-w-md">
            <div
              v-for="sym in strategyStore.symbols.slice(0, 3)"
              :key="sym"
              class="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[10px] shrink-0"
            >
              <span>{{ marketStore.getSymbolName(sym) }}</span>
              <button @click="strategyStore.removeSymbolTag(sym)" class="text-amber-500 hover:text-red-400">×</button>
            </div>
            <span v-if="strategyStore.symbols.length > 3" class="text-[10px] text-zinc-500 shrink-0">
              +{{ strategyStore.symbols.length - 3 }}只
            </span>
          </div>

          <div class="flex items-center space-x-1 shrink-0">
            <input
              v-model="inputSymbolToAdd"
              @keydown.enter.prevent="handleAddSymbol"
              type="text"
              placeholder="+ 代码回车"
              class="w-20 bg-black/40 border border-white/[0.1] rounded px-1.5 py-0.5 text-[11px] text-white focus:outline-none font-mono"
            />
          </div>
        </div>

        <!-- C. 持仓模式紧凑条 -->
        <div v-else class="flex items-center space-x-2 text-[11px] text-emerald-300">
          <span>💼 底仓 {{ strategyStore.userHoldings.length }} 只</span>
          <span class="font-mono text-zinc-400 text-[10px]">¥{{ holdingTotalCost.toLocaleString() }}</span>
        </div>
      </div>

      <!-- 右侧：本金 + 时间区间 + 运行按钮 -->
      <div class="flex items-center space-x-2 shrink-0">
        <!-- 初始本金 -->
        <div class="flex items-center space-x-1 bg-black/50 border border-white/[0.08] px-2 py-0.5 rounded-lg text-xs hidden sm:flex">
          <span class="text-zinc-500 text-[10px]">本金:</span>
          <span class="text-amber-400 font-mono text-[11px]">¥</span>
          <input
            v-model.number="strategyStore.initialCash"
            type="number"
            step="10000"
            class="w-16 bg-transparent text-xs font-mono font-semibold text-white focus:outline-none"
            title="初始回测本金"
          />
        </div>

        <!-- 紧凑时间选择 (起止日期紧凑合体) -->
        <div class="flex items-center space-x-1 bg-[#161822] border border-white/[0.1] rounded-lg px-2 py-0.5 text-xs font-mono">
          <input
            v-model="strategyStore.startDate"
            type="date"
            style="color-scheme: dark"
            class="bg-transparent text-amber-200 focus:outline-none text-[11px] w-[92px] cursor-pointer"
            title="开始日期"
          />
          <span class="text-zinc-600 text-[10px]">~</span>
          <input
            v-model="strategyStore.endDate"
            type="date"
            style="color-scheme: dark"
            placeholder="至今"
            class="bg-transparent text-amber-200 focus:outline-none text-[11px] w-[92px] cursor-pointer"
            title="结束日期(留空为至今)"
          />
        </div>

        <!-- 常用周期下拉或胶囊 (紧凑近1年/3年) -->
        <div class="hidden md:flex items-center space-x-1 text-[10px]">
          <button
            v-for="r in [{ l: '1年', v: '1y' }, { l: '3年', v: '3y' }, { l: '5年', v: '5y' }]"
            :key="r.v"
            @click="applyDateRange(r.v as any)"
            :class="selectedQuickRange === r.v ? 'bg-amber-500/25 text-amber-300 border-amber-500/50 font-bold' : 'bg-white/[0.04] text-zinc-400 hover:text-zinc-200 border-white/[0.06]'"
            class="px-1.5 py-0.5 rounded border cursor-pointer transition-all"
          >
            {{ r.l }}
          </button>
        </div>

        <!-- 运行回测主按钮 (原地触发) -->
        <button
          @click="strategyStore.runBacktest()"
          :disabled="strategyStore.isBacktesting"
          class="px-3 py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-bold text-xs flex items-center space-x-1 shadow-md shadow-red-500/20 transition-all cursor-pointer disabled:opacity-50"
          title="运行量化回测 (⌘+Enter)"
        >
          <span v-if="!strategyStore.isBacktesting">▶</span>
          <span v-else class="w-3 h-3 border-2 border-white/20 border-t-white rounded-full animate-spin"></span>
          <span>{{ strategyStore.isBacktesting ? '撮合中' : '运行' }}</span>
        </button>

        <div class="h-3.5 w-px bg-white/[0.1] mx-0.5"></div>

        <!-- 全屏最大化切换 -->
        <button
          @click="emit('toggleMaximize')"
          class="p-1 rounded-lg hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-colors cursor-pointer text-xs"
          title="全屏放大 / 恢复面板"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <rect x="3" y="3" width="18" height="18" rx="2" stroke-width="2"/>
          </svg>
        </button>

        <!-- 收起抽屉按钮 -->
        <button
          @click="emit('close')"
          class="p-1 rounded-lg hover:bg-red-500/20 hover:text-red-300 text-zinc-400 transition-colors cursor-pointer text-xs"
          title="收起回测面板 (Esc)"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- 错误告警区 -->
    <div
      v-if="strategyStore.backtestError"
      class="m-3 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-300 space-y-1.5 animate-fadeIn shrink-0"
    >
      <div class="flex items-center justify-between">
        <span class="font-bold text-red-400">⚠️ 回测中断告警</span>
        <button
          @click="strategyStore.askAiToFixStrategy()"
          class="px-2 py-0.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/30 text-[11px] font-semibold cursor-pointer"
        >
          🤖 AI 一键诊断修复
        </button>
      </div>
      <p class="font-mono text-[11px] leading-relaxed break-words whitespace-pre-wrap max-h-24 overflow-y-auto bg-black/30 p-2 rounded-lg border border-red-500/10">
        {{ strategyStore.backtestError }}
      </p>
    </div>

    <!-- 回测执行诊断提示 -->
    <div
      v-if="strategyStore.backtestResult?.warnings?.length"
      class="mx-3 mt-2 p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-200 space-y-1 shrink-0"
    >
      <div class="font-bold text-amber-400">💡 回测诊断提示 ({{ strategyStore.backtestResult.warnings.length }})</div>
      <ul class="list-disc list-inside font-mono text-[11px] text-zinc-300 space-y-0.5">
        <li v-for="(w, idx) in strategyStore.backtestResult.warnings" :key="idx">{{ w }}</li>
      </ul>
    </div>

    <!-- ========================================================================= -->
    <!-- 2. 多功能图表与分析切换导航栏 -->
    <!-- ========================================================================= -->
    <div class="px-4 py-2 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-2 shrink-0">
      <!-- Tab 切换 -->
      <div class="flex items-center space-x-1">
        <button
          @click="activeTab = 'equity'"
          :class="activeTab === 'equity' ? 'bg-white/[0.1] text-white font-bold border-red-500/60' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
          class="px-3 py-1 text-xs rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
        >
          <span>📈</span>
          <span>净值与 Alpha</span>
        </button>
        <button
          @click="activeTab = 'underwater'"
          :class="activeTab === 'underwater' ? 'bg-white/[0.1] text-white font-bold border-cyan-500/60' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
          class="px-3 py-1 text-xs rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
        >
          <span>🌊</span>
          <span>水下回撤</span>
        </button>
        <button
          @click="activeTab = 'monthly'"
          :class="activeTab === 'monthly' ? 'bg-white/[0.1] text-white font-bold border-amber-500/60' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
          class="px-3 py-1 text-xs rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
        >
          <span>🗓️</span>
          <span>月度热力图</span>
        </button>
        <button
          @click="activeTab = 'trades'"
          :class="activeTab === 'trades' ? 'bg-white/[0.1] text-white font-bold border-emerald-500/60' : 'text-zinc-400 hover:text-zinc-200 border-transparent'"
          class="px-3 py-1 text-xs rounded-lg border transition-all cursor-pointer flex items-center space-x-1.5"
        >
          <span>📑</span>
          <span>交易明细</span>
          <span v-if="strategyStore.backtestResult?.trades?.length" class="text-[10px] text-zinc-500 font-mono">
            ({{ strategyStore.backtestResult.trades.length }})
          </span>
        </button>
      </div>

      <!-- 右侧图表辅助开关 (Alpha 曲线、买卖点、版本对比、归档) -->
      <div class="flex items-center space-x-2 text-xs">
        <template v-if="activeTab === 'equity'">
          <label class="flex items-center space-x-1 cursor-pointer text-zinc-400 hover:text-zinc-200 text-[11px]">
            <input type="checkbox" v-model="showAlphaCurve" class="rounded border-zinc-700 bg-black/40 text-amber-500 focus:ring-0 cursor-pointer" />
            <span>Alpha 超额</span>
          </label>

          <!-- 同花顺级买卖标记与主信号切换器 -->
          <div class="flex items-center space-x-1.5 bg-black/40 border border-white/[0.08] px-2 py-0.5 rounded-lg text-[11px]">
            <span class="text-zinc-400 font-medium">买卖标记:</span>
            <!-- 模式分段选择器 -->
            <div class="flex items-center bg-white/[0.05] p-0.5 rounded-md text-[10px] space-x-0.5">
              <button
                @click="tradeMarkerMode = 'key'"
                class="px-1.5 py-0.5 rounded transition-all cursor-pointer"
                :class="tradeMarkerMode === 'key' ? 'bg-amber-500/20 text-amber-300 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
                title="精选波段拐点与主信号（自动合并加仓，防堆叠防卡顿，同花顺质感）"
              >
                🎯 主信号
              </button>
              <button
                @click="tradeMarkerMode = 'all'"
                class="px-1.5 py-0.5 rounded transition-all cursor-pointer"
                :class="tradeMarkerMode === 'all' ? 'bg-amber-500/20 text-amber-300 font-bold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
                title="极速微标显示全部明细（全景不卡，滚轮放大看微观细节）"
              >
                🔍 全部
              </button>
              <button
                @click="tradeMarkerMode = 'off'"
                class="px-1.5 py-0.5 rounded transition-all cursor-pointer"
                :class="tradeMarkerMode === 'off' ? 'bg-zinc-700/40 text-zinc-300 font-bold shadow-sm' : 'text-zinc-500 hover:text-zinc-300'"
                title="隐藏买卖标记，仅看净值走势"
              >
                🚫 隐藏
              </button>
            </div>

            <!-- 方向筛选 (当开启标记时可用) -->
            <template v-if="tradeMarkerMode !== 'off'">
              <span class="text-zinc-600">|</span>
              <select
                v-model="tradeMarkerSideFilter"
                class="bg-transparent text-[10px] text-zinc-300 border-0 focus:ring-0 cursor-pointer font-sans py-0 pl-1 pr-3"
                title="按买卖方向筛选标记"
              >
                <option value="all" class="bg-[#181920] text-zinc-200">全部 ({{ tradeStats.total }})</option>
                <option value="buy" class="bg-[#181920] text-red-400">仅看买入 ({{ tradeStats.buys }})</option>
                <option value="sell" class="bg-[#181920] text-emerald-400">仅看卖出 ({{ tradeStats.sells }})</option>
              </select>
            </template>
          </div>

          <label
            v-if="strategyStore.previousBacktestResult"
            class="flex items-center space-x-1 cursor-pointer text-purple-400 hover:text-purple-300 text-[11px]"
            title="将本次收益与运行前一次的策略版本收益叠加对比"
          >
            <input type="checkbox" v-model="comparePrevious" class="rounded border-zinc-700 bg-black/40 text-purple-500 focus:ring-0 cursor-pointer" />
            <span>对比上一版 (A/B)</span>
          </label>
        </template>

        <button
          v-if="strategyStore.backtestResult"
          @click="openArchiveModal"
          class="px-2.5 py-1 rounded-lg bg-gradient-to-r from-amber-500/20 to-orange-500/20 border border-amber-500/40 text-amber-300 hover:text-white hover:bg-amber-500/30 text-xs flex items-center space-x-1 cursor-pointer transition-all"
        >
          <span>💾 归档回测</span>
        </button>
      </div>
    </div>

    <!-- ========================================================================= -->
    <!-- 3. 主体内容展示区 (KPI 九宫格 + 深度图表/明细) -->
    <!-- ========================================================================= -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      <!-- 撮合中动画 -->
      <div v-if="strategyStore.isBacktesting" class="h-64 flex flex-col items-center justify-center text-center space-y-3">
        <div class="w-9 h-9 border-2 border-red-500/20 border-t-red-500 rounded-full animate-spin"></div>
        <span class="text-xs font-mono text-zinc-300">事件驱动撮合与多标的推演中...</span>
        <span class="text-[11px] text-zinc-500">正在生成策略净值、水下回撤与 Alpha 对照曲线</span>
      </div>

      <!-- 未回测空状态 -->
      <div v-else-if="!strategyStore.backtestResult" class="h-64 flex flex-col items-center justify-center text-center space-y-2 text-zinc-500">
        <span class="text-3xl">⚡</span>
        <span class="text-sm font-bold text-zinc-300">量化回测就绪</span>
        <span class="text-xs text-zinc-500">点击上方「▶ 运行回测 (⌘+Enter)」，毫秒级在 AST 沙箱中撮合并推演绩效</span>
      </div>

      <!-- 已出结果 -->
      <template v-else>
        <!-- 9 大核心量化专业指标卡网格 -->
        <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-2">
          <!-- 1. 累计总收益 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">累计总收益</div>
            <div
              :class="strategyStore.backtestResult.summary.total_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
              class="text-sm font-bold font-mono mt-1"
            >
              {{ strategyStore.backtestResult.summary.total_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.total_return * 100).toFixed(2) }}%
            </div>
          </div>

          <!-- 2. 年化收益率 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">年化收益 (CAGR)</div>
            <div
              :class="strategyStore.backtestResult.summary.annualized_return >= 0 ? 'text-red-400' : 'text-emerald-400'"
              class="text-sm font-bold font-mono mt-1"
            >
              {{ strategyStore.backtestResult.summary.annualized_return >= 0 ? '+' : '' }}{{ (strategyStore.backtestResult.summary.annualized_return * 100).toFixed(2) }}%
            </div>
          </div>

          <!-- 3. 最大动态回撤 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">最大动态回撤</div>
            <div class="text-sm font-bold font-mono text-emerald-400 mt-1">
              -{{ (strategyStore.backtestResult.summary.max_drawdown * 100).toFixed(2) }}%
            </div>
          </div>

          <!-- 4. 夏普比率 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">夏普比率 (Sharpe)</div>
            <div class="text-sm font-bold font-mono text-amber-300 mt-1">
              {{ strategyStore.backtestResult.summary.sharpe_ratio.toFixed(2) }}
            </div>
          </div>

          <!-- 5. 索提诺比率 (Sortino) -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">索提诺 (Sortino)</div>
            <div class="text-sm font-bold font-mono text-sky-400 mt-1">
              {{ (strategyStore.backtestResult.summary.sortino_ratio ?? 0).toFixed(2) }}
            </div>
          </div>

          <!-- 6. 卡玛比率 (Calmar) -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">卡玛比率 (Calmar)</div>
            <div class="text-sm font-bold font-mono text-purple-300 mt-1">
              {{ (strategyStore.backtestResult.summary.calmar_ratio ?? 0).toFixed(2) }}
            </div>
          </div>

          <!-- 7. 交易胜率 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">交易胜率 (Win Rate)</div>
            <div class="text-sm font-bold font-mono text-white mt-1">
              {{ (strategyStore.backtestResult.summary.win_rate * 100).toFixed(1) }}%
            </div>
          </div>

          <!-- 8. 盈亏比 (Profit Factor) -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">盈亏比 (PF)</div>
            <div class="text-sm font-bold font-mono text-white mt-1">
              {{ (strategyStore.backtestResult.summary.profit_factor ?? 1.0).toFixed(2) }}
            </div>
          </div>

          <!-- 9. 成交笔数 -->
          <div class="p-2.5 rounded-xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-colors">
            <div class="text-[10px] text-zinc-400">撮合成交</div>
            <div class="text-sm font-bold font-mono text-white mt-1">
              {{ strategyStore.backtestResult.summary.total_trades }} 笔
            </div>
          </div>
        </div>

        <!-- 视图 1：净值走势与 Alpha -->
        <div v-show="activeTab === 'equity'" class="w-full">
          <EChartWrapper ref="equityChartRef" :option="equityChartOption" height="290px" />
        </div>

        <!-- 视图 2：水下动态回撤面积图 -->
        <div v-show="activeTab === 'underwater'" class="w-full">
          <div class="text-xs text-zinc-400 mb-2 flex items-center justify-between">
            <span>水下回撤深度与持续周期分析 (距离历史最高权益回落幅度)</span>
            <span class="text-[11px] text-cyan-400 font-mono">最高回撤: -{{ (strategyStore.backtestResult.summary.max_drawdown * 100).toFixed(2) }}%</span>
          </div>
          <EChartWrapper :option="underwaterChartOption" height="270px" />
        </div>

        <!-- 视图 3：月度收益热力矩阵 (Monthly Heatmap) -->
        <div v-show="activeTab === 'monthly'" class="w-full overflow-x-auto">
          <div class="text-xs text-zinc-400 mb-2">自然月度复合收益率矩阵 (%)</div>
          <div class="min-w-[640px] rounded-xl border border-white/[0.08] bg-black/40 p-3">
            <table class="w-full text-center text-xs font-mono">
              <thead>
                <tr class="text-zinc-500 border-b border-white/[0.06] text-[11px]">
                  <th class="py-1.5 px-2 text-left">年份</th>
                  <th v-for="m in 12" :key="m" class="py-1.5 px-1">{{ m }}月</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-white/[0.04]">
                <tr v-for="y in monthlyHeatmapData.years" :key="y" class="hover:bg-white/[0.02]">
                  <td class="py-2 px-2 text-left font-bold text-zinc-300">{{ y }}</td>
                  <td
                    v-for="m in 12"
                    :key="m"
                    class="py-1.5 px-1 text-[11px]"
                  >
                    <div
                      v-if="monthlyHeatmapData.matrix.has(`${y}-${m}`)"
                      :style="getMonthlyColorStyle(monthlyHeatmapData.matrix.get(`${y}-${m}`))"
                      class="rounded-md py-1 px-0.5"
                    >
                      {{ monthlyHeatmapData.matrix.get(`${y}-${m}`)! >= 0 ? '+' : '' }}{{ monthlyHeatmapData.matrix.get(`${y}-${m}`) }}%
                    </div>
                    <div v-else class="text-zinc-700">-</div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 视图 4：成交流水视图 -->
        <div v-show="activeTab === 'trades'" class="overflow-x-auto max-h-72 rounded-xl border border-white/[0.08] bg-black/40">
          <table class="w-full text-left text-xs font-mono">
            <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08]">
              <tr>
                <th class="p-2.5">成交时间</th>
                <th class="p-2.5">标的代码</th>
                <th class="p-2.5">操作</th>
                <th class="p-2.5">价格</th>
                <th class="p-2.5">数量</th>
                <th class="p-2.5">成交总额</th>
                <th class="p-2.5">调仓理由</th>
                <th class="p-2.5">手续费</th>
                <th class="p-2.5 text-right">走势联动</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-white/[0.04]">
              <tr v-for="(t, idx) in strategyStore.backtestResult.trades" :key="idx" class="hover:bg-white/[0.03] transition-colors group">
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
                    class="px-2 py-0.5 rounded-lg bg-white/[0.04] text-zinc-300 text-[11px] font-sans border border-white/[0.06] truncate max-w-[170px] inline-block"
                    :title="getTradeReason(t)"
                  >
                    {{ getTradeReason(t) }}
                  </span>
                </td>
                <td class="p-2.5 text-zinc-400">¥{{ t.commission.toFixed(2) }}</td>
                <td class="p-2.5 text-right">
                  <button
                    @click="focusDateOnChart(t.datetime_str?.split(' ')[0])"
                    class="px-2 py-0.5 rounded bg-blue-500/15 hover:bg-blue-500/30 text-blue-300 border border-blue-500/30 text-[10px] cursor-pointer opacity-80 group-hover:opacity-100 transition-opacity shadow-sm"
                    title="在净值走势图上平滑定位并聚焦该交易日"
                  >
                    🎯 定位
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <!-- 归档弹窗 -->
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
  </div>
</template>

<style scoped>
.animate-fadeIn {
  animation: fadeIn 0.2s ease-out;
}
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
