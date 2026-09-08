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

export interface MetricPercentileInfo {
  current: number
  percentile: number // 0.0 ~ 1.0
  min_max_ratio?: number
  min?: number
  max?: number
  median?: number
  p20?: number
  p50?: number
  p80?: number
  status?: string // 'extremely_undervalued' | 'undervalued' | 'fair' | 'overvalued' | 'extreme_bubble'
}

export interface EquityRiskPremiumInfo {
  earning_yield_pct: number
  benchmark_10y_bond_pct: number
  equity_risk_premium_pct: number
  status?: string
}

export interface PbRoeQualityInfo {
  implied_roe_pct: number
  pb_level: number
  is_asset_quality_safe: boolean
  status?: string
}

export interface ValuationLatest {
  pe_ttm?: MetricPercentileInfo | null
  pb?: MetricPercentileInfo | null
  ps?: MetricPercentileInfo | null
  dividend_yield_pct?: number | null
  equity_risk_premium?: EquityRiskPremiumInfo | null
  pb_roe_quality?: PbRoeQualityInfo | null
  market_cap_billion?: number | null
}

export interface ValuationHistoryItem {
  date: string
  close?: number
  pe?: number
  pe_pct?: number
  pe_p20?: number
  pe_p50?: number
  pe_p80?: number
  pb?: number
  pb_pct?: number
  pb_p20?: number
  pb_p50?: number
  pb_p80?: number
  dividend_yield?: number
  erp?: number
}

export interface ValuationAnalysisData {
  status: string
  symbol: string
  ticker: string
  asset_type?: string
  country?: string
  window: string
  sample_count: number
  latest: ValuationLatest
  history: ValuationHistoryItem[]
  from_cache?: boolean
  updated_at?: string
}

const RECENT_KEY = 'quantscope_recent_symbols'

// 常用标的中文名称预设字典（支持大盘宽基、行业ETF、核心权重）
const BUILTIN_SYMBOL_NAMES: Record<string, string> = {
  '510300': '沪深300 ETF',
  '510500': '中证500 ETF',
  '512100': '中证1000 ETF',
  '510050': '上证50 ETF',
  '159915': '创业板 ETF',
  '588000': '科创50 ETF',
  '515100': '景顺红利低波100ETF',
  '512880': '证券 ETF',
  '512690': '酒 ETF',
  '512010': '医药 ETF',
  '512480': '半导体 ETF',
  '515030': '新能源车 ETF',
  '513100': '纳斯达克100ETF',
  '159941': '纳指ETF广发',
  '159632': '纳指ETF',
  '159660': '纳斯达克指数ETF',
  '513300': '纳斯达克ETF',
  '600519': '贵州茅台',
  '000858': '五粮液',
  '300750': '宁德时代',
  '002594': '比亚迪',
  '601318': '中国平安',
  '000001': '平安银行',
  '000002': '万科A',
  '600036': '招商银行',
  '000510': '新金路',
  '601899': '紫金矿业',
  '600900': '长江电力',
  '601398': '工商银行',
  '601988': '中国银行',
}

export const useMarketStore = defineStore('market', () => {
  const authStore = useAuthStore()
  const strategyStore = useStrategyStore()

  // 状态
  const searchQuery = ref('')
  const searchResults = ref<SymbolItem[]>([])
  const isSearching = ref(false)

  // 历史搜索列表 (持久化到 localStorage)
  const recentSearches = ref<SymbolItem[]>(loadRecentSearches())

  // 全局标的中文名称映射缓存 (响应式)
  const symbolNameMap = ref<Record<string, string>>({ ...BUILTIN_SYMBOL_NAMES })
  const pendingSymbolFetches = new Set<string>()

  // 获取标的中文友好名称，无缝兼顾缓存、持仓、最近搜索与自动静默拉取
  function getSymbolName(symbol: string | undefined | null): string {
    if (!symbol) return '--'
    const cleanSym = symbol.trim()
    if (!cleanSym) return '--'

    const ticker = cleanSym.split('.')[0]

    // 1. 优先从当前全局响应式缓存中读取
    if (symbolNameMap.value[cleanSym]) return symbolNameMap.value[cleanSym]
    if (symbolNameMap.value[ticker]) return symbolNameMap.value[ticker]

    // 2. 检查 strategyStore 用户持仓中是否有该标的名称
    const holding = strategyStore.userHoldings.find(
      (h) => h.symbol === cleanSym || h.symbol.split('.')[0] === ticker
    )
    if (holding && holding.name) {
      symbolNameMap.value[cleanSym] = holding.name
      symbolNameMap.value[ticker] = holding.name
      return holding.name
    }

    // 3. 检查最近搜索列表中是否有该标的名称
    const recent = recentSearches.value.find(
      (s) => s.symbol === cleanSym || s.ticker === ticker
    )
    if (recent && recent.name) {
      symbolNameMap.value[cleanSym] = recent.name
      symbolNameMap.value[ticker] = recent.name
      return recent.name
    }

    // 4. 若为当前正在浏览的标的详情
    if (currentDetail.value && (currentDetail.value.symbol === cleanSym || currentDetail.value.ticker === ticker)) {
      if (currentDetail.value.name) {
        symbolNameMap.value[cleanSym] = currentDetail.value.name
        symbolNameMap.value[ticker] = currentDetail.value.name
        return currentDetail.value.name
      }
    }

    // 5. 若暂未缓存且非正在拉取，发起一次静默异步拉取补充缓存
    if (!pendingSymbolFetches.has(cleanSym)) {
      pendingSymbolFetches.add(cleanSym)
      fetchSymbolDetail(cleanSym).then((detail) => {
        if (detail && detail.name) {
          symbolNameMap.value[cleanSym] = detail.name
          symbolNameMap.value[ticker] = detail.name
        }
      }).catch(() => {
        // ignore background fetch failure
      })
    }

    // 优雅降级：返回 6 位代码
    return ticker
  }

  // 当前标的详情
  const currentSymbol = ref<string>('600519.SH.STK')
  const currentDetail = ref<SymbolItem | null>(null)
  const isDetailLoading = ref(false)

  // 当前标的 K 线
  const currentKline = ref<KlineItem[]>([])
  const isKlineLoading = ref(false)

  // 当前标的多维估值分析与历史通道
  const currentValuation = ref<ValuationAnalysisData | null>(null)
  const isValuationLoading = ref(false)

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

    // 缓存名称
    if (item.name) {
      symbolNameMap.value[item.symbol] = item.name
      if (item.ticker) symbolNameMap.value[item.ticker] = item.name
    }

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
        // 自动缓存搜索结果中的标的名称
        for (const item of searchResults.value) {
          if (item.name) {
            symbolNameMap.value[item.symbol] = item.name
            if (item.ticker) symbolNameMap.value[item.ticker] = item.name
          }
        }
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
          if (currentDetail.value.name) {
            symbolNameMap.value[currentDetail.value.symbol] = currentDetail.value.name
            if (currentDetail.value.ticker) symbolNameMap.value[currentDetail.value.ticker] = currentDetail.value.name
          }
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

  // 拉取标的多维全量估值分析 (PE/PB/分位数/ERP/PB-ROE)
  async function fetchSymbolValuation(symbol: string, window: string = '3y', forceRefresh: boolean = false): Promise<ValuationAnalysisData | null> {
    isValuationLoading.value = true
    try {
      const cleanSym = symbol.trim().toUpperCase()
      // 1. 优先调用量化服务端点
      let resp = await fetch(`/api/v1/market/symbols/${encodeURIComponent(cleanSym)}/valuation?window=${window}&force_refresh=${forceRefresh}`)
      if (!resp.ok) {
        // 2. 备选调用 stock-data 服务端点
        resp = await fetch(`/stock/api/v1/stock/valuation/analysis?symbol=${encodeURIComponent(cleanSym)}&window=${window}&force_refresh=${forceRefresh}`)
      }
      if (resp.ok) {
        const json = await resp.json()
        currentValuation.value = json
        return json
      }
    } catch (err) {
      console.error('[MarketStore] fetchSymbolValuation error:', err)
    } finally {
      isValuationLoading.value = false
    }
    return null
  }

  return {
    searchQuery,
    searchResults,
    isSearching,
    recentSearches,
    symbolNameMap,
    getSymbolName,
    currentSymbol,
    currentDetail,
    isDetailLoading,
    currentKline,
    isKlineLoading,
    currentValuation,
    isValuationLoading,
    searchSymbols,
    fetchSymbolDetail,
    fetchSymbolKline,
    fetchSymbolValuation,
    addRecentSearch,
    clearRecentSearches,
    addSymbolToWatchlist,
    removeSymbolFromWatchlist,
  }
})
