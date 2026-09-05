<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

import { useAiStore } from '@/stores/ai'

const router = useRouter()
const authStore = useAuthStore()
const aiStore = useAiStore()
const showDropdown = ref(false)
const menuRef = ref<HTMLElement | null>(null)

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
}

function openCodexAssistant() {
  showDropdown.value = false
  aiStore.open()
}

function goToAgentSettings() {
  showDropdown.value = false
  router.push('/agent-settings')
}


function handleLogout() {
  showDropdown.value = false
  authStore.logout()
}

async function handleGrantVip() {
  await authStore.grantVip(30)
}

function handleClickOutside(e: MouseEvent) {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    showDropdown.value = false
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="relative" ref="menuRef">
    <!-- 1. 未登录状态：带有下拉菜单的访客胶囊 -->
    <div v-if="!authStore.isLoggedIn" class="flex items-center space-x-1.5">
      <button
        @click="authStore.openLogin()"
        class="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-gradient-to-r from-red-500/10 to-orange-500/10 hover:from-red-500/20 hover:to-orange-500/20 border border-red-500/20 hover:border-red-500/35 transition-all text-xs font-semibold text-white cursor-pointer shadow-sm shadow-red-500/5 group"
      >
        <svg class="w-3.5 h-3.5 text-red-400 group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        <span>登录 / 注册</span>
      </button>

      <button
        @click.stop="toggleDropdown"
        class="p-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] text-zinc-400 hover:text-white cursor-pointer"
        title="用户下拉菜单"
      >
        <svg
          :class="['w-3.5 h-3.5 transition-transform duration-200', showDropdown ? 'rotate-180 text-white' : '']"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <!-- 访客下拉面板 -->
      <transition name="dropdown-fade">
        <div
          v-if="showDropdown"
          class="absolute right-0 mt-10 w-64 rounded-2xl bg-[#141418] border border-white/[0.12] shadow-2xl p-3 z-50 overflow-hidden"
        >
          <div class="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] mb-2">
            <div class="flex items-center space-x-2.5">
              <div class="w-8 h-8 rounded-xl bg-zinc-700/60 border border-white/10 flex items-center justify-center text-xs font-bold text-zinc-300">
                👤
              </div>
              <div>
                <div class="text-xs font-bold text-white">访客用户 (Guest)</div>
                <div class="text-[10px] text-zinc-500 mt-0.5">登录后可同步策略与云端数据</div>
              </div>
            </div>
          </div>

          <div class="space-y-1 mb-2">
            <button
              @click="openCodexAssistant"
              class="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs text-zinc-200 hover:text-white hover:bg-white/[0.08] border border-white/[0.06] hover:border-purple-500/30 transition-all cursor-pointer group shadow-xs"
            >
              <div class="flex items-center space-x-2.5">
                <div class="w-6 h-6 rounded-lg bg-purple-500/20 text-purple-300 flex items-center justify-center text-xs group-hover:scale-110 transition-transform">
                  🖥️
                </div>
                <div class="text-left">
                  <div class="font-bold text-xs text-zinc-100 group-hover:text-purple-300 transition-colors">
                    Codex 智能工作台
                  </div>
                  <div class="text-[10px] text-zinc-400">
                    多项目工程 · 部署机联动
                  </div>
                </div>
              </div>
              <span class="text-zinc-500 group-hover:text-purple-300 transition-colors text-xs font-mono">➔</span>
            </button>

            <button
              @click="goToAgentSettings"
              class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-zinc-300 hover:text-white hover:bg-white/[0.08] border border-white/[0.06] hover:border-zinc-500/30 transition-all cursor-pointer group"
            >
              <div class="flex items-center space-x-2">
                <span>⚙️</span>
                <span>Agent 管理与 MCP 配置</span>
              </div>
              <span class="text-zinc-500 text-xs font-mono">➔</span>
            </button>
          </div>

          <button
            @click="showDropdown = false; authStore.openLogin()"
            class="w-full py-2 rounded-xl bg-gradient-to-r from-red-500/20 to-orange-500/20 border border-red-500/30 text-white font-medium text-xs hover:from-red-500/30 hover:to-orange-500/30 transition-colors cursor-pointer"
          >
            🔑 立即登录 / 注册
          </button>
        </div>
      </transition>
    </div>

    <!-- 2. 已登录状态：展示用户身份胶囊与下拉菜单 -->
    <div v-else>
      <button
        @click.stop="toggleDropdown"
        class="flex items-center space-x-2 px-2.5 py-1 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] hover:border-white/[0.18] transition-all text-xs text-white cursor-pointer group"
      >
        <!-- 头像小圆标 -->
        <div class="w-5 h-5 rounded-full bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-[10px] font-bold text-white uppercase shadow-sm">
          {{ authStore.username.charAt(0) }}
        </div>

        <!-- 用户名 -->
        <span class="font-medium text-xs max-w-[100px] truncate text-zinc-200 group-hover:text-white">
          {{ authStore.username }}
        </span>

        <!-- 身份状态徽章 -->
        <span
          v-if="authStore.isAdmin"
          class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-500/15 border border-purple-500/30 text-purple-300 font-mono"
        >
          超管
        </span>
        <span
          v-else-if="authStore.isVip"
          class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 border border-amber-500/30 text-amber-300 font-mono"
        >
          👑 VIP
        </span>
        <span
          v-else
          class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-500/15 border border-zinc-500/30 text-zinc-400 font-mono"
        >
          普通
        </span>

        <!-- 下拉小箭头 -->
        <svg
          :class="['w-3.5 h-3.5 text-zinc-400 transition-transform duration-200', showDropdown ? 'rotate-180 text-white' : '']"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <!-- 下拉弹出面板 -->
      <transition name="dropdown-fade">
        <div
          v-if="showDropdown"
          class="absolute right-0 mt-2 w-64 rounded-2xl bg-[#141418] border border-white/[0.12] shadow-2xl p-3 z-50 overflow-hidden"
        >
          <!-- 用户详情摘要卡片 -->
          <div class="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] mb-2">
            <div class="flex items-center space-x-2.5">
              <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-xs font-bold text-white uppercase shadow-md">
                {{ authStore.username.charAt(0) }}
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center space-x-1.5">
                  <span class="text-xs font-bold text-white truncate">{{ authStore.username }}</span>
                  <span v-if="authStore.isAdmin" class="text-[10px] text-purple-300 font-mono font-semibold">[ADMIN]</span>
                  <span v-else-if="authStore.isVip" class="text-[10px] text-amber-300 font-mono font-semibold">[VIP]</span>
                </div>
                <div class="text-[10px] text-zinc-500 truncate mt-0.5">
                  {{ authStore.user?.email || '未绑定邮箱' }}
                </div>
              </div>
            </div>

            <!-- VIP 状态条 -->
            <div class="mt-2.5 pt-2 border-t border-white/[0.06] flex items-center justify-between text-[10px]">
              <span class="text-zinc-400">会员状态:</span>
              <span v-if="authStore.isVip" class="text-amber-400 font-medium">
                👑 VIP 权益生效中
              </span>
              <span v-else class="text-zinc-500 font-medium">
                普通免费版
              </span>
            </div>
          </div>

          <!-- 核心功能导航：🖥️ Codex 智能工作台 + ⚙️ Agent 管理与 MCP 配置 -->
          <div class="space-y-1 mb-2">
            <button
              @click="openCodexAssistant"
              class="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs text-zinc-200 hover:text-white hover:bg-white/[0.08] border border-white/[0.06] hover:border-purple-500/30 transition-all cursor-pointer group shadow-xs"
            >
              <div class="flex items-center space-x-2.5">
                <div class="w-6 h-6 rounded-lg bg-purple-500/20 text-purple-300 flex items-center justify-center text-xs group-hover:scale-110 transition-transform">
                  🖥️
                </div>
                <div class="text-left">
                  <div class="font-bold text-xs text-zinc-100 group-hover:text-purple-300 transition-colors">
                    Codex 智能工作台
                  </div>
                  <div class="text-[10px] text-zinc-400">
                    多项目工程 · 部署机联动 · Canvas
                  </div>
                </div>
              </div>
              <span class="text-zinc-500 group-hover:text-purple-300 transition-colors text-xs font-mono">➔</span>
            </button>

            <button
              @click="goToAgentSettings"
              class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-zinc-300 hover:text-white hover:bg-white/[0.08] border border-white/[0.06] hover:border-zinc-500/30 transition-all cursor-pointer group"
            >
              <div class="flex items-center space-x-2">
                <span>⚙️</span>
                <span>Agent 管理与 MCP 配置</span>
              </div>
              <span class="text-zinc-500 text-xs font-mono">➔</span>
            </button>
          </div>

          <!-- 快速测试/赋权 VIP 按钮 -->
          <div class="space-y-1">
            <button
              v-if="!authStore.isVip || authStore.isAdmin"
              @click="handleGrantVip"
              :disabled="authStore.loading"
              class="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-amber-300 hover:text-amber-200 hover:bg-amber-500/10 border border-amber-500/20 transition-colors cursor-pointer"
            >
              <div class="flex items-center space-x-2">
                <span>⚡</span>
                <span>开通 / 续费 30 天 VIP</span>
              </div>
              <span class="text-[10px] text-amber-400/70">体验</span>
            </button>

            <!-- 退出登录 -->
            <button
              @click="handleLogout"
              class="w-full flex items-center space-x-2 px-3 py-2 rounded-xl text-xs text-zinc-400 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
            >
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
              <span>退出登录</span>
            </button>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.dropdown-fade-enter-active,
.dropdown-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.dropdown-fade-enter-from,
.dropdown-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
