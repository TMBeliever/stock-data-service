<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import UserMenu from '@/components/UserMenu.vue'

const router = useRouter()
const route = useRoute()

const emit = defineEmits<{
  (e: 'open-palette'): void
}>()

const serverStatus = ref('Quant Core v0.1.0')
</script>

<template>
  <header class="sticky top-0 z-40 w-full pt-3.5 pb-2.5 px-4 bg-[#0a0a0c]/40 backdrop-blur-xs">
    <div
      :class="route.path.startsWith('/strategy') ? 'max-w-[1780px]' : 'max-w-7xl'"
      class="mx-auto flex items-center justify-between h-14 px-4 rounded-2xl capsule-nav transition-all duration-300"
    >
      <!-- 左侧：品牌 Logo 与市场呼吸灯 -->
      <div class="flex items-center space-x-3 cursor-pointer" @click="router.push('/')">
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
            <span>系统运行正常</span>
          </div>
        </div>
      </div>

      <!-- 中间：核心页面路由导航胶囊 -->
      <nav class="flex items-center space-x-1 p-1 rounded-xl bg-white/[0.04] border border-white/[0.08]">
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
      </nav>

      <!-- 右侧：快捷键搜索、引擎徽标与用户系统菜单 -->
      <div class="flex items-center space-x-2.5">
        <!-- 引擎版本标签 -->
        <div class="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[11px]">
          <span class="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
          <span class="font-mono">{{ serverStatus }}</span>
        </div>

        <!-- ⌘+K 搜索按钮 -->
        <button
          @click="emit('open-palette')"
          class="flex items-center space-x-2 px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] hover:border-white/[0.18] transition-all text-xs text-zinc-300 cursor-pointer shadow-sm group"
        >
          <svg class="w-3.5 h-3.5 text-zinc-400 group-hover:text-white transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <span class="hidden md:inline text-zinc-400 group-hover:text-zinc-200">命令中心</span>
          <span class="kbd-badge">⌘K</span>
        </button>

        <!-- 用户登录/身份系统胶囊 -->
        <UserMenu />
      </div>
    </div>
  </header>
</template>
