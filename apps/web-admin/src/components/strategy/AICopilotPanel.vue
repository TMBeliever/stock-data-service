<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { marked } from 'marked'
import { useStrategyStore } from '@/stores/strategy'

const strategyStore = useStrategyStore()

const inputPrompt = ref('')
const chatContainer = ref<HTMLDivElement | null>(null)

// 常用量化灵感提示词
const quickPrompts = [
  { label: '📈 编写双均线策略', prompt: '请帮我写一个双均线趋势策略，参数为快线 5 日，慢线 20 日，金叉全仓 80% 买入，死叉全仓平仓。' },
  { label: '🛡️ 增加移动止损', prompt: '基于现有 BaseStrategy 规范，写一个带 5% 移动止损 (Trailing Stop) 的趋势跟踪策略。' },
  { label: '💰 红利低估定投', prompt: '请编写一个针对 510880 红利 ETF 的动态分位数估值定投策略，低估加倍买，高估分批止盈。' },
  { label: '🔍 诊断策略隐患', prompt: '请帮我诊断一下当前量化策略中是否存在未来函数、偷价漏洞、滑点未覆盖或数组越界问题。' },
]

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

watch(
  () => strategyStore.aiMessages[strategyStore.aiMessages.length - 1]?.content,
  () => {
    scrollToBottom()
  }
)

function handleSend() {
  const text = inputPrompt.value.trim()
  if (!text || strategyStore.isAiStreaming) return
  inputPrompt.value = ''
  strategyStore.sendAiMessage(text)
  scrollToBottom()
}

function handleQuickPrompt(promptText: string) {
  if (strategyStore.isAiStreaming) return
  strategyStore.sendAiMessage(promptText)
  scrollToBottom()
}

function copyCode(code: string) {
  navigator.clipboard.writeText(code)
}

function applyCode(code: string) {
  strategyStore.applyCodeToEditor(code)
}

// 格式化 markdown 内容
function renderMarkdown(content: string) {
  try {
    return marked.parse(content)
  } catch {
    return content
  }
}
</script>

<template>
  <div class="flex flex-col h-full bg-[#121316] border border-white/[0.06] rounded-2xl overflow-hidden shadow-xl">
    <!-- 1. 顶部状态与模型切换器 -->
    <div class="px-4 py-3 border-b border-white/[0.08] bg-white/[0.02] flex items-center justify-between">
      <div class="flex items-center space-x-2">
        <div class="w-6 h-6 rounded-lg bg-gradient-to-tr from-amber-500 to-orange-500 flex items-center justify-center text-xs text-white font-bold shadow-md shadow-orange-500/20">
          🤖
        </div>
        <div>
          <h2 class="text-xs font-bold text-white tracking-wide">AI 策略 Copilot</h2>
          <div class="flex items-center space-x-1.5 text-[10px] text-zinc-400">
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="strategyStore.isAiStreaming ? 'bg-amber-400 animate-ping' : 'bg-emerald-400'"
            ></span>
            <span>{{ strategyStore.isAiStreaming ? '思考生成中...' : '双模就绪' }}</span>
          </div>
        </div>
      </div>

      <!-- 模型下拉选择 -->
      <div class="flex items-center space-x-1.5 bg-black/40 p-1 rounded-xl border border-white/[0.08]">
        <button
          @click="strategyStore.aiModel = 'gemini-flash-lite-latest'"
          :class="strategyStore.aiModel === 'gemini-flash-lite-latest' ? 'bg-white/10 text-amber-300 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-2 py-0.5 rounded-lg text-[10px] transition-all flex items-center space-x-1 cursor-pointer"
        >
          <span>⚡</span>
          <span>Gemini</span>
        </button>
        <button
          @click="strategyStore.aiModel = 'claude'"
          :class="strategyStore.aiModel === 'claude' ? 'bg-white/10 text-purple-300 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-2 py-0.5 rounded-lg text-[10px] transition-all flex items-center space-x-1 cursor-pointer"
        >
          <span>🧠</span>
          <span>Claude 本机</span>
        </button>
      </div>
    </div>

    <!-- 2. 对话消息列表 -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
      <div
        v-for="msg in strategyStore.aiMessages"
        :key="msg.id"
        class="flex flex-col space-y-1.5"
      >
        <!-- 角色标签与时间 -->
        <div class="flex items-center space-x-1.5 text-[10px] text-zinc-500">
          <span>{{ msg.role === 'user' ? '👤 你的量化意图' : '🤖 QuantScope Copilot' }}</span>
          <span>·</span>
          <span>{{ new Date(msg.timestamp).toLocaleTimeString() }}</span>
        </div>

        <!-- 消息卡片 -->
        <div
          :class="msg.role === 'user'
            ? 'bg-red-500/10 border border-red-500/20 text-zinc-100 self-end rounded-2xl rounded-tr-sm max-w-[90%]'
            : 'bg-white/[0.03] border border-white/[0.06] text-zinc-300 self-start rounded-2xl rounded-tl-sm w-full'"
          class="p-3.5 leading-relaxed shadow-sm"
        >
          <!-- Markdown 渲染区 -->
          <div
            class="prose prose-invert prose-xs max-w-none break-words space-y-2"
            v-html="renderMarkdown(msg.content)"
          ></div>

          <!-- 若 AI 回复包含代码块，提供一键替换与复制按钮 -->
          <div
            v-if="msg.role === 'assistant' && strategyStore.extractPythonCode(msg.content)"
            class="mt-3 pt-2.5 border-t border-white/[0.08] flex items-center justify-between gap-2"
          >
            <div class="flex items-center space-x-1 text-[11px] text-amber-400 font-medium font-mono">
              <span>🐍</span>
              <span>已检测到完整 Python 策略</span>
            </div>
            <div class="flex items-center space-x-2">
              <button
                @click="copyCode(strategyStore.extractPythonCode(msg.content)!)"
                class="px-2 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-300 hover:text-white transition-all text-[10px] flex items-center space-x-1 cursor-pointer"
              >
                <span>📋</span>
                <span>复制代码</span>
              </button>
              <button
                @click="applyCode(strategyStore.extractPythonCode(msg.content)!)"
                class="px-2.5 py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-semibold transition-all text-[10px] flex items-center space-x-1 shadow-md shadow-red-500/20 cursor-pointer"
              >
                <span>⚡</span>
                <span>一键载入编辑器</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 灵感快捷提示词 -->
    <div class="px-3 py-2 border-t border-white/[0.06] bg-black/20">
      <div class="text-[10px] text-zinc-500 mb-1.5 flex items-center space-x-1">
        <span>💡</span>
        <span>快速提示词灵感：</span>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="(item, idx) in quickPrompts"
          :key="idx"
          @click="handleQuickPrompt(item.prompt)"
          :disabled="strategyStore.isAiStreaming"
          class="px-2 py-0.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] disabled:opacity-40 border border-white/[0.06] text-[10px] text-zinc-300 hover:text-white transition-all cursor-pointer truncate max-w-[160px]"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <!-- 4. 底部输入框与发送按钮 -->
    <div class="p-3 border-t border-white/[0.08] bg-white/[0.02]">
      <div class="relative">
        <textarea
          v-model="inputPrompt"
          @keydown.enter.prevent="handleSend"
          :placeholder="strategyStore.isAiStreaming ? 'AI 正在全力思考并流式输出中...' : '输入量化策略需求 (如: 编写红利低波定投，回踩 MA20 加仓)... 回车发送'"
          rows="3"
          :disabled="strategyStore.isAiStreaming"
          class="w-full resize-none bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/30 transition-all"
        ></textarea>
        <button
          @click="handleSend"
          :disabled="!inputPrompt.trim() || strategyStore.isAiStreaming"
          class="absolute right-2 bottom-3 px-3 py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-[11px] font-semibold flex items-center space-x-1 transition-all shadow-md shadow-red-500/20 cursor-pointer"
        >
          <span>{{ strategyStore.isAiStreaming ? '生成中' : '发送' }}</span>
          <span>➔</span>
        </button>
      </div>
      <div class="flex items-center justify-between text-[10px] text-zinc-500 mt-1 px-1">
        <span>按 Enter 发送</span>
        <span>由 {{ strategyStore.aiModel === 'claude' ? 'Claude 3.7 本机引擎' : 'Gemini 3.7 闪电引擎' }} 驱动</span>
      </div>
    </div>
  </div>
</template>
