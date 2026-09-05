<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMarketStore, type SymbolItem } from '@/stores/market'
import { useStrategyStore } from '@/stores/strategy'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const marketStore = useMarketStore()
const strategyStore = useStrategyStore()
const authStore = useAuthStore()

const inputRef = ref<HTMLInputElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const isOpen = ref(false)
const searchInput = ref('')
const activeCategory = ref<'all' | 'stk' | 'etf' | 'hk_us'>('all')
const selectedIndex = ref(0)
const addingSymbol = ref<string | null>(null)
const toastMsg = ref('')

// 常用推荐预设
const presetTabs = [
  { label: '全部', value: 'all' },
  { label: '🔥 热门白马', value: 'stk' },
  { label: '📈 宽基/ETF', value: 'etf' },
  { label: '🌐 港美核心', value: 'hk_us' },
]

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2500)
}

// 监听输入并防抖查询
let timer: any = null
watch(
  [searchInput, activeCategory],
  ([val, cat]) => {
    selectedIndex.value = 0
    clearTimeout(timer)
    timer = setTimeout(() => {
      marketStore.searchSymbols(val, cat)
    }, 150)
  },
  { immediate: true }
)

// 计算当前下拉展示的标的列表
const displayList = computed<SymbolItem[]>(() => {
  return marketStore.searchResults
})

function onFocus() {
  isOpen.value = true
  if (displayList.value.length === 0) {
    marketStore.searchSymbols(searchInput.value, activeCategory.value)
  }
}

function onClickOutside(e: MouseEvent) {
  if (containerRef.value && !containerRef.value.contains(e.target as Node)) {
    isOpen.value = false
    addingSymbol.value = null
  }
}

// 键盘导航
function onKeydown(e: KeyboardEvent) {
  if (!isOpen.value) {
    if (e.key === 'ArrowDown' || e.key === 'Enter') {
      isOpen.value = true
    }
    return
  }

  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (displayList.value.length > 0) {
      selectedIndex.value = (selectedIndex.value + 1) % displayList.value.length
    }
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (displayList.value.length > 0) {
      selectedIndex.value = (selectedIndex.value - 1 + displayList.value.length) % displayList.value.length
    }
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (displayList.value[selectedIndex.value]) {
      selectSymbol(displayList.value[selectedIndex.value])
    }
  } else if (e.key === 'Escape') {
    isOpen.value = false
    inputRef.value?.blur()
  }
}

// 全局 ⌘+K 聚焦搜索框
function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    inputRef.value?.focus()
    isOpen.value = true
  }
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
  window.removeEventListener('keydown', onGlobalKeydown)
})

// 选中标的跳转详情页
function selectSymbol(item: SymbolItem) {
  isOpen.value = false
  marketStore.addRecentSearch(item)
  router.push(`/symbol/${encodeURIComponent(item.symbol)}`)
}

// 快捷唤起悬浮回测工作舱
function runBacktestWith(item: SymbolItem, e: MouseEvent) {
  e.stopPropagation()
  isOpen.value = false
  strategyStore.openBacktestCockpit({
    symbol: item.symbol,
    mode: 'single',
    autoRun: true,
  })
  showToast(`⚡ 已唤起回测工作舱测试 ${item.name} (${item.symbol})`)
}

// 快捷加入指定组合
async function addWatchlist(item: SymbolItem, watchlistId: number, e: MouseEvent) {
  e.stopPropagation()
  const ok = await marketStore.addSymbolToWatchlist(watchlistId, item.symbol)
  if (ok) {
    showToast(`⭐ 已将 ${item.name} 加入自选组合！`)
    addingSymbol.value = null
  } else {
    showToast(`⚠️ 添加失败，请确保已登录`)
  }
}

function toggleAddDropdown(sym: string, e: MouseEvent) {
  e.stopPropagation()
  if (addingSymbol.value === sym) {
    addingSymbol.value = null
  } else {
    addingSymbol.value = sym
  }
}
</script>

<template>
  <div ref="containerRef" class="relative w-full max-w-md sm:max-w-lg">
    <!-- 1. 搜索框胶囊主输入体 -->
    <div
      class="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-black/40 hover:bg-black/60 border border-white/[0.12] focus-within:border-red-500/50 focus-within:ring-2 focus-within:ring-red-500/20 transition-all shadow-inner group"
    >
      <span class="text-zinc-400 group-focus-within:text-red-400 transition-colors text-xs">🔍</span>
      <input
        ref="inputRef"
        v-model="searchInput"
        type="text"
        placeholder="搜索股票代码 / 拼音 / 名称 (如 600519、GZMT、沪深300)..."
        @focus="onFocus"
        @keydown="onKeydown"
        class="w-full bg-transparent text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none font-sans"
      />

      <!-- 清空输入按钮 -->
      <button
        v-if="searchInput"
        @click="searchInput = ''; inputRef?.focus()"
        class="text-zinc-500 hover:text-zinc-300 text-xs px-1 cursor-pointer transition-colors"
      >
        ✕
      </button>

      <!-- 快捷键提示徽章 -->
      <div class="hidden md:flex items-center space-x-0.5 px-1.5 py-0.5 rounded bg-white/[0.06] border border-white/[0.08] text-[10px] text-zinc-400 font-mono shrink-0">
        <span>⌘</span>
        <span>K</span>
      </div>
    </div>

    <!-- 2. 下拉建议与即输即搜面板 -->
    <div
      v-if="isOpen"
      class="absolute left-0 right-0 top-full mt-2 z-50 bg-[#14151a]/95 backdrop-blur-xl border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden animate-fadeIn text-xs"
      style="max-height: 480px"
    >
      <!-- 分类过滤切换栏 -->
      <div class="flex items-center justify-between px-3 py-2 border-b border-white/[0.08] bg-white/[0.02]">
        <div class="flex items-center space-x-1">
          <button
            v-for="t in presetTabs"
            :key="t.value"
            @click="activeCategory = t.value as any"
            :class="activeCategory === t.value ? 'bg-white/10 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-2 py-0.8 rounded-lg text-[11px] transition-all cursor-pointer"
          >
            {{ t.label }}
          </button>
        </div>

        <span class="text-[10px] text-zinc-500 font-mono">
          {{ displayList.length }} 候选
        </span>
      </div>

      <!-- 最近搜索历史 (当输入框为空且有历史记录时) -->
      <div
        v-if="!searchInput && marketStore.recentSearches.length > 0"
        class="px-3 pt-2.5 pb-1 border-b border-white/[0.06]"
      >
        <div class="flex items-center justify-between text-[11px] text-zinc-400 mb-1.5">
          <span class="flex items-center space-x-1">
            <span>🕒</span>
            <span>最近搜索</span>
          </span>
          <button
            @click="marketStore.clearRecentSearches()"
            class="text-[10px] text-zinc-500 hover:text-zinc-300 cursor-pointer"
          >
            清空
          </button>
        </div>
        <div class="flex flex-wrap gap-1.5 pb-1">
          <button
            v-for="rec in marketStore.recentSearches"
            :key="rec.symbol"
            @click="selectSymbol(rec)"
            class="px-2 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-zinc-300 hover:text-white transition-all flex items-center space-x-1.5 cursor-pointer font-mono text-[11px]"
          >
            <span class="font-bold">{{ rec.name }}</span>
            <span class="text-zinc-500 text-[10px]">({{ rec.ticker }})</span>
            <span
              v-if="rec.pct_change !== undefined && rec.pct_change !== null"
              :class="rec.pct_change >= 0 ? 'text-red-400' : 'text-emerald-400'"
              class="text-[10px] font-bold"
            >
              {{ rec.pct_change >= 0 ? '+' : '' }}{{ rec.pct_change }}%
            </span>
          </button>
        </div>
      </div>

      <!-- 搜索结果列表区 -->
      <div class="overflow-y-auto max-h-80 divide-y divide-white/[0.04]">
        <!-- 加载中动画 -->
        <div v-if="marketStore.isSearching" class="p-6 flex items-center justify-center space-x-2 text-zinc-400">
          <div class="w-4 h-4 border-2 border-red-500/30 border-t-red-500 rounded-full animate-spin"></div>
          <span class="font-mono text-xs">正在实时检索全市场标的...</span>
        </div>

        <!-- 结果空状态 -->
        <div
          v-else-if="displayList.length === 0"
          class="p-8 text-center text-zinc-500 space-y-1"
        >
          <div class="text-xl">🔍</div>
          <div>未找到与 "<strong class="text-zinc-300">{{ searchInput }}</strong>" 匹配的标的</div>
          <div class="text-[11px] text-zinc-600">支持输入 6 位标准代码、中文全称或拼音首字母 (如 600519, 茅台, GZMT)</div>
        </div>

        <!-- 标的列表条目 -->
        <div
          v-for="(item, idx) in displayList"
          :key="item.symbol"
          @click="selectSymbol(item)"
          @mouseenter="selectedIndex = idx"
          :class="selectedIndex === idx ? 'bg-white/[0.06]' : 'hover:bg-white/[0.03]'"
          class="px-3.5 py-2.5 flex items-center justify-between cursor-pointer transition-colors relative group"
        >
          <!-- 左侧：标的名称与代码市场标签 -->
          <div class="flex items-center space-x-2.5 min-w-0">
            <div class="w-7 h-7 rounded-lg bg-black/40 border border-white/[0.08] flex items-center justify-center text-xs shrink-0 font-bold">
              <span v-if="item.asset_type === 'ETF'" class="text-blue-400">基</span>
              <span v-else-if="item.market === 'US'" class="text-amber-400">美</span>
              <span v-else-if="item.market === 'HK'" class="text-purple-400">港</span>
              <span v-else class="text-red-400">A</span>
            </div>

            <div class="min-w-0">
              <div class="flex items-center space-x-1.5">
                <span class="font-bold text-white text-xs truncate max-w-[130px] sm:max-w-[180px]">
                  {{ item.name }}
                </span>
                <span class="px-1.5 py-0.2 rounded text-[10px] font-mono font-bold bg-white/[0.06] text-zinc-300 border border-white/[0.08]">
                  {{ item.ticker }}
                </span>
                <span class="text-[10px] text-zinc-500 font-mono uppercase">
                  {{ item.market }}
                </span>
              </div>
              <div class="text-[10px] text-zinc-400 mt-0.5 flex items-center space-x-1.5">
                <span>{{ item.symbol }}</span>
                <span v-if="item.pe" class="text-zinc-500 font-mono">PE: {{ item.pe }}</span>
              </div>
            </div>
          </div>

          <!-- 右侧：现价、涨跌幅与快捷悬浮操作 -->
          <div class="flex items-center space-x-3 shrink-0">
            <!-- 现价与涨跌幅 -->
            <div class="text-right font-mono">
              <div class="font-bold text-white text-xs">
                ¥{{ item.latest_price !== undefined && item.latest_price !== null ? item.latest_price.toFixed(item.latest_price > 10 ? 2 : 3) : '--' }}
              </div>
              <div
                v-if="item.pct_change !== undefined && item.pct_change !== null"
                :class="item.pct_change >= 0 ? 'text-red-400' : 'text-emerald-400'"
                class="text-[11px] font-bold"
              >
                {{ item.pct_change >= 0 ? '+' : '' }}{{ item.pct_change.toFixed(2) }}%
              </div>
            </div>

            <!-- 快捷操作按钮组 (常驻或悬浮) -->
            <div class="flex items-center space-x-1" @click.stop>
              <!-- 快捷载入回测 -->
              <button
                @click="runBacktestWith(item, $event)"
                class="p-1.5 rounded-lg bg-white/[0.04] hover:bg-red-500/20 text-zinc-400 hover:text-red-300 border border-white/[0.06] transition-all cursor-pointer"
                title="以此标的载入策略工作台进行回测"
              >
                ⚡
              </button>

              <!-- 快捷加入自选组合 (相对定位下拉) -->
              <div class="relative">
                <button
                  @click="toggleAddDropdown(item.symbol, $event)"
                  class="p-1.5 rounded-lg bg-white/[0.04] hover:bg-blue-500/20 text-zinc-400 hover:text-blue-300 border border-white/[0.06] transition-all cursor-pointer"
                  title="加入我的自选组合"
                >
                  ⭐
                </button>

                <!-- 自选组合下拉选择面板 -->
                <div
                  v-if="addingSymbol === item.symbol"
                  class="absolute right-0 top-full mt-1.5 w-48 bg-[#181920] border border-white/[0.12] rounded-xl shadow-2xl p-2 z-50 text-left animate-fadeIn space-y-1"
                >
                  <div class="text-[10px] font-bold text-zinc-400 px-2 py-0.5 border-b border-white/[0.06]">
                    加入自选组合:
                  </div>
                  <div
                    v-if="strategyStore.userWatchlists.length === 0"
                    class="p-2 text-center text-[10px] text-zinc-500"
                  >
                    暂无自选组合
                  </div>
                  <div v-else class="max-h-40 overflow-y-auto space-y-0.5">
                    <button
                      v-for="wl in strategyStore.userWatchlists"
                      :key="wl.id"
                      @click="addWatchlist(item, wl.id, $event)"
                      class="w-full text-left px-2 py-1.5 rounded-lg text-xs hover:bg-blue-500/20 hover:text-blue-300 text-zinc-200 transition-colors flex items-center justify-between cursor-pointer"
                    >
                      <span class="truncate">{{ wl.name }}</span>
                      <span v-if="wl.symbols.includes(item.symbol)" class="text-blue-400 text-[10px]">已在</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部提示栏 -->
      <div class="px-3 py-1.5 bg-black/40 border-t border-white/[0.06] flex items-center justify-between text-[10px] text-zinc-500 font-mono">
        <div class="flex items-center space-x-2">
          <span>↑↓ 切换选择</span>
          <span>↵ 进入标的详情</span>
          <span>ESC 退出</span>
        </div>
        <span class="text-zinc-400">实时行情驱动</span>
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
