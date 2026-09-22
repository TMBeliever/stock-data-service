import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from './auth'

export type AssetCategory =
  | 'CASH'
  | 'EQUITY'
  | 'FIXED_INCOME'
  | 'COMMODITY'
  | 'CRYPTO'
  | 'REAL_ESTATE'
  | 'LIABILITY'

export interface CategoryMeta {
  key: AssetCategory
  label: string
  icon: string
  color: string
  badgeClass: string
  desc: string
  isLiability?: boolean
}

export const ASSET_CATEGORIES: Record<AssetCategory, CategoryMeta> = {
  CASH: {
    key: 'CASH',
    label: '现金及活期',
    icon: '💵',
    color: '#10b981',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
    desc: '活期存款、余额宝、美元现钞等高流动性资金',
  },
  EQUITY: {
    key: 'EQUITY',
    label: '股票及公募ETF',
    icon: '📈',
    color: '#3b82f6',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
    desc: 'A股、ETF、场外基金等权益类投资（自动拉取实时行情）',
  },
  FIXED_INCOME: {
    key: 'FIXED_INCOME',
    label: '银行固收与理财',
    icon: '🏦',
    color: '#8b5cf6',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
    desc: '大额存单、储蓄国债、稳健型银行理财产品',
  },
  COMMODITY: {
    key: 'COMMODITY',
    label: '黄金与大宗商品',
    icon: '🪙',
    color: '#f59e0b',
    badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
    desc: '实物黄金、黄金积存、有色大宗商品',
  },
  CRYPTO: {
    key: 'CRYPTO',
    label: '数字加密资产',
    icon: '⚡',
    color: '#06b6d4',
    badgeClass: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
    desc: '比特币、以太坊等数字资产',
  },
  REAL_ESTATE: {
    key: 'REAL_ESTATE',
    label: '房产与固定资产',
    icon: '🏠',
    color: '#6366f1',
    badgeClass: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25',
    desc: '商品住宅房产评估值、机动车等大宗实物资产',
  },
  LIABILITY: {
    key: 'LIABILITY',
    label: '借贷与家庭负债',
    icon: '💳',
    color: '#f43f5e',
    badgeClass: 'bg-rose-500/15 text-rose-400 border-rose-500/25',
    desc: '住房按揭贷款、汽车抵押贷款、消费信贷应偿本金',
    isLiability: true,
  },
}

export type DepositType = 'NONE' | 'DEMAND' | 'FIXED' | 'NOTICE' | 'LARGE_CD'

export type SettlementCycle = 'DAILY' | 'MONTHLY' | 'QUARTERLY' | 'ANNUAL' | 'MATURITY'

export const DEPOSIT_TYPES: Record<DepositType, { label: string; desc: string }> = {
  NONE: { label: '常规非存款', desc: '股票、房产、借贷等普通资产' },
  DEMAND: { label: '活期存款 / 零钱', desc: '活期储蓄、余额宝、现金管理随存随取' },
  FIXED: { label: '定期存款 / 封闭理财', desc: '整存整取定期、封闭期理财' },
  NOTICE: { label: '通知存款', desc: '一天/七天通知存款，支取需提前通知' },
  LARGE_CD: { label: '大额存单', desc: '银行专属大额存单，支持转让或定期付息' },
}

export const SETTLEMENT_CYCLES: Record<SettlementCycle, { label: string; desc: string }> = {
  MATURITY: { label: '到期一次还本付息', desc: '定期存款最常见模式，到期日统一结算本息' },
  DAILY: { label: '按日计息并结息', desc: '如余额宝、货币基金、日日宝每天结算' },
  MONTHLY: { label: '按月结息 / 月度返利', desc: '每月特定日期支付利息' },
  QUARTERLY: { label: '按季结息', desc: '银行标准活期通常每季度末20日结息' },
  ANNUAL: { label: '按年付息', desc: '多年期大额存单或国债每年付息一次' },
}

export interface AssetItem {
  id: number | string
  user_id: number
  category: AssetCategory
  name: string
  symbol: string | null
  amount: number
  cost_price: number
  manual_price: number | null
  current_price: number
  market_value: number
  cost_value?: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  currency: string
  fx_rate?: number
  market_val_raw?: number
  cost_val_raw?: number
  pnl_raw?: number
  deposit_type?: DepositType
  interest_rate?: number
  start_date?: string | null
  end_date?: string | null
  settlement_cycle?: SettlementCycle
  auto_rollover?: boolean
  accrued_interest?: number
  accrued_interest_cny?: number
  days_held?: number
  days_remaining?: number | null
  term_days?: number | null
  is_matured?: boolean
  note: string | null
  created_at: string
  updated_at: string
}

export interface CategorySummary {
  market_value: number
  cost: number
  pnl: number
  weight: number
  item_count: number
}

export interface AssetOverview {
  total_assets: number
  total_liabilities: number
  net_worth: number
  total_cost: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  category_breakdown: Record<AssetCategory, CategorySummary>
  currency: string
  base_currency?: string
  fx_rates?: Record<string, number>
  item_count: number
  items: AssetItem[]
}

export interface CreateAssetPayload {
  category: AssetCategory
  name: string
  symbol?: string | null
  amount: number
  cost_price: number
  manual_price?: number | null
  currency?: string
  note?: string | null
  deposit_type?: DepositType
  interest_rate?: number
  start_date?: string | null
  end_date?: string | null
  settlement_cycle?: SettlementCycle
  auto_rollover?: boolean
}

export interface UpdateAssetPayload {
  category?: AssetCategory
  name?: string
  symbol?: string | null
  amount?: number
  cost_price?: number
  manual_price?: number | null
  currency?: string
  note?: string | null
  deposit_type?: DepositType
  interest_rate?: number
  start_date?: string | null
  end_date?: string | null
  settlement_cycle?: SettlementCycle
  auto_rollover?: boolean
}

export const useAssetStore = defineStore('asset', () => {
  const authStore = useAuthStore()

  const overview = ref<AssetOverview | null>(null)
  const loading = ref(false)
  const refreshing = ref(false)
  const error = ref<string | null>(null)
  const activeCategoryFilter = ref<AssetCategory | 'ALL'>('ALL')
  const searchQuery = ref('')

  function getAuthHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (authStore.token) {
      headers['Authorization'] = `Bearer ${authStore.token}`
    }
    return headers
  }

  // 1. 获取全景资产总览 (含实时估值、净资产与细分)
  async function fetchOverview(silent = false) {
    if (!silent) loading.value = true
    else refreshing.value = true
    error.value = null

    try {
      const res = await fetch('/api/v1/asset/overview', {
        headers: getAuthHeaders(),
      })
      if (!res.ok) {
        throw new Error(`资产接口响应异常 (${res.status})`)
      }
      const raw = await res.json()
      const summary = raw.summary || {}
      const rawCategories = raw.categories || []

      // 将后端 categories 数组转换为以 AssetCategory 为键的字典对象
      const categoryBreakdown: Record<AssetCategory, CategorySummary> = {
        CASH: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        EQUITY: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        FIXED_INCOME: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        COMMODITY: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        CRYPTO: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        REAL_ESTATE: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
        LIABILITY: { market_value: 0, cost: 0, pnl: 0, weight: 0, item_count: 0 },
      }

      for (const cat of rawCategories) {
        const k = cat.category as AssetCategory
        if (categoryBreakdown[k]) {
          categoryBreakdown[k] = {
            market_value: cat.total_value || 0,
            cost: cat.total_cost || 0,
            pnl: cat.unrealized_pnl || 0,
            weight: (cat.percentage || 0) / 100,
            item_count: cat.count || 0,
          }
        }
      }

      const normalized: AssetOverview = {
        total_assets: summary.total_assets || 0,
        total_liabilities: summary.total_liabilities || 0,
        net_worth: summary.net_worth || 0,
        total_cost: summary.total_cost || 0,
        unrealized_pnl: summary.unrealized_pnl || 0,
        unrealized_pnl_pct: summary.return_pct ?? summary.unrealized_pnl_pct ?? 0,
        category_breakdown: categoryBreakdown,
        currency: 'CNY',
        base_currency: summary.base_currency || 'CNY',
        fx_rates: summary.fx_rates || {},
        item_count: summary.item_count || (raw.items ? raw.items.length : 0),
        items: raw.items || [],
      }


      overview.value = normalized
      return overview.value
    } catch (err: any) {
      console.error('[AssetStore] fetchOverview failed:', err)
      error.value = err.message || '获取资产概览失败'
      return null
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  // 2. 录入新资产
  async function createAsset(payload: CreateAssetPayload): Promise<AssetItem | null> {
    loading.value = true
    try {
      const res = await fetch('/api/v1/asset/items', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `录入资产失败 (${res.status})`)
      }
      const resData = await res.json().catch(() => ({}))
      const created: AssetItem = resData.data || resData
      await fetchOverview(true)
      return created
    } catch (err: any) {
      console.error('[AssetStore] createAsset failed:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  // 3. 更新资产项
  async function updateAsset(id: string | number, payload: UpdateAssetPayload): Promise<AssetItem | null> {
    loading.value = true
    try {
      const res = await fetch(`/api/v1/asset/items/${id}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `更新资产失败 (${res.status})`)
      }
      const resData = await res.json().catch(() => ({}))
      const updated: AssetItem = resData.data || resData
      await fetchOverview(true)
      return updated
    } catch (err: any) {
      console.error('[AssetStore] updateAsset failed:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  // 4. 删除资产项
  async function deleteAsset(id: string | number): Promise<boolean> {
    loading.value = true
    try {
      const res = await fetch(`/api/v1/asset/items/${id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })
      if (!res.ok) {
        throw new Error(`删除资产失败 (${res.status})`)
      }
      await fetchOverview(true)
      return true
    } catch (err: any) {
      console.error('[AssetStore] deleteAsset failed:', err)
      throw err
    } finally {
      loading.value = false
    }
  }


  // 计算属性
  const totalAssets = computed(() => overview.value?.total_assets || 0)
  const totalLiabilities = computed(() => overview.value?.total_liabilities || 0)
  const netWorth = computed(() => overview.value?.net_worth || 0)
  const totalCost = computed(() => overview.value?.total_cost || 0)
  const unrealizedPnl = computed(() => overview.value?.unrealized_pnl || 0)
  const unrealizedPnlPct = computed(() => overview.value?.unrealized_pnl_pct || 0)

  // 资产负债率
  const debtRatio = computed(() => {
    if (totalAssets.value <= 0) return 0
    return Math.min(100, (totalLiabilities.value / totalAssets.value) * 100)
  })

  // 过滤后的资产清单
  const filteredItems = computed(() => {
    const list = overview.value?.items || []
    return list.filter((item) => {
      // 类别筛选
      if (activeCategoryFilter.value !== 'ALL' && item.category !== activeCategoryFilter.value) {
        return false
      }
      // 关键字搜索
      if (searchQuery.value.trim()) {
        const q = searchQuery.value.trim().toLowerCase()
        const matchName = item.name.toLowerCase().includes(q)
        const matchSymbol = item.symbol?.toLowerCase().includes(q) || false
        const matchNote = item.note?.toLowerCase().includes(q) || false
        if (!matchName && !matchSymbol && !matchNote) return false
      }
      return true
    })
  })

  return {
    overview,
    loading,
    refreshing,
    error,
    activeCategoryFilter,
    searchQuery,
    totalAssets,
    totalLiabilities,
    netWorth,
    totalCost,
    unrealizedPnl,
    unrealizedPnlPct,
    debtRatio,
    filteredItems,
    fetchOverview,
    createAsset,
    updateAsset,
    deleteAsset,
  }
})
