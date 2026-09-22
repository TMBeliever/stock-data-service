<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  useAssetStore,
  ASSET_CATEGORIES,
  type AssetCategory,
  type AssetItem,
  type CreateAssetPayload,
  type UpdateAssetPayload,
} from '@/stores/asset'
import { useAuthStore } from '@/stores/auth'
import { useMarketStore, type SymbolItem } from '@/stores/market'
import EChartWrapper from '@/components/EChartWrapper.vue'

const router = useRouter()
const assetStore = useAssetStore()
const authStore = useAuthStore()
const marketStore = useMarketStore()

// 支持的常用资产计价币种
const SUPPORTED_CURRENCIES = [
  { code: 'CNY', label: '人民币 (¥)', symbol: '¥' },
  { code: 'USD', label: '美元 ($)', symbol: '$' },
  { code: 'HKD', label: '港币 (HK$)', symbol: 'HK$' },
  { code: 'USDT', label: '泰达币 (USDT)', symbol: '₮' },
  { code: 'EUR', label: '欧元 (€)', symbol: '€' },
  { code: 'JPY', label: '日元 (JP¥)', symbol: 'JP¥' },
  { code: 'GBP', label: '英镑 (£)', symbol: '£' },
]

// 提示 Toast
const toastMsg = ref('')
const toastType = ref<'success' | 'warn' | 'error'>('success')
function showToast(msg: string, type: 'success' | 'warn' | 'error' = 'success') {
  toastMsg.value = msg
  toastType.value = type
  setTimeout(() => {
    toastMsg.value = ''
  }, 2800)
}

// 排序模式: 'market_value_desc' | 'market_value_asc' | 'pnl_desc' | 'pnl_asc'
const sortMode = ref<'market_value_desc' | 'pnl_desc' | 'pnl_asc' | 'name'>('market_value_desc')

// 弹窗状态 (新增 / 编辑)
const showModal = ref(false)
const modalMode = ref<'create' | 'edit'>('create')
const editingAssetId = ref<string | number | null>(null)
const isSubmitting = ref(false)

// 表单字段
const formCategory = ref<AssetCategory>('EQUITY')
const formName = ref('')
const formSymbol = ref('')
const formAmount = ref<number | string>(100)
const formCostPrice = ref<number | string>(10.0)
const formManualPrice = ref<number | string>('')
const formCurrency = ref('CNY')
const formNote = ref('')

// 标的实时智能反查与下拉联想状态
const symbolSuggestions = ref<SymbolItem[]>([])
const showSuggestions = ref(false)
const isSearchingSymbol = ref(false)
const activeSuggestionPrice = ref<number | null>(null)
const activeSuggestionName = ref<string | null>(null)
let symbolSearchTimer: any = null

// 打开新增资产弹窗
function openCreateModal(presetCategory?: AssetCategory) {
  modalMode.value = 'create'
  editingAssetId.value = null
  formCategory.value = presetCategory || 'EQUITY'
  formName.value = ''
  formSymbol.value = ''
  formAmount.value = formCategory.value === 'EQUITY' ? 1000 : 1
  formCostPrice.value = formCategory.value === 'CASH' ? 1 : 10.0
  formManualPrice.value = ''
  formCurrency.value = 'CNY'
  formNote.value = ''
  showSuggestions.value = false
  symbolSuggestions.value = []
  activeSuggestionPrice.value = null
  activeSuggestionName.value = null
  showModal.value = true
}

// 打开编辑资产弹窗
function openEditModal(item: AssetItem) {
  modalMode.value = 'edit'
  editingAssetId.value = item.id
  formCategory.value = item.category
  formName.value = item.name
  formSymbol.value = item.symbol || ''
  formAmount.value = item.amount
  formCostPrice.value = item.cost_price
  formManualPrice.value = item.manual_price !== null && item.manual_price !== undefined ? item.manual_price : ''
  formCurrency.value = item.currency || 'CNY'
  formNote.value = item.note || ''
  showSuggestions.value = false
  symbolSuggestions.value = []
  activeSuggestionPrice.value = item.current_price || null
  activeSuggestionName.value = item.name
  showModal.value = true
}

// 搜索框输入防抖查询股票、ETF 与公募基金
function handleSymbolInput(e: Event) {
  const input = (e.target as HTMLInputElement).value
  formSymbol.value = input
  clearTimeout(symbolSearchTimer)
  const q = input.trim()
  if (!q) {
    symbolSuggestions.value = []
    showSuggestions.value = false
    activeSuggestionPrice.value = null
    activeSuggestionName.value = null
    return
  }

  symbolSearchTimer = setTimeout(async () => {
    isSearchingSymbol.value = true
    try {
      const results = await marketStore.searchSymbols(q, 'all', 8)
      symbolSuggestions.value = results
      showSuggestions.value = results.length > 0
    } catch (err) {
      console.error('标的反查异常:', err)
    } finally {
      isSearchingSymbol.value = false
    }
  }, 160)
}

// 选中联想结果自动回填代码、名称、币种与现价/净值
function selectSuggestion(item: SymbolItem) {
  formSymbol.value = item.symbol
  formName.value = item.name
  activeSuggestionName.value = item.name

  // 币种推断
  if (item.market === 'US') {
    formCurrency.value = 'USD'
  } else if (item.market === 'HK') {
    formCurrency.value = 'HKD'
  } else if (formCurrency.value !== 'USD' && formCurrency.value !== 'HKD') {
    formCurrency.value = 'CNY'
  }

  // 参考现价/净值
  if (item.latest_price !== null && item.latest_price !== undefined) {
    activeSuggestionPrice.value = item.latest_price
    if (!formCostPrice.value || Number(formCostPrice.value) === 0) {
      formCostPrice.value = item.latest_price
    }
  } else {
    activeSuggestionPrice.value = null
  }

  // 大类智能推导
  if (item.asset_type === 'ETF' || item.asset_type === 'STK' || item.asset_type === 'FND') {
    formCategory.value = 'EQUITY'
  }

  showSuggestions.value = false
}

// 一键将最新价格/净值填入买入成本
function applySuggestionPrice() {
  if (activeSuggestionPrice.value !== null && activeSuggestionPrice.value !== undefined) {
    formCostPrice.value = activeSuggestionPrice.value
    showToast(`✅ 已填入最新参考单价 ¥${activeSuggestionPrice.value}`)
  }
}

// 失去焦点时的代码标准化保底与自动回填
async function handleSymbolInputBlur() {
  setTimeout(() => {
    showSuggestions.value = false
  }, 250)

  const raw = formSymbol.value.trim().toUpperCase()
  if (!raw) return

  // 1. 如果已有下拉建议，优先精确匹配
  const exactMatch = symbolSuggestions.value.find(
    (s) => s.ticker === raw || s.symbol === raw || s.symbol.startsWith(raw + '.')
  )
  if (exactMatch) {
    selectSuggestion(exactMatch)
    return
  }

  // 2. 6 位纯数字代码规范化
  if (/^\d{6}$/.test(raw)) {
    if (raw.startsWith('51') || raw.startsWith('56') || raw.startsWith('58')) {
      formSymbol.value = `${raw}.SH.ETF`
    } else if (raw.startsWith('15') || raw.startsWith('16')) {
      formSymbol.value = `${raw}.SZ.ETF`
    } else if (raw.startsWith('60') || raw.startsWith('68')) {
      formSymbol.value = `${raw}.SH.STK`
    } else if (raw.startsWith('000') || raw.startsWith('001') || raw.startsWith('002') || raw.startsWith('003') || raw.startsWith('300') || raw.startsWith('301')) {
      formSymbol.value = `${raw}.SZ.STK`
    } else if (raw.startsWith('8') || raw.startsWith('4') || raw.startsWith('9')) {
      formSymbol.value = `${raw}.BJ.STK`
    } else {
      // 开放式公募基金号段 (如 006242, 005827, 012414, 110011 等)
      formSymbol.value = `${raw}.OF.FND`
    }

    // 若当前资产名称为空，发起一次反查并回填名称与最新价格/净值
    if (!formName.value) {
      try {
        const results = await marketStore.searchSymbols(raw, 'all', 1)
        if (results && results.length > 0) {
          const match = results[0]
          if (match.ticker === raw || match.symbol.startsWith(raw)) {
            selectSuggestion(match)
          }
        }
      } catch (err) {
        // ignore
      }
    }
  } else if (/^\d{4,5}$/.test(raw)) {
    // 4~5位港股 (如 700 -> 00700.HK.STK)
    formSymbol.value = `${raw.padStart(5, '0')}.HK.STK`
    if (!formName.value) {
      try {
        const results = await marketStore.searchSymbols(formSymbol.value, 'all', 1)
        if (results && results.length > 0) {
          selectSuggestion(results[0])
        }
      } catch (err) {
        // ignore
      }
    }
  }
}


// 提交资产表单
async function handleSubmitAsset() {
  const name = formName.value.trim()
  if (!name) {
    showToast('⚠️ 请输入资产名称', 'warn')
    return
  }

  const amount = Number(formAmount.value)
  if (isNaN(amount) || amount < 0) {
    showToast('⚠️ 请输入合法的持有数量或本金', 'warn')
    return
  }

  const costPrice = Number(formCostPrice.value) || 0
  const manualPrice = formManualPrice.value !== '' && formManualPrice.value !== null ? Number(formManualPrice.value) : null

  isSubmitting.value = true
  try {
    if (modalMode.value === 'create') {
      const payload: CreateAssetPayload = {
        category: formCategory.value,
        name,
        symbol: formSymbol.value.trim().toUpperCase() || null,
        amount,
        cost_price: costPrice,
        manual_price: manualPrice,
        currency: formCurrency.value,
        note: formNote.value.trim() || null,
      }
      await assetStore.createAsset(payload)
      showToast(`✅ 成功录入资产「${name}」！`)
    } else if (editingAssetId.value) {
      const payload: UpdateAssetPayload = {
        category: formCategory.value,
        name,
        symbol: formSymbol.value.trim().toUpperCase() || null,
        amount,
        cost_price: costPrice,
        manual_price: manualPrice,
        currency: formCurrency.value,
        note: formNote.value.trim() || null,
      }
      await assetStore.updateAsset(editingAssetId.value, payload)
      showToast(`✅ 资产「${name}」已更新！`)
    }
    showModal.value = false
  } catch (err: any) {
    showToast(err.message || '操作失败，请重试', 'error')
  } finally {
    isSubmitting.value = false
  }
}

// 删除资产
async function handleDeleteAsset(item: AssetItem) {
  if (confirm(`确认删除资产「${item.name}」吗？此操作不可撤销。`)) {
    try {
      await assetStore.deleteAsset(item.id)
      showToast(`🗑️ 已删除资产「${item.name}」`)
    } catch (err: any) {
      showToast(err.message || '删除失败', 'error')
    }
  }
}

// 刷新估值
async function handleRefresh() {
  await assetStore.fetchOverview(true)
  showToast('🔄 最新资产估值与行情已同步！')
}

// 资产列表排序与过滤
const sortedItems = computed(() => {
  const list = [...assetStore.filteredItems]
  return list.sort((a, b) => {
    if (sortMode.value === 'market_value_desc') return b.market_value - a.market_value
    if (sortMode.value === 'pnl_desc') return b.unrealized_pnl - a.unrealized_pnl
    if (sortMode.value === 'pnl_asc') return a.unrealized_pnl - b.unrealized_pnl
    if (sortMode.value === 'name') return a.name.localeCompare(b.name, 'zh-CN')
    return 0
  })
})

// ECharts 资产配置环形图 (Donut Chart) 配置
const chartOption = computed(() => {
  const breakdown = assetStore.overview?.category_breakdown || ({} as any)
  const data = Object.entries(breakdown)
    .filter(([key, val]: [string, any]) => key !== 'LIABILITY' && (val?.market_value || 0) > 0)
    .map(([key, val]: [string, any]) => {
      const meta = ASSET_CATEGORIES[key as AssetCategory]
      return {
        name: meta?.label || key,
        value: Math.round(val.market_value),
        itemStyle: { color: meta?.color || '#a1a1aa' },
      }
    })

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        return `
          <div style="font-size: 12px; font-weight: 600; margin-bottom: 4px;">${params.name}</div>
          <div style="font-family: monospace; color: #a1a1aa;">
            评估总值: <b style="color:#fff;">¥${Number(params.value).toLocaleString('zh-CN')}</b><br/>
            资产占比: <b style="color:#38bdf8;">${params.percent}%</b>
          </div>
        `
      },
      backgroundColor: 'rgba(15, 17, 26, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      borderWidth: 1,
      padding: [8, 12],
    },
    legend: {
      orient: 'vertical',
      right: '6%',
      top: 'middle',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 10,
      textStyle: {
        color: '#94a3b8',
        fontSize: 11,
      },
      formatter: (name: string) => {
        const item = data.find((d) => d.name === name)
        if (!item || !assetStore.totalAssets) return name
        const pct = ((item.value / assetStore.totalAssets) * 100).toFixed(1)
        return `${name} (${pct}%)`
      },
    },
    series: [
      {
        name: '资产配置大类',
        type: 'pie',
        radius: ['52%', '78%'],
        center: ['35%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 6,
          borderColor: '#0a0a0c',
          borderWidth: 2,
        },
        label: { show: false },
        emphasis: {
          scale: true,
          scaleSize: 6,
          label: {
            show: true,
            fontSize: 12,
            fontWeight: 'bold',
            color: '#fff',
            formatter: '{b}\n{d}%',
          },
        },
        data: data.length > 0 ? data : [{ name: '暂无正向资产', value: 1, itemStyle: { color: '#27272a' } }],
      },
    ],
  }
})

// 生命周期与监听
onMounted(() => {
  assetStore.fetchOverview()
})

watch(
  () => authStore.isLoggedIn,
  () => {
    assetStore.fetchOverview()
  }
)
</script>

<template>
  <div class="space-y-6 pb-16">
    <!-- Toast 通知条 -->
    <div
      v-if="toastMsg"
      class="fixed top-18 right-6 z-50 px-4 py-2.5 rounded-xl shadow-2xl backdrop-blur-md border text-xs font-semibold flex items-center space-x-2 transition-all animate-bounce-in"
      :class="
        toastType === 'success'
          ? 'bg-emerald-950/80 border-emerald-500/40 text-emerald-200'
          : toastType === 'warn'
            ? 'bg-amber-950/80 border-amber-500/40 text-amber-200'
            : 'bg-rose-950/80 border-rose-500/40 text-rose-200'
      "
    >
      <span>{{ toastMsg }}</span>
    </div>

    <!-- 1. 顶部 Header 栏 -->
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] backdrop-blur-sm">
      <div class="space-y-1">
        <div class="flex items-center space-x-2.5">
          <h1 class="text-xl font-bold tracking-tight text-white flex items-center space-x-2">
            <span>💼</span>
            <span>全景资产看板</span>
          </h1>
          <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/15 text-blue-400 border border-blue-500/30">
            PRO WEALTH
          </span>
          <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1 animate-pulse"></span>
            微服务实时估值
          </span>
        </div>
        <p class="text-xs text-zinc-400">
          全品类资产穿透汇总 · 股票/ETF实时行情自动联动 · 负债穿透与家庭真实净资产中枢
        </p>
      </div>

      <!-- 右侧动作按钮 -->
      <div class="flex items-center space-x-2.5 shrink-0">
        <button
          @click="handleRefresh"
          :disabled="assetStore.refreshing"
          class="px-3.5 py-2 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] text-zinc-300 hover:text-white border border-white/[0.08] text-xs font-semibold flex items-center space-x-1.5 transition-all cursor-pointer disabled:opacity-50"
          title="重新拉取最新股票快照与资产估值"
        >
          <span :class="{ 'animate-spin': assetStore.refreshing }">🔄</span>
          <span>{{ assetStore.refreshing ? '估值同步中...' : '刷新行情估值' }}</span>
        </button>

        <button
          @click="openCreateModal()"
          class="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-bold text-xs shadow-lg shadow-blue-500/20 flex items-center space-x-1.5 transition-all cursor-pointer group"
        >
          <span class="text-sm font-bold group-hover:scale-110 transition-transform">➕</span>
          <span>录入新资产</span>
        </button>
      </div>
    </div>

    <!-- 2. 核心 KPI 4 块度量大卡片 -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <!-- KPI 1: 真实净资产 (主视觉) -->
      <div class="p-5 rounded-2xl bg-gradient-to-br from-emerald-500/10 via-teal-500/5 to-transparent border border-emerald-500/30 shadow-lg shadow-emerald-500/5 relative overflow-hidden group">
        <div class="absolute -right-6 -bottom-6 w-24 h-24 bg-emerald-500/10 rounded-full blur-2xl group-hover:bg-emerald-500/20 transition-all pointer-events-none"></div>
        <div class="flex items-center justify-between text-xs text-emerald-400 font-semibold mb-1">
          <span class="flex items-center space-x-1.5">
            <span>💳</span>
            <span>真实净资产 (Net Worth)</span>
          </span>
          <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300">资产 - 负债</span>
        </div>
        <div class="text-2xl lg:text-3xl font-bold font-mono tracking-tight text-white mt-2">
          ¥{{ assetStore.netWorth.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
        </div>
        <div class="mt-2 text-[11px] text-zinc-400 flex items-center justify-between font-mono">
          <span>总资产 ¥{{ (assetStore.totalAssets / 10000).toFixed(1) }}万</span>
          <span class="text-zinc-600">|</span>
          <span class="text-rose-400">负债 ¥{{ (assetStore.totalLiabilities / 10000).toFixed(1) }}万</span>
        </div>
      </div>

      <!-- KPI 2: 总资产 (Gross Assets) -->
      <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-all">
        <div class="flex items-center justify-between text-xs text-zinc-400 font-medium mb-1">
          <span class="flex items-center space-x-1.5">
            <span>📈</span>
            <span>总资产估值 (Gross Assets)</span>
          </span>
          <span class="text-[10px] font-mono text-zinc-400">共 {{ assetStore.overview?.item_count || 0 }} 项</span>
        </div>
        <div class="text-2xl lg:text-3xl font-bold font-mono tracking-tight text-zinc-100 mt-2">
          ¥{{ assetStore.totalAssets.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
        </div>
        <div class="mt-2 text-[11px] text-zinc-400 font-mono">
          <span>投入总成本: ¥{{ assetStore.totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}</span>
        </div>
      </div>

      <!-- KPI 3: 总负债与负债率 -->
      <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-all">
        <div class="flex items-center justify-between text-xs text-zinc-400 font-medium mb-1">
          <span class="flex items-center space-x-1.5">
            <span>📉</span>
            <span>家庭总负债 (Liabilities)</span>
          </span>
          <span
            class="text-[10px] font-mono px-1.5 py-0.5 rounded"
            :class="assetStore.debtRatio > 50 ? 'bg-rose-500/20 text-rose-300' : 'bg-amber-500/20 text-amber-300'"
          >
            负债率 {{ assetStore.debtRatio.toFixed(1) }}%
          </span>
        </div>
        <div class="text-2xl lg:text-3xl font-bold font-mono tracking-tight text-rose-400 mt-2">
          ¥{{ assetStore.totalLiabilities.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
        </div>
        <div class="mt-2 text-[11px] text-zinc-400 font-mono">
          <span>{{ assetStore.totalLiabilities > 0 ? '房贷/车贷/消费信贷本金' : '当前无负债杠杆负担' }}</span>
        </div>
      </div>

      <!-- KPI 4: 累计浮动盈亏 -->
      <div class="p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-all">
        <div class="flex items-center justify-between text-xs text-zinc-400 font-medium mb-1">
          <span class="flex items-center space-x-1.5">
            <span>💰</span>
            <span>投资浮动总盈亏 (PnL)</span>
          </span>
          <span class="text-[10px] font-mono text-zinc-400">权益与理财项</span>
        </div>
        <div
          class="text-2xl lg:text-3xl font-bold font-mono tracking-tight mt-2 flex items-baseline space-x-2"
          :class="assetStore.unrealizedPnl >= 0 ? 'text-red-400' : 'text-emerald-400'"
        >
          <span>{{ assetStore.unrealizedPnl >= 0 ? '+' : '' }}¥{{ assetStore.unrealizedPnl.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}</span>
        </div>
        <div class="mt-2 text-[11px] font-mono font-semibold" :class="assetStore.unrealizedPnl >= 0 ? 'text-red-400/80' : 'text-emerald-400/80'">
          <span>总投资收益率: {{ assetStore.unrealizedPnl >= 0 ? '+' : '' }}{{ assetStore.unrealizedPnlPct.toFixed(2) }}%</span>
        </div>
      </div>
    </div>

    <!-- 3. 资产配置分布图谱 (Donut Chart + 分类指标明细) -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <!-- 左侧：ECharts 环形占比图 -->
      <div class="lg:col-span-6 p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] flex flex-col justify-between">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-bold text-white">📊 资产配置大类分布</span>
            <span class="text-[10px] text-zinc-400 font-mono">正向资产权重</span>
          </div>
          <span class="text-xs text-zinc-400 font-mono">总计 ¥{{ (assetStore.totalAssets / 10000).toFixed(1) }}万</span>
        </div>

        <div class="h-64 w-full">
          <EChartWrapper :option="chartOption" height="256px" />
        </div>
      </div>

      <!-- 右侧：7 大类明细卡片与配比栏 -->
      <div class="lg:col-span-6 p-5 rounded-2xl bg-white/[0.02] border border-white/[0.08] space-y-3">
        <div class="flex items-center justify-between pb-2 border-b border-white/[0.06]">
          <span class="text-xs font-bold text-zinc-300">各品类持仓统计与概览</span>
          <span class="text-[11px] text-zinc-400">点击品类快速筛选</span>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <div
            v-for="(meta, catKey) in ASSET_CATEGORIES"
            :key="catKey"
            @click="assetStore.activeCategoryFilter = assetStore.activeCategoryFilter === catKey ? 'ALL' : catKey"
            :class="
              assetStore.activeCategoryFilter === catKey
                ? 'bg-blue-500/15 border-blue-500/40'
                : 'bg-white/[0.015] hover:bg-white/[0.04] border-white/[0.06]'
            "
            class="p-2.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between group"
          >
            <div class="flex items-center space-x-2.5 min-w-0">
              <span class="text-base shrink-0">{{ meta.icon }}</span>
              <div class="flex flex-col min-w-0">
                <span class="text-xs font-semibold text-zinc-200 group-hover:text-white truncate">
                  {{ meta.label }}
                </span>
                <span class="text-[10px] text-zinc-400 font-mono">
                  {{ assetStore.overview?.category_breakdown?.[catKey]?.item_count || 0 }} 项资产
                </span>
              </div>
            </div>

            <div class="text-right font-mono shrink-0">
              <div
                class="text-xs font-bold"
                :class="meta.isLiability ? 'text-rose-400' : 'text-zinc-200'"
              >
                ¥{{ Math.round(assetStore.overview?.category_breakdown?.[catKey]?.market_value || 0).toLocaleString('zh-CN') }}
              </div>
              <div class="text-[10px] text-zinc-400">
                占比 {{ ((assetStore.overview?.category_breakdown?.[catKey]?.weight || 0) * 100).toFixed(1) }}%
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. 资产分类过滤与列表工具栏 -->
    <div class="p-4 rounded-2xl bg-white/[0.02] border border-white/[0.08] space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <!-- 类别筛选 Chips -->
        <div class="flex flex-wrap items-center gap-1.5">
          <button
            @click="assetStore.activeCategoryFilter = 'ALL'"
            :class="
              assetStore.activeCategoryFilter === 'ALL'
                ? 'bg-white/15 text-white font-bold border-white/20'
                : 'bg-white/[0.03] hover:bg-white/[0.07] text-zinc-400 border-white/[0.06]'
            "
            class="px-3 py-1.5 rounded-xl text-xs border transition-all cursor-pointer flex items-center space-x-1"
          >
            <span>全部类别</span>
            <span class="text-[10px] font-mono text-zinc-400 ml-1">({{ assetStore.overview?.item_count || 0 }})</span>
          </button>

          <button
            v-for="(meta, catKey) in ASSET_CATEGORIES"
            :key="catKey"
            @click="assetStore.activeCategoryFilter = catKey"
            :class="
              assetStore.activeCategoryFilter === catKey
                ? `${meta.badgeClass} font-bold border shadow-sm`
                : 'bg-white/[0.03] hover:bg-white/[0.07] text-zinc-400 border-white/[0.06]'
            "
            class="px-2.5 py-1.5 rounded-xl text-xs border transition-all cursor-pointer flex items-center space-x-1"
          >
            <span>{{ meta.icon }}</span>
            <span>{{ meta.label }}</span>
            <span class="text-[10px] font-mono opacity-80">({{ assetStore.overview?.category_breakdown?.[catKey]?.item_count || 0 }})</span>
          </button>
        </div>

        <!-- 搜索与排序 -->
        <div class="flex items-center space-x-2 w-full md:w-auto">
          <!-- 搜索输入框 -->
          <div class="relative flex-1 md:w-56">
            <input
              v-model="assetStore.searchQuery"
              type="text"
              placeholder="搜索名称 / 股票代码 / 备注..."
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
            />
            <span class="absolute left-2.5 top-2 text-xs text-zinc-500">🔍</span>
            <button
              v-if="assetStore.searchQuery"
              @click="assetStore.searchQuery = ''"
              class="absolute right-2.5 top-1.5 text-xs text-zinc-400 hover:text-white cursor-pointer"
            >
              ✕
            </button>
          </div>

          <!-- 排序下拉 -->
          <select
            v-model="sortMode"
            class="bg-black/50 border border-white/[0.1] rounded-xl px-2.5 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-blue-500/50 cursor-pointer"
          >
            <option value="market_value_desc">按估值市值从高到低</option>
            <option value="pnl_desc">按收益金额从高到低</option>
            <option value="pnl_asc">按收益金额从低到高</option>
            <option value="name">按资产名称排序</option>
          </select>
        </div>
      </div>

      <!-- 5. 资产数据明细表 -->
      <div class="rounded-xl border border-white/[0.08] overflow-x-auto bg-black/20">
        <table class="w-full text-left font-mono text-xs">
          <thead class="bg-white/[0.04] text-zinc-400 border-b border-white/[0.08] text-[11px]">
            <tr>
              <th class="p-3.5">资产标的</th>
              <th class="p-3.5">类别</th>
              <th class="p-3.5 text-right">持有数量/份额</th>
              <th class="p-3.5 text-right">成本单价</th>
              <th class="p-3.5 text-right">当前单价/行情</th>
              <th class="p-3.5 text-right">最新总估值</th>
              <th class="p-3.5 text-right">浮动盈亏</th>
              <th class="p-3.5 text-center">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-white/[0.04]">
            <tr
              v-for="item in sortedItems"
              :key="item.id"
              class="hover:bg-white/[0.03] transition-colors group"
            >
              <!-- 资产标的 -->
              <td class="p-3.5 font-sans">
                <div class="flex items-center space-x-3">
                  <div class="w-8 h-8 rounded-xl bg-black/40 border border-white/[0.08] flex items-center justify-center text-sm shrink-0 font-bold">
                    {{ ASSET_CATEGORIES[item.category]?.icon || '📦' }}
                  </div>
                  <div class="flex flex-col min-w-0">
                    <div class="flex items-center space-x-2">
                      <span class="font-bold text-white text-xs truncate max-w-[180px]">
                        {{ item.name }}
                      </span>
                      <span
                        v-if="item.symbol"
                        class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-blue-500/15 text-blue-300 border border-blue-500/20 shrink-0"
                      >
                        {{ item.symbol.split('.')[0] }}
                      </span>
                      <span
                        v-if="item.currency && item.currency !== 'CNY'"
                        class="px-1 py-0.2 rounded text-[9px] font-mono font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 shrink-0"
                      >
                        {{ item.currency }}
                      </span>
                    </div>
                    <div class="text-[11px] text-zinc-500 truncate max-w-[240px] mt-0.5">
                      {{ item.note || (item.symbol ? item.symbol : '无附加备注') }}
                    </div>
                  </div>
                </div>
              </td>

              <!-- 类别徽章 -->
              <td class="p-3.5">
                <span
                  class="px-2 py-0.5 rounded text-[10px] font-semibold border inline-flex items-center space-x-1"
                  :class="ASSET_CATEGORIES[item.category]?.badgeClass"
                >
                  <span>{{ ASSET_CATEGORIES[item.category]?.icon }}</span>
                  <span>{{ ASSET_CATEGORIES[item.category]?.label }}</span>
                </span>
              </td>

              <!-- 持有数量 -->
              <td class="p-3.5 text-right text-zinc-300 font-mono">
                {{ item.amount.toLocaleString('zh-CN', { maximumFractionDigits: 3 }) }}
              </td>

              <!-- 成本单价 -->
              <td class="p-3.5 text-right text-zinc-400 font-mono">
                {{ item.currency && item.currency !== 'CNY' ? item.currency : '¥' }} {{ item.cost_price.toFixed(item.cost_price > 10 ? 2 : 3) }}
              </td>

              <!-- 当前单价 / 行情 -->
              <td class="p-3.5 text-right font-mono">
                <div class="flex flex-col items-end">
                  <span class="font-bold text-white">
                    {{ item.currency && item.currency !== 'CNY' ? item.currency : '¥' }} {{ item.current_price.toFixed(item.current_price > 10 ? 2 : 3) }}
                  </span>
                  <span v-if="item.symbol" class="text-[10px] text-emerald-400 flex items-center space-x-0.5">
                    <span>⚡ 实时行情</span>
                  </span>
                  <span v-else class="text-[10px] text-zinc-500">
                    {{ item.manual_price !== null ? '手工估值' : '按成本单价' }}
                  </span>
                </div>
              </td>

              <!-- 最新总估值 (统一以本位币 CNY 汇总，并标注原币金额) -->
              <td class="p-3.5 text-right font-mono">
                <div class="flex flex-col items-end">
                  <span
                    class="font-bold text-sm"
                    :class="item.category === 'LIABILITY' ? 'text-rose-400' : 'text-zinc-100'"
                  >
                    ¥{{ item.market_value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
                  </span>
                  <span v-if="item.currency && item.currency !== 'CNY'" class="text-[10px] text-zinc-500">
                    {{ item.currency }} {{ (item.market_val_raw !== undefined ? item.market_val_raw : item.amount * item.current_price).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}
                    (汇率 {{ item.fx_rate || '--' }})
                  </span>
                </div>
              </td>


              <!-- 浮动盈亏 -->
              <td class="p-3.5 text-right font-mono">
                <template v-if="item.category !== 'CASH' && item.category !== 'LIABILITY'">
                  <div
                    class="font-bold"
                    :class="item.unrealized_pnl >= 0 ? 'text-red-400' : 'text-emerald-400'"
                  >
                    {{ item.unrealized_pnl >= 0 ? '+' : '' }}¥{{ item.unrealized_pnl.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) }}
                  </div>
                  <div
                    class="text-[10px]"
                    :class="item.unrealized_pnl >= 0 ? 'text-red-400/80' : 'text-emerald-400/80'"
                  >
                    {{ item.unrealized_pnl >= 0 ? '+' : '' }}{{ item.unrealized_pnl_pct.toFixed(2) }}%
                  </div>
                </template>
                <span v-else class="text-zinc-500">--</span>
              </td>

              <!-- 操作按钮 -->
              <td class="p-3.5 text-center">
                <div class="flex items-center justify-center space-x-1.5">
                  <!-- 若有股票代码，支持一键跳转行情详情 -->
                  <button
                    v-if="item.symbol"
                    @click="router.push(`/symbol/${encodeURIComponent(item.symbol)}`)"
                    class="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-colors text-[11px] cursor-pointer"
                    title="查看独立 K 线与行情深度"
                  >
                    👁️ K线
                  </button>

                  <button
                    @click="openEditModal(item)"
                    class="px-2 py-1 rounded bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-colors text-[11px] cursor-pointer"
                    title="编辑资产详情"
                  >
                    ✏️ 编辑
                  </button>

                  <button
                    @click="handleDeleteAsset(item)"
                    class="px-1.5 py-1 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-colors text-xs cursor-pointer"
                    title="删除资产"
                  >
                    🗑️
                  </button>
                </div>
              </td>
            </tr>

            <!-- 空状态 -->
            <tr v-if="sortedItems.length === 0">
              <td colspan="8" class="p-12 text-center space-y-3">
                <div class="text-3xl">💼</div>
                <div class="text-sm font-bold text-white">暂无匹配资产项目</div>
                <div class="text-xs text-zinc-400">
                  {{ assetStore.searchQuery ? '未找到符合条件的资产，可清空搜索词重试' : '点击下方按钮录入你的第一笔资产或负债' }}
                </div>
                <button
                  v-if="!assetStore.searchQuery"
                  @click="openCreateModal()"
                  class="px-4 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-white text-xs font-bold shadow-lg shadow-blue-500/20 cursor-pointer"
                >
                  ＋ 立即录入第一笔资产
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- 资产录入 / 编辑 Glassmorphic Modal -->
    <!-- ============================================================== -->
    <div
      v-if="showModal"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-lg bg-[#14151b] border border-white/[0.12] rounded-2xl shadow-2xl p-6 space-y-5">
        <!-- 弹窗头部 -->
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <h3 class="text-base font-bold text-white flex items-center space-x-2">
            <span>{{ modalMode === 'create' ? '➕' : '✏️' }}</span>
            <span>{{ modalMode === 'create' ? '录入新资产或负债' : '编辑资产信息' }}</span>
          </h3>
          <button @click="showModal = false" class="text-zinc-400 hover:text-white cursor-pointer text-sm">✕</button>
        </div>

        <!-- 类别选择卡片 -->
        <div>
          <label class="block text-xs text-zinc-400 mb-2 font-medium">选择资产所属大类</label>
          <div class="grid grid-cols-4 gap-2">
            <button
              v-for="(meta, catKey) in ASSET_CATEGORIES"
              :key="catKey"
              type="button"
              @click="formCategory = catKey"
              :class="
                formCategory === catKey
                  ? 'bg-blue-600/25 border-blue-500 text-white shadow-sm'
                  : 'bg-white/[0.02] border-white/[0.06] text-zinc-400 hover:bg-white/[0.05]'
              "
              class="p-2 rounded-xl border text-center transition-all cursor-pointer flex flex-col items-center justify-center space-y-1"
            >
              <span class="text-lg">{{ meta.icon }}</span>
              <span class="text-[11px] font-semibold">{{ meta.label.split('及')[0].split('与')[0] }}</span>
            </button>
          </div>
        </div>

        <!-- 表单输入区 -->
        <div class="space-y-3.5 text-xs">
          <!-- 资产名称 -->
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">
              资产名称 <span class="text-red-400">*</span>
            </label>
            <input
              v-model="formName"
              type="text"
              :placeholder="
                formCategory === 'EQUITY'
                  ? '如: 沪深300 ETF / 贵州茅台'
                  : formCategory === 'CASH'
                    ? '如: 招商银行活期存款 / 余额宝'
                    : formCategory === 'LIABILITY'
                      ? '如: 招商银行住房按揭贷款'
                      : '如: 某商品住宅房产 / 实物黄金金条'
              "
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>

          <!-- 标的代码 (仅在股票/ETF 或大宗时着重显示) -->
          <!-- 标的代码 / 智能反查 (支持股票/ETF/场外公募基金代码与名称) -->
          <div v-if="formCategory === 'EQUITY' || formCategory === 'COMMODITY' || formCategory === 'CRYPTO'" class="relative">
            <div class="flex items-center justify-between mb-1">
              <label class="text-zinc-400 font-medium">标的代码 / 拼音 / 名称智能反查 (Symbol)</label>
              <span class="text-[10px] text-blue-400 flex items-center space-x-1">
                <span v-if="isSearchingSymbol" class="animate-spin">🔄</span>
                <span>支持股票 / ETF / 场外公募基金</span>
              </span>
            </div>
            <div class="relative">
              <input
                :value="formSymbol"
                @input="handleSymbolInput"
                @blur="handleSymbolInputBlur"
                @focus="formSymbol && symbolSuggestions.length && (showSuggestions = true)"
                type="text"
                placeholder="输入代码、拼音或名称，如 510300、005827、茅台、易方达"
                class="w-full bg-black/50 border border-white/[0.1] focus:border-blue-500 rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none font-mono uppercase"
              />
              <span
                v-if="formSymbol"
                @click="formSymbol = ''; showSuggestions = false; activeSuggestionPrice = null; activeSuggestionName = null"
                class="absolute right-3 top-2.5 text-zinc-500 hover:text-white cursor-pointer"
              >
                ✕
              </span>
            </div>

            <!-- 智能联想下拉建议浮层 -->
            <div
              v-if="showSuggestions && symbolSuggestions.length > 0"
              class="absolute left-0 right-0 top-full mt-1.5 z-50 bg-[#161720] border border-white/[0.15] rounded-xl shadow-2xl max-h-56 overflow-y-auto divide-y divide-white/[0.05]"
            >
              <div
                v-for="sug in symbolSuggestions"
                :key="sug.symbol"
                @mousedown.prevent="selectSuggestion(sug)"
                class="p-2.5 hover:bg-blue-600/20 transition-colors cursor-pointer flex items-center justify-between group"
              >
                <div class="flex items-center space-x-2.5 min-w-0">
                  <span
                    class="px-1.5 py-0.5 rounded text-[10px] font-mono shrink-0"
                    :class="
                      sug.asset_type === 'ETF'
                        ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                        : sug.asset_type === 'FND'
                          ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30'
                          : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                    "
                  >
                    {{ sug.asset_type === 'FND' ? '公募基金' : sug.asset_type === 'ETF' ? '场内ETF' : 'A股' }}
                  </span>
                  <div class="flex flex-col min-w-0">
                    <span class="font-bold text-white text-xs truncate group-hover:text-blue-300">{{ sug.name }}</span>
                    <span class="text-[10px] font-mono text-zinc-400">{{ sug.symbol }}</span>
                  </div>
                </div>
                <div v-if="sug.latest_price !== null && sug.latest_price !== undefined" class="text-right font-mono shrink-0 ml-2">
                  <div class="text-xs font-bold text-white">¥{{ Number(sug.latest_price).toFixed(sug.latest_price > 10 ? 2 : 4) }}</div>
                  <div v-if="sug.pct_change !== null && sug.pct_change !== undefined" class="text-[10px]" :class="sug.pct_change >= 0 ? 'text-red-400' : 'text-emerald-400'">
                    {{ sug.pct_change >= 0 ? '+' : '' }}{{ Number(sug.pct_change).toFixed(2) }}%
                  </div>
                </div>
              </div>
            </div>

            <!-- 最新参考行情/净值一键填入条 -->
            <div
              v-if="activeSuggestionPrice !== null"
              class="mt-2 p-2 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-between text-[11px]"
            >
              <div class="flex items-center space-x-1.5 text-zinc-300">
                <span>⚡</span>
                <span>
                  {{ formSymbol.includes('.OF.FND') ? '公募最新参考净值:' : '最新实时现价:' }}
                  <b class="text-white font-mono font-bold">¥{{ Number(activeSuggestionPrice).toFixed(activeSuggestionPrice > 10 ? 2 : 4) }}</b>
                </span>
              </div>
              <button
                type="button"
                @click="applySuggestionPrice"
                class="px-2 py-0.5 rounded bg-blue-500/25 hover:bg-blue-500/40 text-blue-300 font-semibold cursor-pointer transition-colors text-[11px]"
              >
                一键填为买入成本
              </button>
            </div>
          </div>

          <!-- 数量与成本单价 (并排) -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-zinc-400 mb-1 font-medium">
                {{ formCategory === 'CASH' || formCategory === 'LIABILITY' ? '持有金额 / 负债本金' : '持有数量 / 份额' }}
                <span class="text-red-400">*</span>
              </label>
              <input
                v-model.number="formAmount"
                type="number"
                step="any"
                min="0"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 font-mono"
              />
            </div>

            <div>
              <label class="block text-zinc-400 mb-1 font-medium">买入成本均价 (单价)</label>
              <input
                v-model.number="formCostPrice"
                type="number"
                step="any"
                min="0"
                placeholder="现金/负债填 1"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 font-mono"
              />
            </div>
          </div>

          <!-- 计价币种与手动估值 -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-zinc-400 mb-1 font-medium">计价币种 (Currency)</label>
              <select
                v-model="formCurrency"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white focus:outline-none focus:border-blue-500/50 cursor-pointer font-mono"
              >
                <option v-for="c in SUPPORTED_CURRENCIES" :key="c.code" :value="c.code">
                  {{ c.label }}
                </option>
              </select>
            </div>

            <div v-if="!formSymbol">
              <label class="block text-zinc-400 mb-1 font-medium">手动评估单价</label>
              <input
                v-model.number="formManualPrice"
                type="number"
                step="any"
                min="0"
                placeholder="留空按成本单价"
                class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50 font-mono"
              />
            </div>
          </div>

          <!-- 外币折算汇率提示条 -->
          <div
            v-if="formCurrency !== 'CNY'"
            class="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-200 text-[11px] flex items-center justify-between"
          >
            <span class="flex items-center space-x-1">
              <span>💱</span>
              <span>
                实时外汇参考: 1 {{ formCurrency }} ≈ {{ (assetStore.overview?.fx_rates?.[formCurrency] || 7.20).toFixed(4) }} CNY
              </span>
            </span>
            <span class="text-[10px] text-amber-400 font-mono">资产总览将自动折合人民币核算</span>
          </div>

          <!-- 备注信息 -->
          <div>
            <label class="block text-zinc-400 mb-1 font-medium">备注说明</label>
            <input
              v-model="formNote"
              type="text"
              placeholder="如: 核心长线底仓、公积金组合贷、每年定投等"
              class="w-full bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500/50"
            />
          </div>

        </div>

        <!-- 预估价值反馈条 -->
        <div class="p-3 rounded-xl bg-black/40 border border-white/[0.08] flex items-center justify-between text-xs font-mono">
          <span class="text-zinc-400">总投入成本预估:</span>
          <span class="text-white font-bold">
            ¥{{ (Number(formAmount || 0) * Number(formCostPrice || 0)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
          </span>
        </div>

        <!-- 弹窗动作按钮 -->
        <div class="flex items-center justify-end space-x-2.5 pt-2 border-t border-white/[0.08]">
          <button
            type="button"
            @click="showModal = false"
            class="px-4 py-2 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs font-semibold cursor-pointer"
          >
            取消
          </button>
          <button
            type="button"
            @click="handleSubmitAsset"
            :disabled="isSubmitting"
            class="px-5 py-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 disabled:opacity-50 text-white font-bold text-xs shadow-lg shadow-blue-500/20 cursor-pointer"
          >
            {{ isSubmitting ? '保存中...' : modalMode === 'create' ? '立即录入' : '确认修改' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
