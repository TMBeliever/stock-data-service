import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useStrategyStore, saveWatchlistsToStorage } from './strategy'

export interface SymbolItem {
  symbol: string
  ticker: string
  name: string
  market: string
  asset_type: string
  pinyin?: string
  category?: string
  tags?: string[]
  latest_price?: number | null
  change?: number | null
  pct_change?: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  pre_close?: number | null
  volume?: number | null
  amount?: number | null
  pe?: number | null
  pb?: number | null
  market_cap?: number | null
}

export interface KlineItem {
  timestamp: number
  date: string
  open: number
  close: number
  low: number
  high: number
  volume: number
  amount?: number | null
  ma5?: number | null
  ma10?: number | null
  ma20?: number | null
}

const RECENT_KEY = 'quantscope_recent_symbols'

export const useMarketStore = defineStore('market', () => {
  const authStore = useAuthStore()
  const strategyStore = useStrategyStore()

  // 状态
  const searchQuery = ref('')
  const searchResults = ref<SymbolItem[]>([])
  const isSearching = ref(false)

  // 历史搜索列表 (持久化到 localStorage)
  const recentSearches = ref<SymbolItem[]>(loadRecentSearches())

  // 当前标的详情
  const currentSymbol = ref<string>('600519.SH.STK')
  const currentDetail = ref<SymbolItem | null>(null)
  const isDetailLoading = ref(false)

  // 当前标的 K 线
  const currentKline = ref<KlineItem[]>([])
  const isKlineLoading = ref(false)

  function loadRecentSearches(): SymbolItem[] {
    try {
      const raw = localStorage.getItem(RECENT_KEY)
      if (raw) return JSON.parse(raw)
    } catch {
      // ignore
    }
    return [
      { symbol: '510300.SH.ETF', ticker: '510300', name: '沪深300 ETF', market: 'SH', asset_type: 'ETF', pct_change: 0.85, latest_price: 3.785 },
      { symbol: '600519.SH.STK', ticker: '600519', name: '贵州茅台', market: 'SH', asset_type: 'STK', pct_change: 2.40, latest_price: 1330.0 },
      { symbol: '300750.SZ.STK', ticker: '300750', name: '宁德时代', market: 'SZ', asset_type: 'STK', pct_change: -1.12, latest_price: 215.6 },
    ]
  }

  function addRecentSearch(item: SymbolItem) {
    // 移除已有的相同标的
    const filtered = recentSearches.value.filter((s) => s.symbol !== item.symbol)
    filtered.unshift({
      symbol: item.symbol,
      ticker: item.ticker,
      name: item.name,
      market: item.market,
      asset_type: item.asset_type,
      latest_price: item.latest_price,
      pct_change: item.pct_change,
    })
    recentSearches.value = filtered.slice(0, 8)
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(recentSearches.value))
    } catch {
      // ignore
    }
  }

  function clearRecentSearches() {
    recentSearches.value = []
    try {
      localStorage.removeItem(RECENT_KEY)
    } catch {
      // ignore
    }
  }

  // 标的搜索
  async function searchSymbols(keyword: string = '', category: string = 'all', limit: number = 15): Promise<SymbolItem[]> {
    isSearching.value = true
    try {
      const params = new URLSearchParams()
      if (keyword.trim()) params.append('q', keyword.trim())
      if (category && category !== 'all') params.append('category', category)
      params.append('limit', String(limit))

      const resp = await fetch(`/api/v1/market/symbols/search?${params.toString()}`)
      if (resp.ok) {
        const json = await resp.json()
        searchResults.value = json.data || []
        return searchResults.value
      }
    } catch (err) {
      console.error('[MarketStore] searchSymbols error:', err)
    } finally {
      isSearching.value = false
    }
    return []
  }

  // 拉取标的详情
  async function fetchSymbolDetail(symbol: string): Promise<SymbolItem | null> {
    isDetailLoading.value = true
    currentSymbol.value = symbol
    try {
      const resp = await fetch(`/api/v1/market/symbols/${encodeURIComponent(symbol)}/detail`)
      if (resp.ok) {
        const json = await resp.json()
        currentDetail.value = json.detail || null
        if (currentDetail.value) {
          addRecentSearch(currentDetail.value)
        }
        return currentDetail.value
      }
    } catch (err) {
      console.error('[MarketStore] fetchSymbolDetail error:', err)
    } finally {
      isDetailLoading.value = false
    }
    return null
  }

  // 拉取标的 K 线数据
  async function fetchSymbolKline(symbol: string, limit: number = 200, period: string = '1d', adjust: string = 'qfq'): Promise<KlineItem[]> {
    isKlineLoading.value = true
    try {
      const resp = await fetch(`/api/v1/market/symbols/${encodeURIComponent(symbol)}/kline?limit=${limit}&period=${period}&adjust=${adjust}`)
      if (resp.ok) {
        const json = await resp.json()
        currentKline.value = json.data || []
        return currentKline.value
      }
    } catch (err) {
      console.error('[MarketStore] fetchSymbolKline error:', err)
    } finally {
      isKlineLoading.value = false
    }
    return []
  }

  // 将标的追加至用户的指定自选组合 (支持本地即时更新 + 服务端持久化)
  async function addSymbolToWatchlist(watchlistId: number, symbol: string): Promise<boolean> {
    const sym = symbol.trim().toUpperCase()
    if (!sym) return false

    // 1. 本地立即更新 strategyStore 并保存缓存
    const idx = strategyStore.userWatchlists.findIndex((w) => w.id === watchlistId)
    if (idx !== -1) {
      const currentSyms = [...strategyStore.userWatchlists[idx].symbols]
      if (!currentSyms.includes(sym)) {
        currentSyms.push(sym)
        strategyStore.userWatchlists[idx] = {
          ...strategyStore.userWatchlists[idx],
          symbols: currentSyms,
          updated_at: new Date().toISOString(),
        }
        saveWatchlistsToStorage(strategyStore.userWatchlists)
      }
    }

    // 2. 若持有凭证且为服务端组合 (id > 0)，调用接口持久化
    if (authStore.token && watchlistId > 0) {
      try {
        const resp = await fetch(`/api/v1/user/watchlists/${watchlistId}/symbols`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${authStore.token}`,
          },
          body: JSON.stringify({ symbols: [sym] }),
        })
        if (resp.ok) {
          const updated = await resp.json()
          if (idx !== -1) {
            strategyStore.userWatchlists[idx] = updated
            saveWatchlistsToStorage(strategyStore.userWatchlists)
          }
        }
      } catch (err) {
        console.error('[MarketStore] addSymbolToWatchlist error:', err)
      }
    }
    return true
  }

  // 从指定自选组合中移除标的 (支持本地即时更新 + 服务端持久化)
  async function removeSymbolFromWatchlist(watchlistId: number, symbol: string): Promise<boolean> {
    const sym = symbol.trim().toUpperCase()
    // 1. 本地立即更新 strategyStore 并保存缓存
    const idx = strategyStore.userWatchlists.findIndex((w) => w.id === watchlistId)
    if (idx !== -1) {
      const currentSyms = strategyStore.userWatchlists[idx].symbols.filter((s) => s.toUpperCase() !== sym)
      strategyStore.userWatchlists[idx] = {
        ...strategyStore.userWatchlists[idx],
        symbols: currentSyms,
        updated_at: new Date().toISOString(),
      }
      saveWatchlistsToStorage(strategyStore.userWatchlists)
    }

    // 2. 若持有凭证且为服务端组合 (id > 0)，调用接口持久化
    if (authStore.token && watchlistId > 0) {
      try {
        const resp = await fetch(`/api/v1/user/watchlists/${watchlistId}/symbols/${encodeURIComponent(sym)}`, {
          method: 'DELETE',
          headers: {
            Authorization: `Bearer ${authStore.token}`,
          },
        })
        if (resp.ok) {
          const updated = await resp.json()
          if (idx !== -1) {
            strategyStore.userWatchlists[idx] = updated
            saveWatchlistsToStorage(strategyStore.userWatchlists)
          }
        }
      } catch (err) {
        console.error('[MarketStore] removeSymbolFromWatchlist error:', err)
      }
    }
    return true
  }

  return {
    searchQuery,
    searchResults,
    isSearching,
    recentSearches,
    currentSymbol,
    currentDetail,
    isDetailLoading,
    currentKline,
    isKlineLoading,
    searchSymbols,
    fetchSymbolDetail,
    fetchSymbolKline,
    addRecentSearch,
    clearRecentSearches,
    addSymbolToWatchlist,
    removeSymbolFromWatchlist,
  }
})
