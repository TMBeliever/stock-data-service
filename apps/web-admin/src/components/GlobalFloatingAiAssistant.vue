<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { useAiStore } from '@/stores/ai'
import { useAuthStore } from '@/stores/auth'
import { useStrategyStore } from '@/stores/strategy'

const aiStore = useAiStore()
const authStore = useAuthStore()
const strategyStore = useStrategyStore()
const route = useRoute()

const chatContainer = ref<HTMLDivElement | null>(null)
const inputPrompt = ref('')
const showVipModal = ref(false)
const isActivatingVip = ref(false)
const toastMsg = ref('')

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2800)
}

// 自动滚到消息底部
function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

watch(
  () => aiStore.messages[aiStore.messages.length - 1]?.content,
  () => {
    scrollToBottom()
  }
)

// 监听路由变动：当打开窗口且切换页面时，平滑适配当前页面
const currentQuickPrompts = computed(() => {
  return aiStore.getQuickPromptsForRoute(route.path)
})

const isStrategyPage = computed(() => {
  return route.path.startsWith('/strategy')
})

function handleSend() {
  const text = inputPrompt.value.trim()
  if (!text || aiStore.isStreaming) return
  inputPrompt.value = ''
  aiStore.sendAiMessage(text, route.path)
  scrollToBottom()
}

function handleQuickPrompt(promptText: string) {
  if (aiStore.isStreaming) return
  aiStore.sendAiMessage(promptText, route.path)
  scrollToBottom()
}

function copyCode(code: string) {
  navigator.clipboard.writeText(code)
  showToast('📋 代码已复制到剪贴板')
}

function applyCodeToEditor(code: string) {
  strategyStore.applyCodeToEditor(code)
  showToast('⚡ 策略代码已一键载入工作台编辑器！')
}

function renderMarkdown(content: string) {
  try {
    return marked.parse(content)
  } catch {
    return content
  }
}

// 切换模型处理
function handleSelectModel(modelKey: 'gemini-flash-lite-latest' | 'claude') {
  if (modelKey === 'claude') {
    if (!authStore.isLoggedIn) {
      authStore.openLogin()
      return
    }
    if (!authStore.isVip) {
      showVipModal.value = true
      return
    }
  }
  aiStore.aiModel = modelKey
}

async function handleActivateVip() {
  isActivatingVip.value = true
  try {
    const ok = await authStore.grantVip(30)
    if (ok) {
      aiStore.aiModel = 'claude'
      showVipModal.value = false
      showToast('🎉 VIP 会员激活成功！已解锁 Claude 3.7 本机深度推理引擎！')
    } else {
      alert('激活失败，请检查网络后重试')
    }
  } finally {
    isActivatingVip.value = false
  }
}

// -------------------------------------------------------------
// 窗口拖拽 (Draggable) 逻辑
// -------------------------------------------------------------
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let initialPosX = 0
let initialPosY = 0

function onHeaderMouseDown(e: MouseEvent) {
  // 如果点击的是按钮，不触发拖拽
  const target = e.target as HTMLElement
  if (target.closest('button') || target.closest('select') || target.closest('input')) {
    return
  }
  if (aiStore.isMaximized) return

  isDragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  initialPosX = aiStore.position.x
  initialPosY = aiStore.position.y

  window.addEventListener('mousemove', onHeaderMouseMove)
  window.addEventListener('mouseup', onHeaderMouseUp)
}

function onHeaderMouseMove(e: MouseEvent) {
  if (!isDragging) return
  const deltaX = e.clientX - dragStartX
  const deltaY = e.clientY - dragStartY
  aiStore.updatePosition(initialPosX + deltaX, initialPosY + deltaY)
}

function onHeaderMouseUp() {
  isDragging = false
  window.removeEventListener('mousemove', onHeaderMouseMove)
  window.removeEventListener('mouseup', onHeaderMouseUp)
}

// -------------------------------------------------------------
// 窗口缩放 (Resizable) 逻辑
// -------------------------------------------------------------
let isResizing = false
let resizeStartX = 0
let resizeStartY = 0
let initialWidth = 0
let initialHeight = 0

function onResizeHandleMouseDown(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  if (aiStore.isMaximized) return

  isResizing = true
  resizeStartX = e.clientX
  resizeStartY = e.clientY
  initialWidth = aiStore.size.width
  initialHeight = aiStore.size.height

  window.addEventListener('mousemove', onResizeMouseMove)
  window.addEventListener('mouseup', onResizeMouseUp)
}

function onResizeMouseMove(e: MouseEvent) {
  if (!isResizing) return
  const deltaX = e.clientX - resizeStartX
  const deltaY = e.clientY - resizeStartY
  aiStore.updateSize(initialWidth + deltaX, initialHeight + deltaY)
}

function onResizeMouseUp() {
  isResizing = false
  window.removeEventListener('mousemove', onResizeMouseMove)
  window.removeEventListener('mouseup', onResizeMouseUp)
}

// 全局 ⌘+J 唤起快捷键
function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
    e.preventDefault()
    aiStore.toggleOpen()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div>
    <!-- 1. 收起状态：右下角悬浮胶囊召唤器 (Floating Trigger Bubble) -->
    <transition name="fade">
      <button
        v-if="!aiStore.isOpen"
        @click="aiStore.open()"
        class="fixed bottom-6 right-6 z-40 px-3.5 py-2.5 rounded-full bg-gradient-to-r from-amber-500/90 via-orange-500/90 to-rose-500/90 hover:from-amber-600 hover:to-rose-600 text-white font-bold text-xs shadow-2xl shadow-orange-500/30 flex items-center space-x-2 border border-white/20 backdrop-blur-md transition-all transform hover:scale-105 cursor-pointer group"
        title="唤醒全站 AI 智能助手 (⌘+J)"
      >
        <span class="text-sm">🤖</span>
        <span class="tracking-wide">Quant AI</span>
        <span
          class="w-2 h-2 rounded-full"
          :class="aiStore.isStreaming ? 'bg-amber-300 animate-ping' : 'bg-emerald-300 animate-pulse'"
        ></span>
        <span class="hidden group-hover:inline text-[10px] text-white/75 font-mono">⌘J</span>
      </button>
    </transition>

    <!-- 2. 展开状态：自由拖拽与鼠标缩放的毛玻璃独立悬浮窗 -->
    <div
      v-if="aiStore.isOpen"
      :style="{
        left: `${aiStore.position.x}px`,
        top: `${aiStore.position.y}px`,
        width: `${aiStore.size.width}px`,
        height: `${aiStore.size.height}px`,
      }"
      class="fixed z-50 bg-[#121316]/95 border border-white/[0.14] rounded-2xl shadow-2xl flex flex-col backdrop-blur-2xl overflow-hidden select-none"
    >
      <!-- 提示气泡 Toast -->
      <div
        v-if="toastMsg"
        class="absolute top-14 left-1/2 -translate-x-1/2 z-50 px-3.5 py-1.5 rounded-xl bg-emerald-500/90 text-white font-medium text-xs shadow-xl backdrop-blur-sm animate-bounce pointer-events-none"
      >
        {{ toastMsg }}
      </div>

      <!-- 2.1 顶部可拖拽标题栏 (Drag Handle Header) -->
      <div
        @mousedown="onHeaderMouseDown"
        @dblclick="aiStore.toggleMaximize()"
        class="px-3.5 py-2.5 border-b border-white/[0.08] bg-white/[0.02] flex items-center justify-between shrink-0 cursor-grab active:cursor-grabbing"
      >
        <!-- 左侧：图标与情境感知模式标签 -->
        <div class="flex items-center space-x-2">
          <div class="w-6 h-6 rounded-lg bg-gradient-to-tr from-amber-500 to-orange-500 flex items-center justify-center text-xs text-white shadow-md shadow-orange-500/20">
            🤖
          </div>
          <div>
            <div class="flex items-center space-x-1.5">
              <span class="text-xs font-bold text-white tracking-wide">QuantScope Copilot</span>
              <span
                :class="isStrategyPage ? 'bg-rose-500/15 text-rose-300 border-rose-500/25' : 'bg-blue-500/15 text-blue-300 border-blue-500/25'"
                class="px-1.5 py-0.2 rounded text-[9px] font-mono border"
              >
                {{ isStrategyPage ? '⚡ 策略量化' : '📊 市场宏观' }}
              </span>
            </div>
          </div>
        </div>

        <!-- 中部：双模型选择胶囊 -->
        <div class="flex items-center space-x-1 bg-black/40 p-0.5 rounded-xl border border-white/[0.08]">
          <button
            @click="handleSelectModel('gemini-flash-lite-latest')"
            :class="aiStore.aiModel === 'gemini-flash-lite-latest' ? 'bg-white/10 text-amber-300 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-1.5 py-0.5 rounded-lg text-[10px] transition-all flex items-center space-x-1 cursor-pointer"
          >
            <span>⚡</span>
            <span>Gemini</span>
          </button>
          <button
            @click="handleSelectModel('claude')"
            :class="aiStore.aiModel === 'claude' ? 'bg-white/10 text-purple-300 font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
            class="px-1.5 py-0.5 rounded-lg text-[10px] transition-all flex items-center space-x-1 cursor-pointer"
          >
            <span>🧠</span>
            <span>Claude</span>
            <span
              v-if="!authStore.isVip"
              class="px-1 py-0.1 rounded text-[8px] bg-gradient-to-r from-amber-500 to-orange-500 text-black font-extrabold"
            >
              VIP
            </span>
          </button>
        </div>

        <!-- 右侧：窗口控制胶囊按钮 -->
        <div class="flex items-center space-x-1 text-zinc-400">
          <button
            @click="aiStore.clearMessages()"
            title="清空会话历史"
            class="p-1 rounded-lg hover:bg-white/[0.08] hover:text-zinc-200 text-xs transition-colors cursor-pointer"
          >
            🧹
          </button>
          <button
            @click="aiStore.toggleMaximize()"
            :title="aiStore.isMaximized ? '还原窗口' : '最大化窗口'"
            class="p-1 rounded-lg hover:bg-white/[0.08] hover:text-zinc-200 text-xs transition-colors cursor-pointer"
          >
            {{ aiStore.isMaximized ? '❐' : '⛶' }}
          </button>
          <button
            @click="aiStore.close()"
            title="收起窗口至右下角 (⌘+J)"
            class="p-1 rounded-lg hover:bg-red-500/20 hover:text-red-300 text-xs transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>
      </div>

      <!-- 2.2 消息滚动区 (可自由选中文本) -->
      <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-3.5 text-xs select-text">
        <div
          v-for="msg in aiStore.messages"
          :key="msg.id"
          class="flex flex-col space-y-1.5"
        >
          <!-- 角色标签与时间 -->
          <div class="flex items-center space-x-1.5 text-[10px] text-zinc-500">
            <span>{{ msg.role === 'user' ? '👤 你的提问' : '🤖 Quant Copilot' }}</span>
            <span>·</span>
            <span>{{ new Date(msg.timestamp).toLocaleTimeString() }}</span>
          </div>

          <!-- 消息卡片 -->
          <div
            :class="msg.role === 'user'
              ? 'bg-red-500/10 border border-red-500/20 text-zinc-100 self-end rounded-2xl rounded-tr-sm max-w-[90%]'
              : 'bg-white/[0.03] border border-white/[0.06] text-zinc-300 self-start rounded-2xl rounded-tl-sm w-full'"
            class="p-3 leading-relaxed shadow-sm"
          >
            <!-- Markdown 内容 -->
            <div
              class="prose prose-invert prose-xs max-w-none break-words space-y-2 select-text"
              v-html="renderMarkdown(msg.content)"
            ></div>

            <!-- 若包含 Python 代码块，提供便捷操作条 -->
            <div
              v-if="msg.role === 'assistant' && aiStore.extractPythonCode(msg.content)"
              class="mt-3 pt-2.5 border-t border-white/[0.08] flex items-center justify-between gap-2"
            >
              <div class="flex items-center space-x-1 text-[11px] text-amber-400 font-mono">
                <span>🐍</span>
                <span>检测到 Python 策略</span>
              </div>
              <div class="flex items-center space-x-2">
                <button
                  @click="copyCode(aiStore.extractPythonCode(msg.content)!)"
                  class="px-2 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] text-zinc-300 hover:text-white transition-all text-[10px] flex items-center space-x-1 cursor-pointer"
                >
                  <span>📋</span>
                  <span>复制</span>
                </button>
                <button
                  v-if="isStrategyPage"
                  @click="applyCodeToEditor(aiStore.extractPythonCode(msg.content)!)"
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

      <!-- 2.3 动态情境快捷提示词 -->
      <div class="px-3 py-2 border-t border-white/[0.06] bg-black/20 shrink-0">
        <div class="text-[10px] text-zinc-500 mb-1 flex items-center justify-between">
          <span class="flex items-center space-x-1">
            <span>💡</span>
            <span>{{ isStrategyPage ? '工作台快捷策略灵感：' : '大盘宏观分析建议：' }}</span>
          </span>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="(item, idx) in currentQuickPrompts"
            :key="idx"
            @click="handleQuickPrompt(item.prompt)"
            :disabled="aiStore.isStreaming"
            class="px-2 py-0.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] disabled:opacity-40 border border-white/[0.06] text-[10px] text-zinc-300 hover:text-white transition-all cursor-pointer truncate max-w-[170px]"
          >
            {{ item.label }}
          </button>
        </div>
      </div>

      <!-- 2.4 底部输入区域 -->
      <div class="p-3 border-t border-white/[0.08] bg-white/[0.02] shrink-0">
        <div class="relative">
          <textarea
            v-model="inputPrompt"
            @keydown.enter.exact.prevent="handleSend"
            :placeholder="aiStore.isStreaming ? 'AI 正在深度思考中...' : (isStrategyPage ? '输入量化需求 (如: 双均线配合RSI过滤)... 回车发送' : '输入大盘研判意图 (如: 分析今日主力成交量)... 回车发送')"
            rows="2"
            :disabled="aiStore.isStreaming"
            class="w-full resize-none bg-black/50 border border-white/[0.1] rounded-xl px-3 py-2 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-amber-500/50 focus:ring-1 focus:ring-amber-500/30 transition-all select-text"
          ></textarea>
          <button
            @click="handleSend"
            :disabled="!inputPrompt.trim() || aiStore.isStreaming"
            class="absolute right-2 bottom-2.5 px-3 py-1 rounded-lg bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 disabled:opacity-40 text-white text-[11px] font-semibold flex items-center space-x-1 transition-all shadow-md shadow-red-500/20 cursor-pointer"
          >
            <span>{{ aiStore.isStreaming ? '生成中' : '发送' }}</span>
            <span>➔</span>
          </button>
        </div>
        <div class="flex items-center justify-between text-[10px] text-zinc-500 mt-1 px-1">
          <span>Enter 发送，Shift+Enter 换行 · 支持拖拽/边缘缩放</span>
          <span class="text-amber-400 font-mono">{{ aiStore.aiModel === 'claude' ? 'Claude 3.7' : 'Gemini 3.7' }}</span>
        </div>
      </div>

      <!-- 2.5 鼠标右下角自由缩放把手 (Resize Handle) -->
      <div
        v-if="!aiStore.isMaximized"
        @mousedown="onResizeHandleMouseDown"
        class="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize flex items-center justify-center opacity-40 hover:opacity-100 transition-opacity"
        title="按住鼠标拖拽拉伸窗口大小"
      >
        <svg class="w-2.5 h-2.5 text-zinc-400" viewBox="0 0 10 10" fill="currentColor">
          <circle cx="8" cy="8" r="1.2" />
          <circle cx="5" cy="8" r="1.2" />
          <circle cx="8" cy="5" r="1.2" />
        </svg>
      </div>
    </div>

    <!-- 3. VIP 会员专属权益激活弹窗 -->
    <div
      v-if="showVipModal"
      class="fixed inset-0 z-60 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-fadeIn"
    >
      <div class="w-full max-w-md bg-[#18191e] border border-amber-500/30 rounded-2xl shadow-2xl overflow-hidden p-6 space-y-4">
        <div class="flex items-center justify-between pb-3 border-b border-white/[0.08]">
          <div class="flex items-center space-x-2.5">
            <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-amber-500 to-orange-500 flex items-center justify-center text-lg shadow-lg shadow-orange-500/30">
              👑
            </div>
            <div>
              <h3 class="text-sm font-bold text-white">解锁 VIP 专属深度推理模型</h3>
              <p class="text-[11px] text-zinc-400">Claude 3.7 Sonnet 本机安全推理与无限投研特权</p>
            </div>
          </div>
          <button
            @click="showVipModal = false"
            class="text-zinc-400 hover:text-white transition-colors cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        <div class="space-y-2.5 text-xs text-zinc-300">
          <div class="p-3 rounded-xl bg-amber-500/5 border border-amber-500/15 flex items-start space-x-2.5">
            <span class="text-base">🧠</span>
            <div>
              <div class="font-bold text-amber-300">Claude 3.7 本机安全深度推理</div>
              <p class="text-[11px] text-zinc-400 mt-0.5">
                基于专用硬件直连，具备超强 AST 语法树解析与复杂多因子逻辑推演。
              </p>
            </div>
          </div>
          <div class="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06] flex items-start space-x-2.5">
            <span class="text-base">♾️</span>
            <div>
              <div class="font-bold text-white">无限制云端策略持久化与回测归档</div>
              <p class="text-[11px] text-zinc-400 mt-0.5">
                普通用户最多保存 10 套策略，VIP 用户享有无上限个人策略持久化与全量回测档案。
              </p>
            </div>
          </div>
        </div>

        <div class="pt-2 flex items-center justify-between gap-3">
          <button
            @click="showVipModal = false"
            class="w-1/3 py-2 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 text-xs transition-colors cursor-pointer"
          >
            稍后再说
          </button>
          <button
            @click="handleActivateVip"
            :disabled="isActivatingVip"
            class="w-2/3 py-2 rounded-xl bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500 hover:from-amber-600 hover:to-rose-600 disabled:opacity-50 text-white font-bold text-xs shadow-lg shadow-orange-500/25 transition-all cursor-pointer flex items-center justify-center space-x-1.5"
          >
            <span>⚡</span>
            <span>{{ isActivatingVip ? '正在激活...' : '立即开通 30 天 VIP 免费体验' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
