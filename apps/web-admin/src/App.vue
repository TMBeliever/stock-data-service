<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import TopCapsuleNav from '@/components/TopCapsuleNav.vue'
import CommandPalette from '@/components/CommandPalette.vue'
import AuthModal from '@/components/AuthModal.vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const showPalette = ref(false)

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault()
    showPalette.value = !showPalette.value
  }
}

onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
  authStore.initAuth()
})

onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
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
    <TopCapsuleNav @open-palette="showPalette = true" />

    <!-- 3. 主工作区视口 (PC 宽屏高质感容器) -->
    <main class="max-w-6xl mx-auto px-4 pb-20 relative z-10">
      <router-view v-slot="{ Component, route }">
        <transition name="fade" mode="out-in">
          <component :is="Component" :key="route.fullPath" />
        </transition>
      </router-view>
    </main>

    <!-- 4. 全局 Raycast 极客命令面板 (⌘+K) -->
    <CommandPalette :show="showPalette" @close="showPalette = false" />

    <!-- 5. 全局登录/注册身份认证模态窗 -->
    <AuthModal />
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
