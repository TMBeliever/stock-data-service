<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
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

const toolMetaMap: Record<string, { label: string; icon: string }> = {
  get_realtime_quote: { label: '实时行情快照 (最新价/盘口)', icon: '⚡' },
  get_stock_kline: { label: '高精度 K 线走势', icon: '📈' },
  get_stock_valuation: { label: '个股实时估值 (PE/PB/分位)', icon: '💎' },
  get_stock_financials: { label: '上市公司三大财报 (PIT)', icon: '📑' },
  get_stock_profile: { label: '公司画像与行业分类', icon: '🏢' },
  get_stock_shareholders: { label: '股东户数与筹码集中度', icon: '👥' },
  get_market_sectors: { label: '全市场行业/概念板块排名', icon: '📊' },
  get_dragon_tiger_list: { label: '每日交易所龙虎榜明细', icon: '🐉' },
  screen_stocks: { label: 'A股截面强势股选股器', icon: '🎯' },
  get_macro_treasury_yield: { label: '中美10年期国债收益率', icon: '🏛️' },
  get_system_storage_status: { label: '量化数据中台存储水位', icon: '💾' },
  validate_strategy_code: { label: 'Python 量化策略代码诊断', icon: '🔍' },
  run_backtest_fast: { label: '沙箱极速量化回测引擎', icon: '🚀' },
}

function getToolMeta(name: string) {
  return toolMetaMap[name] || { label: name, icon: '🔧' }
}

function formatToolArgs(args?: Record<string, any>) {
  if (!args || Object.keys(args).length === 0) return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
    .join(', ')
}

// 思考与工具推演折叠面板状态管理 (默认展开)
const trajectoryOpenMap = ref<Record<string, boolean>>({})

function isTrajectoryOpen(msgId: string): boolean {
  if (trajectoryOpenMap.value[msgId] === undefined) {
    return true // 默认展开，便于直观审计
  }
  return trajectoryOpenMap.value[msgId]
}

function toggleTrajectory(msgId: string) {
  trajectoryOpenMap.value[msgId] = !isTrajectoryOpen(msgId)
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
  // 如果点击的是按钮、输入框、下拉框，不触发拖拽
  const target = e.target as HTMLElement
  if (target.closest('button') || target.closest('select') || target.closest('input') || target.closest('textarea')) {
    return
  }

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
// 四个角手动拉伸缩放 (4-Corner Resizable) 逻辑
// -------------------------------------------------------------
let isCornerResizing = false
let activeCorner: 'nw' | 'ne' | 'sw' | 'se' | null = null
let resizeMouseStartX = 0
let resizeMouseStartY = 0
let resizeInitialX = 0
let resizeInitialY = 0
let resizeInitialW = 0
let resizeInitialH = 0

function onCornerMouseDown(corner: 'nw' | 'ne' | 'sw' | 'se', e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()

  isCornerResizing = true
  activeCorner = corner
  resizeMouseStartX = e.clientX
  resizeMouseStartY = e.clientY
  resizeInitialX = aiStore.position.x
  resizeInitialY = aiStore.position.y
  resizeInitialW = aiStore.size.width
  resizeInitialH = aiStore.size.height

  window.addEventListener('mousemove', onCornerMouseMove)
  window.addEventListener('mouseup', onCornerMouseUp)
}

function onCornerMouseMove(e: MouseEvent) {
  if (!isCornerResizing || !activeCorner) return
  const deltaX = e.clientX - resizeMouseStartX
  const deltaY = e.clientY - resizeMouseStartY

  const minW = 340
  const minH = 400

  let newX = resizeInitialX
  let newY = resizeInitialY
  let newW = resizeInitialW
  let newH = resizeInitialH

  if (activeCorner === 'se') {
    // 右下角 (SE): X, Y 保持不变，向右/下扩大
    newW = Math.max(minW, resizeInitialW + deltaX)
    newH = Math.max(minH, resizeInitialH + deltaY)
  } else if (activeCorner === 'sw') {
    // 左下角 (SW): Y 保持不变，向左修改 X 与 W，向下修改 H
    const tentativeW = resizeInitialW - deltaX
    if (tentativeW < minW) {
      newW = minW
      newX = resizeInitialX + (resizeInitialW - minW)
    } else {
      newW = tentativeW
      newX = resizeInitialX + deltaX
    }
    newH = Math.max(minH, resizeInitialH + deltaY)
  } else if (activeCorner === 'ne') {
    // 右上角 (NE): X 保持不变，向右修改 W，向上修改 Y 与 H
    newW = Math.max(minW, resizeInitialW + deltaX)
    const tentativeH = resizeInitialH - deltaY
    if (tentativeH < minH) {
      newH = minH
      newY = resizeInitialY + (resizeInitialH - minH)
    } else {
      newH = tentativeH
      newY = resizeInitialY + deltaY
    }
  } else if (activeCorner === 'nw') {
    // 左上角 (NW): 向左修改 X 与 W，向上修改 Y 与 H
    const tentativeW = resizeInitialW - deltaX
    if (tentativeW < minW) {
      newW = minW
      newX = resizeInitialX + (resizeInitialW - minW)
    } else {
      newW = tentativeW
      newX = resizeInitialX + deltaX
    }

    const tentativeH = resizeInitialH - deltaY
    if (tentativeH < minH) {
      newH = minH
      newY = resizeInitialY + (resizeInitialH - minH)
    } else {
      newH = tentativeH
      newY = resizeInitialY + deltaY
    }
  }

  aiStore.updateGeometry(newX, newY, newW, newH)
}

function onCornerMouseUp() {
  isCornerResizing = false
  activeCorner = null
  window.removeEventListener('mousemove', onCornerMouseMove)
  window.removeEventListener('mouseup', onCornerMouseUp)
}

// -------------------------------------------------------------
// 悬浮胶囊召唤器自由拖动 (Draggable Floating Trigger) 逻辑
// -------------------------------------------------------------
const { triggerPosition: triggerPos } = storeToRefs(aiStore)

let isDraggingTrigger = false
let triggerMouseStartX = 0
let triggerMouseStartY = 0
let triggerInitialX = 0
let triggerInitialY = 0
let hasTriggerMoved = false

function onTriggerMouseDown(e: MouseEvent) {
  if (e.button !== 0) return // 仅响应鼠标左键
  isDraggingTrigger = true
  hasTriggerMoved = false
  triggerMouseStartX = e.clientX
  triggerMouseStartY = e.clientY
  triggerInitialX = triggerPos.value?.x ?? 1150
  triggerInitialY = triggerPos.value?.y ?? 720

  window.addEventListener('mousemove', onTriggerMouseMove)
  window.addEventListener('mouseup', onTriggerMouseUp)
}

function onTriggerMouseMove(e: MouseEvent) {
  if (!isDraggingTrigger) return
  const deltaX = e.clientX - triggerMouseStartX
  const deltaY = e.clientY - triggerMouseStartY

  if (Math.hypot(deltaX, deltaY) > 3) {
    hasTriggerMoved = true
  }

  const maxX = Math.max(10, window.innerWidth - 200)
  const maxY = Math.max(10, window.innerHeight - 56)
  const newX = Math.min(Math.max(10, triggerInitialX + deltaX), maxX)
  const newY = Math.min(Math.max(10, triggerInitialY + deltaY), maxY)

  triggerPos.value = { x: newX, y: newY }
}

function onTriggerMouseUp(e: MouseEvent) {
  if (!isDraggingTrigger) return
  isDraggingTrigger = false
  window.removeEventListener('mousemove', onTriggerMouseMove)
  window.removeEventListener('mouseup', onTriggerMouseUp)

  // 若用户未进行明显拖拽，则触发点击唤醒助手（在悬浮球旁边展开）
  if (!hasTriggerMoved && triggerPos.value) {
    aiStore.open(triggerPos.value)
  }
}

function handleWindowResize() {
  if (typeof window === 'undefined') return
  if (!triggerPos.value) return
  const maxX = Math.max(10, window.innerWidth - 200)
  const maxY = Math.max(10, window.innerHeight - 56)
  if (triggerPos.value.x > maxX) triggerPos.value.x = maxX
  if (triggerPos.value.y > maxY) triggerPos.value.y = maxY
}

// 全局 ⌘+J 唤起快捷键
function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
    e.preventDefault()
    aiStore.toggleOpen(triggerPos.value)
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('resize', handleWindowResize)
  handleWindowResize()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('resize', handleWindowResize)
  window.removeEventListener('mousemove', onHeaderMouseMove)
  window.removeEventListener('mouseup', onHeaderMouseUp)
  window.removeEventListener('mousemove', onCornerMouseMove)
  window.removeEventListener('mouseup', onCornerMouseUp)
  window.removeEventListener('mousemove', onTriggerMouseMove)
  window.removeEventListener('mouseup', onTriggerMouseUp)
})
</script>

<template>
  <teleport to="body">
    <!-- 1. 收起状态：支持全屏自由拖拽的暗色毛玻璃悬浮胶囊 (Draggable Floating Capsule) -->
    <transition name="fade">
      <div
        v-if="!aiStore.isOpen"
        @mousedown="onTriggerMouseDown"
        :style="{
          position: 'fixed',
          left: `${triggerPos?.x ?? 1150}px`,
          top: `${triggerPos?.y ?? 720}px`,
          zIndex: 9999,
        }"
        class="group flex items-center space-x-2.5 pl-3 pr-3.5 py-2 rounded-full bg-[#13151b]/95 hover:bg-[#181a23] border border-white/[0.14] hover:border-amber-500/50 shadow-2xl shadow-black/80 hover:shadow-amber-500/20 backdrop-blur-2xl transition-shadow duration-200 cursor-grab active:cursor-grabbing select-none"
        title="按住鼠标左键可自由拖动位置，点击唤醒全站 AI 智能助手 (⌘+J)"
      >
        <!-- 左侧机器人状态微章 -->
        <div class="relative flex items-center justify-center w-7 h-7 rounded-xl bg-gradient-to-br from-amber-500/20 via-orange-500/15 to-transparent border border-amber-500/30 text-sm shadow-sm group-hover:border-amber-400/60 transition-colors pointer-events-none">
          <span>🤖</span>
          <!-- 呼吸状态灯 -->
          <span
            class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-[#13151b]"
            :class="aiStore.isStreaming ? 'bg-amber-400 animate-ping' : 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'"
          ></span>
        </div>

        <!-- 中部文字说明 -->
        <div class="flex flex-col text-left pointer-events-none">
          <div class="flex items-center space-x-1.5">
            <span class="text-xs font-semibold text-zinc-100 group-hover:text-amber-300 transition-colors tracking-wide">Quant Copilot</span>
          </div>
          <span class="text-[9px] text-zinc-400 font-mono flex items-center space-x-1">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block animate-pulse"></span>
            <span>{{ aiStore.isStreaming ? '正在深度推演...' : '全站投研助理' }}</span>
          </span>
        </div>

        <!-- 右侧快捷键 Badge -->
        <div class="ml-1 pl-2 border-l border-white/[0.1] flex items-center pointer-events-none">
          <kbd class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.12] text-zinc-300 font-mono shadow-inner group-hover:border-amber-500/40 group-hover:text-amber-300 transition-colors">⌘J</kbd>
        </div>
      </div>
    </transition>

    <!-- 2. 展开状态：自由拖拽与四角鼠标缩放的毛玻璃独立悬浮窗 (Fixed Floating Window) -->
    <div
      v-if="aiStore.isOpen"
      :style="{
        position: 'fixed',
        left: `${aiStore.position.x}px`,
        top: `${aiStore.position.y}px`,
        width: `${aiStore.size.width}px`,
        height: `${aiStore.size.height}px`,
        zIndex: 9999,
      }"
      class="bg-[#121316]/95 border border-white/[0.14] rounded-2xl shadow-2xl flex flex-col backdrop-blur-2xl select-none group"
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
        class="px-3.5 py-2.5 border-b border-white/[0.08] bg-white/[0.02] flex items-center justify-between shrink-0 cursor-grab active:cursor-grabbing rounded-t-2xl"
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

        <!-- 右侧：窗口控制胶囊按钮 (清空与收起，无需一键缩放) -->
        <div class="flex items-center space-x-1 text-zinc-400">
          <button
            @click="aiStore.clearMessages()"
            title="清空会话历史"
            class="p-1 rounded-lg hover:bg-white/[0.08] hover:text-zinc-200 text-xs transition-colors cursor-pointer"
          >
            🧹
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

          <!-- 当 AI 刚响应、内容尚未吐出且没有步骤时：展示小巧精致的呼吸思考胶囊 -->
          <div
            v-if="msg.role === 'assistant' && (!msg.content || !msg.content.trim()) && (!msg.steps || msg.steps.length === 0)"
            class="inline-flex items-center space-x-2 px-3 py-1.5 rounded-2xl rounded-tl-sm bg-[#161720]/90 border border-amber-500/20 text-amber-200/90 shadow-sm backdrop-blur-md self-start text-[11px]"
          >
            <!-- 迷你呼吸指示灯 -->
            <div class="relative flex items-center justify-center w-2.5 h-2.5 shrink-0">
              <span class="absolute inline-flex w-full h-full rounded-full bg-amber-400 opacity-75 animate-ping"></span>
              <span class="relative inline-flex w-1.5 h-1.5 rounded-full bg-amber-400"></span>
            </div>
            <span class="font-medium tracking-wide">AI 正在深度思考与推演</span>
            <!-- 动效微跳三连点 -->
            <span class="inline-flex items-center space-x-0.5 text-amber-400">
              <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 0ms"></span>
              <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 150ms"></span>
              <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 300ms"></span>
            </span>
          </div>

          <!-- 正常消息卡片 (包含用户提问与助手多步推演/正文) -->
          <div
            v-else
            :class="msg.role === 'user'
              ? 'bg-red-500/10 border border-red-500/20 text-zinc-100 self-end rounded-2xl rounded-tr-sm max-w-[90%]'
              : 'bg-white/[0.03] border border-white/[0.06] text-zinc-300 self-start rounded-2xl rounded-tl-sm w-full'"
            class="p-3 leading-relaxed shadow-sm space-y-2.5"
          >
            <!-- 助手端：思考与工具链多步推演轨迹面板 (Agent Thought & Tool Trajectory Accordion) -->
            <div
              v-if="msg.role === 'assistant' && ((msg.steps && msg.steps.length > 0) || (msg.toolCalls && msg.toolCalls.length > 0))"
              class="rounded-xl border border-white/[0.08] bg-black/40 overflow-hidden text-xs transition-all shadow-inner"
            >
              <!-- 折叠标题栏 -->
              <div
                @click="toggleTrajectory(msg.id)"
                class="px-2.5 py-1.5 bg-white/[0.02] hover:bg-white/[0.04] flex items-center justify-between cursor-pointer select-none transition-colors border-b border-white/[0.04]"
              >
                <div class="flex items-center space-x-1.5 text-[11px]">
                  <span class="text-xs">🧠</span>
                  <span class="font-medium text-zinc-300">
                    {{ aiStore.isStreaming && msg.id === aiStore.messages[aiStore.messages.length - 1]?.id ? '智能体正在推演中...' : `推演思考与工具链 (${msg.steps?.length || msg.toolCalls?.length || 0} 步)` }}
                  </span>
                </div>
                <div class="flex items-center space-x-2 text-[10px] text-zinc-400">
                  <span
                    v-if="aiStore.isStreaming && msg.id === aiStore.messages[aiStore.messages.length - 1]?.id"
                    class="flex items-center space-x-1 text-amber-300 font-mono"
                  >
                    <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span>
                    <span>思考与调用中</span>
                  </span>
                  <span class="text-[10px] transition-transform duration-200 text-zinc-500" :class="isTrajectoryOpen(msg.id) ? 'rotate-180' : ''">
                    ▼
                  </span>
                </div>
              </div>

              <!-- 展开的每一步推演流水线 -->
              <div v-show="isTrajectoryOpen(msg.id)" class="p-2.5 space-y-2.5 font-mono">
                <!-- A. 标准按步骤渲染 (优先) -->
                <template v-if="msg.steps && msg.steps.length > 0">
                  <div
                    v-for="st in msg.steps"
                    :key="st.step"
                    class="relative pl-3.5 border-l-2 space-y-1.5"
                    :class="st.status === 'running' ? 'border-amber-400/80 animate-pulse' : 'border-emerald-500/40'"
                  >
                    <!-- 步骤左侧指示灯 -->
                    <div
                      class="absolute -left-[5px] top-0.5 w-2 h-2 rounded-full ring-2 ring-[#121316]"
                      :class="st.status === 'running' ? 'bg-amber-400 animate-ping' : 'bg-emerald-400'"
                    ></div>

                    <!-- 步骤序号与状态 -->
                    <div class="flex items-center justify-between text-[10.5px]">
                      <span class="font-semibold text-zinc-200 flex items-center space-x-1">
                        <span>📍 第 {{ st.step }} 步</span>
                      </span>
                      <span
                        class="text-[9px] px-1.5 py-0.2 rounded"
                        :class="st.status === 'running' ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/15 text-emerald-300'"
                      >
                        {{ st.status === 'running' ? '思考与调用中...' : '✓ 步骤完成' }}
                      </span>
                    </div>

                    <!-- 思考内容 (Thought) -->
                    <div v-if="st.thought" class="p-1.5 rounded-md bg-white/[0.02] border border-white/[0.04] text-[10.5px] text-zinc-300 flex items-start space-x-1.5 leading-snug">
                      <span class="text-[11px] shrink-0 mt-0.5">💭</span>
                      <div class="flex-1 min-w-0">
                        <span class="text-zinc-400 text-[9.5px] block font-medium mb-0.5">AI 思考意图：</span>
                        <span class="text-amber-200/90">{{ st.thought }}</span>
                      </div>
                    </div>

                    <!-- 本步骤调用的工具列表 (Tool Calls) -->
                    <div v-if="st.toolCalls && st.toolCalls.length > 0" class="space-y-1 pt-0.5">
                      <div
                        v-for="tool in st.toolCalls"
                        :key="tool.id"
                        class="rounded-md border bg-black/40 text-[10px] overflow-hidden transition-all"
                        :class="tool.status === 'calling' ? 'border-amber-500/40 text-amber-300' : 'border-emerald-500/25 text-emerald-300'"
                      >
                        <details class="group/tcall">
                          <summary class="px-2 py-1 flex items-center justify-between cursor-pointer select-none hover:bg-white/[0.02]">
                            <div class="flex items-center space-x-1.5 truncate">
                              <span class="text-xs">{{ getToolMeta(tool.name).icon }}</span>
                              <span class="font-medium text-zinc-200">{{ getToolMeta(tool.name).label }}</span>
                              <span v-if="formatToolArgs(tool.arguments)" class="text-[9px] text-zinc-400 truncate max-w-[130px]">
                                ({{ formatToolArgs(tool.arguments) }})
                              </span>
                            </div>
                            <div class="flex items-center space-x-1 shrink-0 ml-1">
                              <span
                                class="text-[8.5px] px-1 py-0.2 rounded"
                                :class="tool.status === 'calling' ? 'bg-amber-500/20 text-amber-300 animate-pulse' : 'bg-emerald-500/20 text-emerald-300'"
                              >
                                {{ tool.status === 'calling' ? '执行中...' : '✓ 真实数据' }}
                              </span>
                              <span v-if="tool.outputPreview" class="text-[8px] text-zinc-500 group-open/tcall:rotate-180 transition-transform">▼</span>
                            </div>
                          </summary>
                          <div v-if="tool.outputPreview" class="p-2 border-t border-white/[0.06] bg-black/80 text-[9.5px] text-zinc-400 font-mono overflow-x-auto max-h-32">
                            <pre class="whitespace-pre-wrap leading-tight">{{ tool.outputPreview }}</pre>
                          </div>
                        </details>
                      </div>
                    </div>
                  </div>
                </template>

                <!-- B. 兜底纯工具列表渲染 -->
                <template v-else>
                  <div
                    v-for="tool in msg.toolCalls"
                    :key="tool.id"
                    class="rounded-lg border bg-black/50 text-[10px] overflow-hidden"
                    :class="tool.status === 'calling' ? 'border-amber-500/40 text-amber-300' : 'border-emerald-500/25 text-emerald-300'"
                  >
                    <details class="group/tcall">
                      <summary class="px-2.5 py-1.5 flex items-center justify-between cursor-pointer select-none hover:bg-white/[0.02]">
                        <div class="flex items-center space-x-1.5 truncate">
                          <span class="text-xs">{{ getToolMeta(tool.name).icon }}</span>
                          <span class="font-semibold text-zinc-200">{{ getToolMeta(tool.name).label }}</span>
                        </div>
                        <span class="text-[9px] px-1 py-0.2 rounded bg-emerald-500/20 text-emerald-300">✓ 获得数据</span>
                      </summary>
                      <div v-if="tool.outputPreview" class="p-2 border-t border-white/[0.06] bg-black/80 text-[10px] text-zinc-400 font-mono overflow-x-auto max-h-32">
                        <pre class="whitespace-pre-wrap leading-tight">{{ tool.outputPreview }}</pre>
                      </div>
                    </details>
                  </div>
                </template>
              </div>
            </div>

            <!-- 当仍在推理中且尚无正文时：展示精致轻量的数据就绪生成状态 -->
            <div
              v-if="msg.role === 'assistant' && (!msg.content || !msg.content.trim())"
              class="inline-flex items-center space-x-2 py-1 px-2.5 rounded-lg bg-emerald-500/[0.06] border border-emerald-500/15 text-[11px] text-zinc-300 self-start"
            >
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0"></span>
              <span class="text-zinc-300 font-medium">数据就绪，正在生成专业研报</span>
              <span class="inline-flex items-center space-x-0.5 text-emerald-400/80">
                <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 0ms"></span>
                <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 150ms"></span>
                <span class="w-1 h-1 rounded-full bg-current animate-bounce" style="animation-duration: 0.8s; animation-delay: 300ms"></span>
              </span>
            </div>

            <!-- Markdown 正文内容 -->
            <div
              v-if="msg.content && msg.content.trim()"
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
      <div class="p-3 border-t border-white/[0.08] bg-white/[0.02] shrink-0 rounded-b-2xl">
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
          <span>Enter 发送 · Shift+Enter 换行 · 四个角均可拖拽拉伸</span>
          <span class="text-amber-400 font-mono">{{ aiStore.aiModel === 'claude' ? 'Claude 3.7' : 'Gemini 3.7' }}</span>
        </div>
      </div>

      <!-- 2.5 四个角手动拉伸缩放把手 (4 Corner Manual Resizers) -->
      <!-- 左上角 (NW) -->
      <div
        @mousedown="onCornerMouseDown('nw', $event)"
        class="absolute -top-1.5 -left-1.5 w-5 h-5 cursor-nwse-resize z-50 group/corner flex items-start justify-start p-1"
        title="按住鼠标拖拽拉伸窗口 (左上)"
      >
        <div class="w-2 h-2 border-t-2 border-l-2 border-white/20 group-hover/corner:border-amber-400 rounded-tl-sm transition-colors"></div>
      </div>

      <!-- 右上角 (NE) -->
      <div
        @mousedown="onCornerMouseDown('ne', $event)"
        class="absolute -top-1.5 -right-1.5 w-5 h-5 cursor-nesw-resize z-50 group/corner flex items-start justify-end p-1"
        title="按住鼠标拖拽拉伸窗口 (右上)"
      >
        <div class="w-2 h-2 border-t-2 border-r-2 border-white/20 group-hover/corner:border-amber-400 rounded-tr-sm transition-colors"></div>
      </div>

      <!-- 左下角 (SW) -->
      <div
        @mousedown="onCornerMouseDown('sw', $event)"
        class="absolute -bottom-1.5 -left-1.5 w-5 h-5 cursor-nesw-resize z-50 group/corner flex items-end justify-start p-1"
        title="按住鼠标拖拽拉伸窗口 (左下)"
      >
        <div class="w-2 h-2 border-b-2 border-l-2 border-white/20 group-hover/corner:border-amber-400 rounded-bl-sm transition-colors"></div>
      </div>

      <!-- 右下角 (SE) -->
      <div
        @mousedown="onCornerMouseDown('se', $event)"
        class="absolute -bottom-1.5 -right-1.5 w-5 h-5 cursor-nwse-resize z-50 group/corner flex items-end justify-end p-1"
        title="按住鼠标拖拽拉伸窗口 (右下)"
      >
        <div class="w-2 h-2 border-b-2 border-r-2 border-white/20 group-hover/corner:border-amber-400 rounded-br-sm transition-colors"></div>
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
  </teleport>
</template>

<style scoped>
@keyframes robot-float {
  0%, 100% {
    transform: translateY(0px) rotate(0deg);
  }
  50% {
    transform: translateY(-4px) rotate(-2deg);
  }
}

.robot-float {
  animation: robot-float 2.2s ease-in-out infinite;
}
</style>
