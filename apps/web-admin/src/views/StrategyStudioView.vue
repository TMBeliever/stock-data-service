<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import CodeEditorPanel from '@/components/strategy/CodeEditorPanel.vue'
import BacktestDashboard from '@/components/strategy/BacktestDashboard.vue'
import { useStrategyStore } from '@/stores/strategy'

const strategyStore = useStrategyStore()

// 回测抽屉展开状态 (默认收起，专注代码；运行回测或手动点击时滑出)
const isDrawerOpen = ref<boolean>(false)
const isDrawerMaximized = ref<boolean>(false)

// 打开抽屉
function openDrawer() {
  isDrawerOpen.value = true
}

// 收起抽屉
function closeDrawer() {
  isDrawerOpen.value = false
}

// 切换抽屉状态
function toggleDrawer() {
  isDrawerOpen.value = !isDrawerOpen.value
}

// 切换抽屉全屏最大化
function toggleMaximize() {
  isDrawerMaximized.value = !isDrawerMaximized.value
}

// 点击运行回测或按 ⌘+Enter 时：自动滑出抽屉并开始撮合运行
function handleOpenAndRun() {
  isDrawerOpen.value = true
  strategyStore.runBacktest()
}

// 全局快捷键监听 (Esc 快速收起抽屉)
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isDrawerOpen.value) {
    e.preventDefault()
    closeDrawer()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="h-[calc(100vh-7rem)] w-full min-h-0 overflow-hidden relative flex flex-col">
    <!-- 1. 主视觉：满血 100% 宽屏 Python 策略代码编辑器 (日常编码极致舒展) -->
    <div class="w-full h-full min-w-0">
      <CodeEditorPanel
        :is-drawer-open="isDrawerOpen"
        @toggle-drawer="toggleDrawer"
        @open-drawer-and-run="handleOpenAndRun"
      />
    </div>

    <!-- 2. 右侧边缘精致吸边条 (抽屉收起时常驻，带有能量微光，随时可一键唤出) -->
    <transition name="fade">
      <button
        v-if="!isDrawerOpen"
        @click="openDrawer"
        class="absolute right-0 top-1/2 -translate-y-1/2 z-30 group flex flex-col items-center justify-center py-4 px-1.5 rounded-l-2xl bg-[#181a24]/95 hover:bg-[#202230] border-l border-t border-b border-white/[0.12] hover:border-amber-500/50 shadow-2xl backdrop-blur-xl cursor-pointer transition-all duration-200"
        title="点击滑出量化回测分析看板 (快捷键: ⌘+Enter 自动运行并滑出)"
      >
        <span class="text-amber-400 text-sm group-hover:scale-110 transition-transform">⚡</span>
        <span class="text-[11px] font-semibold text-zinc-300 group-hover:text-amber-300 writing-vertical tracking-widest my-2 select-none">
          回测面板
        </span>
        <span
          v-if="strategyStore.isBacktesting"
          class="w-2 h-2 rounded-full bg-amber-400 animate-ping"
        ></span>
        <span
          v-else-if="strategyStore.backtestResult"
          class="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]"
        ></span>
      </button>
    </transition>

    <!-- 3. 背景轻柔遮罩 (点击左侧阴影区域可平滑收起抽屉) -->
    <transition name="fade">
      <div
        v-if="isDrawerOpen && !isDrawerMaximized"
        @click="closeDrawer"
        class="absolute inset-0 bg-black/40 backdrop-blur-[2px] z-40 transition-opacity"
      ></div>
    </transition>

    <!-- 4. 右向左平滑滑出抽屉 (Slide-over Drawer - 展开 90% 超大宽幅) -->
    <transition name="slide-left">
      <div
        v-if="isDrawerOpen"
        :class="isDrawerMaximized ? 'w-full' : 'w-full md:w-[92%] lg:w-[90%]'"
        class="absolute right-0 top-0 bottom-0 z-50 h-full rounded-l-2xl border-l border-y border-white/[0.14] bg-[#12141a]/98 backdrop-blur-2xl shadow-[-20px_0_60px_rgba(0,0,0,0.85)] flex flex-col overflow-hidden transition-[width] duration-200 select-none"
      >
        <BacktestDashboard
          mode="inline"
          height-class="h-full w-full"
          @close="closeDrawer"
          @toggle-maximize="toggleMaximize"
        />
      </div>
    </transition>
  </div>
</template>

<style scoped>
/* 竖排文字 */
.writing-vertical {
  writing-mode: vertical-rl;
  text-orientation: mixed;
}

/* 渐入渐出淡化 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 右向左平滑滑入滑出 */
.slide-left-enter-active,
.slide-left-leave-active {
  transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease;
}
.slide-left-enter-from,
.slide-left-leave-to {
  transform: translateX(100%);
  opacity: 0.8;
}
</style>
