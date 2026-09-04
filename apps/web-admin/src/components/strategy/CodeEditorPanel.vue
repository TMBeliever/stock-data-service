<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { Codemirror } from 'vue-codemirror'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { useStrategyStore, STRATEGY_TEMPLATES } from '@/stores/strategy'

const strategyStore = useStrategyStore()

const extensions = [python(), oneDark]

const lineCount = computed(() => {
  return strategyStore.code.split('\n').length
})

const charCount = computed(() => {
  return strategyStore.code.length
})

function handleTemplateChange(e: Event) {
  const target = e.target as HTMLSelectElement
  if (target && target.value) {
    strategyStore.applyTemplate(target.value)
  }
}

function handleResetTemplate() {
  if (confirm('确定要重置为当前选中模板的初始代码吗？未保存的修改将被覆盖。')) {
    strategyStore.applyTemplate(strategyStore.selectedTemplate)
  }
}

function copyCode() {
  navigator.clipboard.writeText(strategyStore.code)
}

function handleKeyDown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault()
    strategyStore.runBacktest()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl">
    <!-- 1. 顶部操作栏 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex flex-wrap items-center justify-between gap-2">
      <!-- 左侧：文件名与模板选择器 -->
      <div class="flex items-center space-x-2.5">
        <div class="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/[0.08] text-xs font-mono text-zinc-300">
          <span class="text-amber-400">🐍</span>
          <span class="font-semibold text-white">custom_strategy.py</span>
        </div>

        <!-- 预设模板选择器 -->
        <div class="flex items-center space-x-1.5">
          <span class="text-[11px] text-zinc-400">预设模板:</span>
          <select
            :value="strategyStore.selectedTemplate"
            @change="handleTemplateChange"
            class="bg-black/50 border border-white/[0.1] rounded-lg px-2.5 py-1 text-xs text-zinc-200 hover:text-white focus:outline-none focus:border-amber-500/50 cursor-pointer"
          >
            <option v-for="(tpl, key) in STRATEGY_TEMPLATES" :key="key" :value="key">
              {{ tpl.name }}
            </option>
          </select>
        </div>
      </div>

      <!-- 右侧：重置、复制与运行回测按钮 -->
      <div class="flex items-center space-x-2">
        <button
          @click="handleResetTemplate"
          title="重置为模板初始代码"
          class="p-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-zinc-400 hover:text-white transition-all text-xs cursor-pointer"
        >
          🔄
        </button>

        <button
          @click="copyCode"
          title="复制当前源码"
          class="px-2.5 py-1 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] text-zinc-400 hover:text-white transition-all text-xs flex items-center space-x-1 cursor-pointer"
        >
          <span>📋</span>
          <span class="hidden sm:inline text-[11px]">复制</span>
        </button>

        <!-- 运行回测主按钮 -->
        <button
          @click="strategyStore.runBacktest()"
          :disabled="strategyStore.isBacktesting"
          class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-red-500 via-rose-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1.5 shadow-lg shadow-red-500/20 transition-all cursor-pointer group"
        >
          <span v-if="strategyStore.isBacktesting" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span v-else class="text-sm group-hover:scale-110 transition-transform">▶</span>
          <span>{{ strategyStore.isBacktesting ? '沙箱撮合中...' : '运行回测' }}</span>
          <span class="hidden md:inline text-[10px] opacity-70 font-mono bg-black/20 px-1 py-0.5 rounded">⌘↵</span>
        </button>
      </div>
    </div>

    <!-- 2. CodeMirror 编辑器主体 -->
    <div class="flex-1 relative overflow-hidden bg-[#0d0e11] font-mono text-[13px]">
      <Codemirror
        v-model="strategyStore.code"
        :extensions="extensions"
        :autofocus="true"
        :indent-with-tab="true"
        :tab-size="4"
        style="height: 100%; width: 100%;"
      />
    </div>

    <!-- 3. 底部状态栏 -->
    <div class="px-3 py-1.5 border-t border-white/[0.08] bg-white/[0.02] flex items-center justify-between text-[11px] text-zinc-400 font-mono">
      <div class="flex items-center space-x-3">
        <span class="flex items-center space-x-1 text-emerald-400">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
          <span>AST 安全沙箱防护开启</span>
        </span>
        <span>·</span>
        <span>Python 3.12</span>
      </div>

      <div class="flex items-center space-x-3 text-zinc-500">
        <span>{{ lineCount }} 行</span>
        <span>{{ charCount }} 字符</span>
        <span>UTF-8</span>
      </div>
    </div>
  </div>
</template>

<style>
/* 针对 CodeMirror 深度定制暗黑透明风格与行号居中对齐 */
.cm-editor {
  height: 100% !important;
  background-color: #0d0e11 !important;
}
.cm-scroller {
  font-family: 'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace !important;
  line-height: 1.6 !important;
}
.cm-gutters {
  background-color: #0d0e11 !important;
  border-right: 1px solid rgba(255, 255, 255, 0.06) !important;
  color: rgba(255, 255, 255, 0.25) !important;
}
</style>
