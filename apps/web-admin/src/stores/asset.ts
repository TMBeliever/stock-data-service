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

export interface AssetItem {
  id: string
  user_id: number
  category: AssetCategory
  name: string
  symbol: string | null
  amount: number
  cost_price: number
  manual_price: number | null
  current_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  currency: string
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
      const data: AssetOverview = await res.json()
      overview.value = data
      return data
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
      const created: AssetItem = await res.json()
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
  async function updateAsset(id: string, payload: UpdateAssetPayload): Promise<AssetItem | null> {
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
      const updated: AssetItem = await res.json()
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
  async function deleteAsset(id: string): Promise<boolean> {
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
