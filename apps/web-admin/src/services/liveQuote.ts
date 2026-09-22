/**
 * 前端行情服务 (Market Quote Service)
 * 严格遵循系统架构规范：所有行情与净值数据统一走内部数据中台 (/stock/api/v1/snapshot/batch)
 * 严禁前端直连或反代任何外部三方行情源。
 */

export interface LiveQuoteItem {
  symbol: string
  ticker: string
  name: string
  price: number
  pre_close: number
  change: number
  pct_change: number
  is_fund: boolean
  source: string
  timestamp: number
}

// 内存短缓存 (TTL 3秒)，避免短时间内组件重复调用造成中台击穿
const quoteCache = new Map<string, { item: LiveQuoteItem; time: number }>()
const CACHE_TTL_MS = 3000

/**
 * 提取纯数字代码或标准化标识
 */
export function extractTicker(raw: string): string {
  const clean = raw.trim().toUpperCase()
  if (/^\d{6}$/.test(clean)) return clean
  const match = clean.match(/\b\d{6}\b/)
  if (match) return match[0]
  const p = clean.split('.')[0]
  if (/^\d{5,6}$/.test(p)) return p
  return clean
}

/**
 * 判断标的是否为公募开放式基金 (OF.FND 或常见开放式基金代码)
 */
export function isFundSymbol(symbol: string): boolean {
  const s = symbol.trim().toUpperCase()
  if (s.includes('.OF.FND') || s.includes('.FND') || s.startsWith('F_') || s.startsWith('FU_')) {
    return true
  }
  const ticker = extractTicker(s)
  if (/^\d{6}$/.test(ticker)) {
    if (
      ticker.startsWith('00') &&
      !ticker.startsWith('000') &&
      !ticker.startsWith('001') &&
      !ticker.startsWith('002') &&
      !ticker.startsWith('003')
    ) {
      return true
    }
    if (ticker.startsWith('01') || ticker.startsWith('02') || ticker.startsWith('11') || ticker.startsWith('21')) {
      return true
    }
  }
  return false
}

function roundNumber(num: number, digits = 2): number {
  const factor = Math.pow(10, digits)
  return Math.round(num * factor) / factor
}

/**
 * 批量获取标的行情快照 (统一经由内部数据中台 /stock/api/v1/snapshot/batch)
 */
export async function fetchBatchQuotes(symbols: string[]): Promise<Map<string, LiveQuoteItem>> {
  const result = new Map<string, LiveQuoteItem>()
  const cleanSymbols = Array.from(new Set(symbols.map((s) => s.trim()).filter(Boolean)))
  if (cleanSymbols.length === 0) return result

  const missingFromCache: string[] = []
  const now = Date.now()

  for (const s of cleanSymbols) {
    const cached = quoteCache.get(s)
    if (cached && now - cached.time < CACHE_TTL_MS) {
      result.set(s, cached.item)
    } else {
      missingFromCache.push(s)
    }
  }

  if (missingFromCache.length === 0) {
    return result
  }

  try {
    const resp = await fetch('/stock/api/v1/snapshot/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: missingFromCache }),
    })

    if (resp.ok) {
      const json = await resp.json()
      const items = json.data || []
      for (const it of items) {
        const p = Number(it.latest_price !== null && it.latest_price !== undefined ? it.latest_price : it.price || 0)
        const prev = Number(it.pre_close !== null && it.pre_close !== undefined ? it.pre_close : it.prev_close || p)
        const chg = it.change !== null && it.change !== undefined ? Number(it.change) : roundNumber(p - prev, 4)
        const pct = Number(it.pct_change !== null && it.pct_change !== undefined ? it.pct_change : it.change_percent || 0)
        const isFund = Boolean(it.symbol?.includes('.OF.FND') || it.symbol?.includes('.FND') || it.nav !== undefined && it.nav !== null)

        const snap: LiveQuoteItem = {
          symbol: it.symbol,
          ticker: it.ticker || extractTicker(it.symbol),
          name: it.name,
          price: p,
          pre_close: prev,
          change: chg,
          pct_change: pct,
          is_fund: isFund,
          source: 'stock-data',
          timestamp: it.timestamp || Date.now(),
        }

        if (it.symbol) {
          result.set(it.symbol, snap)
          quoteCache.set(it.symbol, { item: snap, time: now })
        }
        if (it.ticker) {
          result.set(it.ticker, snap)
          quoteCache.set(it.ticker, { item: snap, time: now })
        }
      }
    } else {
      console.warn(`[MarketQuote] 数据中台批量快照返回状态码: ${resp.status}`)
    }
  } catch (err) {
    console.error('[MarketQuote] 请求数据中台 /stock/api/v1/snapshot/batch 失败:', err)
  }

  return result
}

/**
 * 获取单个标的实时行情快照 (统一经由数据中台)
 */
export async function fetchLiveFundQuote(tickerOrSymbol: string): Promise<LiveQuoteItem | null> {
  const clean = tickerOrSymbol.trim()
  if (!clean) return null

  const cached = quoteCache.get(clean)
  if (cached && Date.now() - cached.time < CACHE_TTL_MS) {
    return cached.item
  }

  const map = await fetchBatchQuotes([clean])
  return map.get(clean) || map.get(extractTicker(clean)) || null
}
