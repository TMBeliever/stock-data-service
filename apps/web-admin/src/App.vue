<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import TopCapsuleNav from '@/components/TopCapsuleNav.vue'
import CommandPalette from '@/components/CommandPalette.vue'
import AuthModal from '@/components/AuthModal.vue'
import GlobalFloatingAiAssistant from '@/components/GlobalFloatingAiAssistant.vue'
import { useAuthStore } from '@/stores/auth'
import { useAiStore } from '@/stores/ai'

import { useModalManagerStore } from '@/stores/modalManager'

const authStore = useAuthStore()
const aiStore = useAiStore()
const modalManager = useModalManagerStore()
const showPalette = ref(false)

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented) return

  // 0. ESC 键全局调度：若当前有打开的弹窗，优先依栈顶次序逐层关闭最新/最顶层弹窗
  if (e.key === 'Escape') {
    const handled = modalManager.handleEscKey()
    if (handled) {
      e.preventDefault()
      return
    }
  }

  // 1. ⌘+K 全局检索与命令面板
  if ((e.metaKey || e.ctrlKey) && (e.key?.toLowerCase() === 'k' || e.code === 'KeyK')) {
    e.preventDefault()
    showPalette.value = !showPalette.value
    return
  }

  // 2. ⌘+J 呼出/收起全站 AI 助手 (根组件兜底保证任何视口均能响应)
  if ((e.metaKey || e.ctrlKey) && (e.key?.toLowerCase() === 'j' || e.code === 'KeyJ')) {
    e.preventDefault()
    aiStore.toggleOpen()
    return
  }
}

function handleOpenPalette() {
  showPalette.value = true
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  window.addEventListener('open-command-palette', handleOpenPalette)
  authStore.initAuth()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
  window.removeEventListener('open-command-palette', handleOpenPalette)
})
</script>

<template>
  <div class="min-h-screen bg-[#0a0a0c] text-[#f4f4f6] relative selection:bg-red-500/30 selection:text-white">
    <!-- 1. Raycast 极客弥散微光背景与噪点质感 -->
    <div class="raycast-bg-container">
      <div class="raycast-glow-top"></div>
      <div class="raycast-glow-subtle"></div>
      <div class="raycast-noise-overlay"></div>
    </div>

    <!-- 2. 顶部悬浮磨砂玻璃胶囊导航栏 -->
    <TopCapsuleNav />

    <!-- 3. 主工作区视口 (工作台与组合持仓自适应超宽屏与优雅容器) -->
    <router-view v-slot="{ Component, route }">
      <main
        :class="route.path.startsWith('/strategy') || route.path.startsWith('/portfolio') ? 'max-w-[1780px] mx-auto px-4 pt-3 pb-6 relative z-10' : 'max-w-6xl mx-auto px-4 pt-4 pb-20 relative z-10'"
      >
        <transition name="fade" mode="out-in">
          <component :is="Component" :key="route.fullPath" />
        </transition>
      </main>
    </router-view>

    <!-- 4. 全局 Raycast 极客命令面板 (⌘+K) -->
    <CommandPalette :show="showPalette" @close="showPalette = false" />

    <!-- 5. 全局登录/注册身份认证模态窗 -->
    <AuthModal />

    <!-- 6. 全局悬浮可拖拽与缩放 AI 助手 (⌘+J) -->
    <GlobalFloatingAiAssistant />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease-out, transform 0.15s ease-out;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
