<script setup lang="ts">
import { ref } from 'vue'
import AICopilotPanel from '@/components/strategy/AICopilotPanel.vue'
import CodeEditorPanel from '@/components/strategy/CodeEditorPanel.vue'
import BacktestDashboardPanel from '@/components/strategy/BacktestDashboardPanel.vue'

const showAiPanel = ref(true)
const showDashboard = ref(true)

function toggleAiPanel() {
  showAiPanel.value = !showAiPanel.value
}

function toggleDashboard() {
  showDashboard.value = !showDashboard.value
}
</script>

<template>
  <div class="h-[calc(100vh-6.5rem)] flex flex-col space-y-3 pb-2">
    <!-- 1. 工作台顶部状态与视图控制条 -->
    <div class="glass-panel px-4 py-2.5 flex items-center justify-between shrink-0">
      <div class="flex items-center space-x-3">
        <div class="w-7 h-7 rounded-xl bg-gradient-to-tr from-rose-500 to-amber-500 flex items-center justify-center text-sm shadow-md shadow-rose-500/20">
          ⚡
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <h1 class="text-sm font-bold text-white tracking-tight">量化策略投研工作台 (Quant Studio)</h1>
            <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-red-500/10 text-red-400 border border-red-500/20">
              PYTHON 3.12
            </span>
          </div>
          <p class="text-[11px] text-zinc-400 hidden sm:block">
            集成 AI 自然语言生成、受控 AST 沙箱安全编译、CodeMirror 编辑器与事件驱动毫秒级撮合回测
          </p>
        </div>
      </div>

      <!-- 视图展开/收起控制胶囊 -->
      <div class="flex items-center space-x-2 text-xs">
        <button
          @click="toggleAiPanel"
          :class="showAiPanel ? 'bg-amber-500/15 text-amber-300 border-amber-500/30' : 'bg-white/[0.04] text-zinc-400 border-white/[0.08]'"
          class="px-2.5 py-1 rounded-lg border text-xs flex items-center space-x-1 transition-all cursor-pointer"
        >
          <span>🤖</span>
          <span>{{ showAiPanel ? '收起 AI Copilot' : '展开 AI Copilot' }}</span>
        </button>

        <button
          @click="toggleDashboard"
          :class="showDashboard ? 'bg-red-500/15 text-red-300 border-red-500/30' : 'bg-white/[0.04] text-zinc-400 border-white/[0.08]'"
          class="px-2.5 py-1 rounded-lg border text-xs flex items-center space-x-1 transition-all cursor-pointer"
        >
          <span>📊</span>
          <span>{{ showDashboard ? '收起绩效看板' : '展开绩效看板' }}</span>
        </button>
      </div>
    </div>

    <!-- 2. 工作台多栏核心工作区 -->
    <div class="flex-1 flex gap-3 min-h-0 overflow-hidden">
      <!-- 左栏：AI Strategy Copilot -->
      <div
        v-show="showAiPanel"
        class="w-80 lg:w-96 shrink-0 h-full transition-all duration-300"
      >
        <AICopilotPanel />
      </div>

      <!-- 中间：代码编辑器 -->
      <div class="flex-1 min-w-[320px] h-full transition-all duration-300">
        <CodeEditorPanel />
      </div>

      <!-- 右栏：实时回测看板 -->
      <div
        v-show="showDashboard"
        class="w-96 lg:w-[480px] shrink-0 h-full transition-all duration-300"
      >
        <BacktestDashboardPanel />
      </div>
    </div>
  </div>
</template>
