<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import UserMenu from '@/components/UserMenu.vue'
import GlobalSymbolSearchBar from '@/components/market/GlobalSymbolSearchBar.vue'
import WeixinAgentModal from '@/components/WeixinAgentModal.vue'
import { useStrategyStore } from '@/stores/strategy'

const router = useRouter()
const route = useRoute()
const strategyStore = useStrategyStore()
const showWeixinModal = ref(false)

function handleOpenWeixinModal() {
  showWeixinModal.value = true
}

onMounted(() => {
  window.addEventListener('open-weixin-modal', handleOpenWeixinModal)
})

onUnmounted(() => {
  window.removeEventListener('open-weixin-modal', handleOpenWeixinModal)
})
</script>

<template>
  <header class="sticky top-0 z-40 w-full pt-3.5 pb-2.5 px-4 bg-[#0a0a0c]/40 backdrop-blur-xs">
    <div
      :class="route.path.startsWith('/strategy') ? 'max-w-[1780px]' : 'max-w-7xl'"
      class="mx-auto flex items-center justify-between h-14 px-4 rounded-2xl capsule-nav transition-all duration-300 gap-4"
    >
      <!-- 1. 左侧：品牌 Logo 与行情指示 -->
      <div class="flex items-center space-x-3 cursor-pointer shrink-0" @click="router.push('/')">
        <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-[#ff5f3d] to-[#ff2d55] flex items-center justify-center shadow-lg shadow-red-500/20">
          <span class="text-white text-base font-bold">📈</span>
        </div>
        <div class="flex flex-col">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-semibold tracking-tight text-white">QuantScope</span>
            <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400 border border-red-500/20">PRO</span>
          </div>
          <div class="flex items-center space-x-1.5 text-[10px] text-zinc-400">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-glow"></span>
            <span>全市场行情直连</span>
          </div>
        </div>
      </div>

      <!-- 2. 核心页面路由导航胶囊 -->
      <nav class="hidden md:flex items-center space-x-1 p-1 rounded-xl bg-white/[0.04] border border-white/[0.08] shrink-0">
        <button
          @click="router.push('/')"
          :class="route.path === '/' ? 'bg-white/10 text-white font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>📊</span>
          <span>市场看板</span>
        </button>

        <button
          @click="router.push('/strategy')"
          :class="route.path.startsWith('/strategy') ? 'bg-gradient-to-r from-red-500/20 to-amber-500/20 text-white border border-red-500/30 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer group"
        >
          <span>⚡</span>
          <span>策略工作台</span>
          <span class="px-1 py-0.2 rounded text-[9px] bg-red-500/20 text-red-400 font-mono font-bold">AI+Py</span>
        </button>

        <button
          @click="router.push('/portfolio')"
          :class="route.path.startsWith('/portfolio') ? 'bg-gradient-to-r from-blue-500/20 to-emerald-500/20 text-white border border-blue-500/30 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>💼</span>
          <span>组合与持仓</span>
        </button>
      </nav>

      <!-- 3. 中间核心：全站全局标的即输即搜检索框 (仿同花顺/雪球) -->
      <div class="flex-1 max-w-lg mx-2">
        <GlobalSymbolSearchBar />
      </div>

      <!-- 4. 右侧：微信助理入口与用户系统菜单 -->
      <div class="flex items-center space-x-2.5 shrink-0">
        <button
          @click="showWeixinModal = true"
          class="hidden sm:flex items-center space-x-1.5 px-2.5 py-1.5 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/25 hover:border-emerald-500/40 text-emerald-400 hover:text-emerald-300 text-xs font-semibold transition-all cursor-pointer shadow-xs group"
          title="微信量化智能助理 (手机微信扫码直连)"
        >
          <span class="text-sm group-hover:scale-110 transition-transform">💬</span>
          <span>微信助理</span>
        </button>

        <UserMenu />
      </div>
    </div>

    <!-- 微信智能助理扫码与管理弹窗 -->
    <WeixinAgentModal v-model="showWeixinModal" />
  </header>
</template>
