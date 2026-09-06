<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { renderMarkdown, highlightCodeSnippet } from '@/utils/markdown'
import {
  copyToClipboard,
  formatToolchainMarkdown,
  formatSingleToolCall,
  formatFullMessageForCopy
} from '@/utils/clipboard'
import { useAiStore } from '@/stores/ai'
import { useAuthStore } from '@/stores/auth'
import { useStrategyStore } from '@/stores/strategy'
import {
  useCodexWorkspaceStore,
  type ExecutionMode,
  type ThinkingLevel,
  type FileSystemBrowseResult,
  type FileSystemItem,
  type DiscoveredProjectItem,
  type CodexProject,
  type CodexSession,
  AVAILABLE_MODELS,
  THINKING_LEVEL_OPTIONS,
} from '@/stores/codexWorkspace'
import ProjectModal from '@/components/ProjectModal.vue'
import { useModalLayer } from '@/stores/modalManager'

const router = useRouter()
const aiStore = useAiStore()
const authStore = useAuthStore()
const strategyStore = useStrategyStore()
const codexStore = useCodexWorkspaceStore()

// 接入统一弹窗与工作台层级调度治理，确保后打开或点击的 AI 助手在最顶层
const isAiOpen = computed(() => aiStore.isOpen)
const { zIndex: aiWindowZIndex, focusModal: focusAiWindow } = useModalLayer(
  'ai-assistant-window',
  isAiOpen,
  () => {
    aiStore.close()
  }
)

const chatContainer = ref<HTMLDivElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const permissionTooltipRef = ref<HTMLElement | null>(null)
const modelPopoverRef = ref<HTMLElement | null>(null)
const inputPrompt = ref('')
const toastMsg = ref('')

// 界面控制状态
const isSidebarOpen = ref(true)
const showMcpDrawer = ref(false)
const showPermissionTooltip = ref(false)
const showModelPopover = ref(false)
const showModeMenu = ref(false)
const modeMenuRef = ref<HTMLElement | null>(null)
const expandedProjects = ref<Record<string, boolean>>({})

function selectAssistantMode(mode: 'quant' | 'devops') {
  codexStore.setAssistantMode(mode)
  showModeMenu.value = false
  showToast(mode === 'quant' ? '✓ 已切换为量化投研模式' : '✓ 已切换为工程与运维模式')
}

// 当前激活模型与思考程度
const modelFilterTab = ref<'all' | 'agy' | 'standard'>('all')

const filteredModelList = computed(() => {
  if (modelFilterTab.value === 'agy') {
    return AVAILABLE_MODELS.filter((m) => m.isAgy)
  }
  if (modelFilterTab.value === 'standard') {
    return AVAILABLE_MODELS.filter((m) => !m.isAgy)
  }
  return AVAILABLE_MODELS
})

const currentModelItem = computed(() => {
  return AVAILABLE_MODELS.find((m) => m.id === codexStore.aiModel) || AVAILABLE_MODELS[0]
})

const currentThinkingOption = computed(() => {
  return THINKING_LEVEL_OPTIONS.find((t) => t.level === codexStore.thinkingLevel) || THINKING_LEVEL_OPTIONS[2]
})

function selectModel(modelId: string) {
  codexStore.setModel(modelId)
  showModelPopover.value = false
  const m = AVAILABLE_MODELS.find((x) => x.id === modelId)
  showToast(`✓ 已切换至模型: ${m?.name || modelId}`)
}

function selectThinkingLevel(level: ThinkingLevel) {
  codexStore.setThinkingLevel(level)
  showModelPopover.value = false
  const opt = THINKING_LEVEL_OPTIONS.find((x) => x.level === level)
  showToast(`✓ 已调整推演思考程度: ${opt?.label || level}`)
}

// 中文/CJK 输入法拼音合成状态 (防误发回车)
const isComposing = ref(false)

// MCP 动态热插拔数据
const mcpServers = ref<any[]>([])
const loadingMcp = ref(false)

function onCompositionStart() {
  isComposing.value = true
}

function onCompositionEnd() {
  setTimeout(() => {
    isComposing.value = false
  }, 50)
}

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2600)
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

// 监听窗口展开与消息变更，自动定位与聚焦
watch(
  () => aiStore.isOpen,
  (val) => {
    if (val) {
      nextTick(() => {
        textareaRef.value?.focus()
        scrollToBottom()
      })
      fetchMcpServers()
    }
  }
)

const streamingElapsed = ref(0)
let streamingTimer: any = null

watch(
  () => codexStore.isStreaming,
  (val) => {
    if (val) {
      streamingElapsed.value = 0
      clearInterval(streamingTimer)
      streamingTimer = setInterval(() => {
        streamingElapsed.value++
      }, 1000)
    } else {
      clearInterval(streamingTimer)
      streamingElapsed.value = 0
    }
  }
)

onUnmounted(() => {
  clearInterval(streamingTimer)
})

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60).toString().padStart(2, '0')
  const s = (sec % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

const activeRunningTool = computed(() => {
  const msgs = codexStore.currentMessages
  const last = msgs[msgs.length - 1]
  return last?.toolCalls?.find((t: any) => t.status === 'calling')
})

const latestAssistantMessage = computed(() => {
  const msgs = codexStore.currentMessages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant') return msgs[i]
  }
  return null
})

// 深度监听消息流与工具输出，持续贴合底部驻守
watch(
  () => codexStore.currentMessages,
  () => {
    scrollToBottom()
  },
  { deep: true }
)

function handleSend() {
  const text = inputPrompt.value.trim()
  if (!text || codexStore.isStreaming) return
  inputPrompt.value = ''
  showPermissionTooltip.value = false
  codexStore.sendMessage(text)
  scrollToBottom()
}

function handleStop() {
  if (codexStore.isStreaming) {
    codexStore.stopStreaming()
    showToast('⏹️ 已中断当前推演')
  }
}

function onTextareaKeydown(e: KeyboardEvent) {
  // 1. 中文输入法正在拼音选字中，绝不能发送
  if (e.isComposing || isComposing.value || e.keyCode === 229) {
    return
  }

  // 2. 普通 Enter (未按 Shift) 触发消息发送
  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    e.preventDefault()
    handleSend()
    return
  }

  // 3. Cmd+Enter 或 Ctrl+Enter 快捷发送
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
    e.preventDefault()
    handleSend()
    return
  }

  // 4. Esc 键：正在推演时中断生成 (绝不关闭弹窗，避免误触丢失工作上下文)
  if (e.key === 'Escape') {
    if (showPermissionTooltip.value) {
      showPermissionTooltip.value = false
      return
    }
    if (showModelPopover.value) {
      showModelPopover.value = false
      return
    }
    if (codexStore.isStreaming) {
      e.preventDefault()
      handleStop()
    }
  }
}

async function copyText(code: string, successMsg = '📋 已复制到剪贴板') {
  if (!code && code !== '') {
    showToast('⚠️ 内容为空，无需复制')
    return
  }
  const ok = await copyToClipboard(code)
  if (ok) {
    showToast(successMsg)
  } else {
    showToast('⚠️ 复制失败，请尝试手动选中文本复制')
  }
}

async function copyToolchain(toolCalls: any[]) {
  if (!toolCalls || toolCalls.length === 0) {
    showToast('⚠️ 无工具链记录')
    return
  }
  const md = formatToolchainMarkdown(toolCalls)
  await copyText(md, `📋 已复制全部 ${toolCalls.length} 步工具链及执行结果`)
}

async function copySingleTool(tc: any) {
  if (!tc) return
  const md = formatSingleToolCall(tc)
  const name = formatToolName(tc.name)
  await copyText(md, `📋 已复制工具 [${name}] 执行详情`)
}

async function copyFullMessage(msg: any) {
  if (!msg) return
  const fullText = formatFullMessageForCopy(msg)
  if (!fullText) {
    showToast('⚠️ 消息内容为空')
    return
  }
  await copyText(fullText, '📋 已复制完整回答 (包含工具链及推演结论)')
}

function applyCodeToEditor(code: string) {
  strategyStore.applyCodeToEditor(code)
  showToast('⚡ 策略代码已一键载入工作台编辑器！')
}

// -------------------------------------------------------------
// 简约风工具链展示 (Minimalist Toolchain Accordion) 状态与方法
// -------------------------------------------------------------
const expandedToolchains = ref<Record<string, boolean>>({})
const autoExpandedToolchains = ref<Set<string>>(new Set()) // 记录已经自动展开过的消息，防止重复触发
const expandedPreviews = ref<Record<string, boolean>>({})

function toggleToolchain(msgId: string) {
  expandedToolchains.value[msgId] = !isToolchainExpandedById(msgId)
}

function isToolchainExpandedById(msgId: string): boolean {
  return !!expandedToolchains.value[msgId]
}

function isToolchainExpanded(msg: any): boolean {
  // 用户手动操作过一次，严格以用户选择为准（防闪烁）
  if (expandedToolchains.value[msg.id] !== undefined) {
    return expandedToolchains.value[msg.id]
  }
  // 默认精简收起，零闪烁与零跳动；用户点击顶栏即可流畅展开
  return false
}

function togglePreview(tcId: string) {
  expandedPreviews.value[tcId] = !expandedPreviews.value[tcId]
}

function isPreviewExpanded(tcId: string): boolean {
  return !!expandedPreviews.value[tcId]
}

function hasRunningTools(msg: any): boolean {
  return !!msg.toolCalls?.some((t: any) => t.status === 'calling')
}

function countCompletedTools(msg: any): number {
  return (msg.toolCalls || []).filter((t: any) => t.status === 'done').length
}

const toolNameMap: Record<string, string> = {
  get_stock_quote: '行情快照',
  get_stock_bars: 'K线行情',
  get_stock_valuation: '估值分位',
  get_pe_pb_percentile: '估值分析',
  get_financial_metrics: '财务指标',
  run_backtest_fast: '策略回测',
  validate_strategy_code: '策略校验',
  read_file: '读取文件',
  write_file: '写入文件',
  list_directory: '浏览工作区',
  run_command: 'Shell 命令行',
  admin_execute_shell: '宿主机 Shell',
  admin_docker_manage: 'Docker 容器',
  admin_manage_service: '微服务治理',
  admin_modify_source_code: '代码精准运维',
  bash_executor: 'Shell 终端',
  docker_manager: 'Docker 容器',
  system_inspector: '系统巡检',
}

function formatToolName(name: string): string {
  if (toolNameMap[name]) return toolNameMap[name]
  return name.replace(/_/g, ' ')
}

function getToolIcon(name: string): string {
  const lower = (name || '').toLowerCase()
  if (lower.includes('quote') || lower.includes('market')) return '📈'
  if (lower.includes('bar') || lower.includes('kline')) return '📊'
  if (lower.includes('val') || lower.includes('pe') || lower.includes('pb')) return '⚖️'
  if (lower.includes('fin') || lower.includes('metric') || lower.includes('report')) return '📑'
  if (lower.includes('backtest')) return '⚡'
  if (lower.includes('valid')) return '🔍'
  if (lower.includes('file') || lower.includes('dir')) return '📄'
  if (lower.includes('bash') || lower.includes('shell') || lower.includes('cmd')) return '💻'
  if (lower.includes('docker') || lower.includes('container')) return '🐳'
  return '⚙️'
}

function formatArgs(args: Record<string, any> | undefined): string {
  if (!args || typeof args !== 'object') return ''
  return Object.entries(args)
    .map(([k, v]) => {
      const valStr = typeof v === 'object' ? JSON.stringify(v) : String(v)
      const truncated = valStr.length > 35 ? valStr.slice(0, 32) + '...' : valStr
      return `${k}=${truncated}`
    })
    .join('  ')
}

// 事件代理：捕获 Markdown 代码块内的“复制”、“载入工作台”与“极速试跑回测”按钮点击
async function onChatContainerClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  const copyBtn = target.closest('.copy-code-btn') as HTMLElement
  if (copyBtn) {
    const rawEncoded = copyBtn.getAttribute('data-code') || ''
    if (rawEncoded) {
      const code = decodeURIComponent(rawEncoded)
      copyText(code)
      return
    }
  }

  const runBtn = target.closest('.run-backtest-btn') as HTMLElement
  if (runBtn) {
    const rawEncoded = runBtn.getAttribute('data-code') || ''
    if (rawEncoded) {
      const code = decodeURIComponent(rawEncoded)
      showToast('⚡ 正在对策略进行最小日期极速试跑预检 (30天数据)...')
      try {
        const dryRes = await strategyStore.dryRunStrategy(code)
        if (dryRes.success) {
          showToast('✅ 极速试跑验证通过！正在载入工作台并开启回测')
          strategyStore.applyCodeToEditor(code)
          strategyStore.openBacktestCockpit({ autoRun: true })
        } else {
          showToast('⚠️ 策略试跑未通过，已自动提交 AI 进行诊断与修复...')
          strategyStore.askAiToFixStrategy(dryRes.error, code)
        }
      } catch (err: any) {
        showToast('⚠️ 策略试跑未通过，已自动提交 AI 进行诊断与修复...')
        strategyStore.askAiToFixStrategy(err?.message || '试跑通信异常', code)
      }
      return
    }
  }

  const applyBtn = target.closest('.apply-editor-btn') as HTMLElement
  if (applyBtn) {
    const rawEncoded = applyBtn.getAttribute('data-code') || ''
    if (rawEncoded) {
      const code = decodeURIComponent(rawEncoded)
      applyCodeToEditor(code)
      return
    }
  }
}

function formatWeekdayTime(ts: number) {
  if (!ts) return ''
  const d = new Date(ts > 1e11 ? ts : ts * 1000)
  const days = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  const dayStr = days[d.getDay()] || ''
  const hours = d.getHours().toString().padStart(2, '0')
  const minutes = d.getMinutes().toString().padStart(2, '0')
  return `${dayStr}${hours}:${minutes}`
}

function handleEditMessage(content: string) {
  inputPrompt.value = content
  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.focus()
      textareaRef.value.setSelectionRange(content.length, content.length)
    }
  })
  showToast('✏️ 已载入输入框，修改后可重写推演')
}

// -------------------------------------------------------------
// 选中文本弹出气泡提问 (Ask 阿尔法 / Text Selection Tooltip)
// -------------------------------------------------------------
const selectionTooltip = ref({
  visible: false,
  x: 0,
  y: 0,
  text: '',
})

function handleAssistantTextMouseUp() {
  setTimeout(() => {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed) {
      selectionTooltip.value.visible = false
      return
    }
    const text = selection.toString().trim()
    if (!text || text.length < 2) {
      selectionTooltip.value.visible = false
      return
    }

    const anchorNode = selection.anchorNode
    const focusNode = selection.focusNode
    const anchorEl = (anchorNode instanceof HTMLElement ? anchorNode : anchorNode?.parentElement)
    const focusEl = (focusNode instanceof HTMLElement ? focusNode : focusNode?.parentElement)

    const isInsideAssistant =
      anchorEl?.closest('.agent-assistant-message') ||
      focusEl?.closest('.agent-assistant-message')

    if (!isInsideAssistant) {
      selectionTooltip.value.visible = false
      return
    }

    if (selection.rangeCount > 0) {
      const range = selection.getRangeAt(0)
      const rect = range.getBoundingClientRect()
      if (rect && rect.width > 0 && rect.height > 0) {
        selectionTooltip.value = {
          visible: true,
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top - 8),
          text,
        }
      }
    }
  }, 30)
}

function handleChatScroll() {
  if (selectionTooltip.value.visible) {
    selectionTooltip.value.visible = false
  }
}

function handleAskAlpha() {
  const text = selectionTooltip.value.text.trim()
  if (!text) return
  selectionTooltip.value.visible = false
  window.getSelection()?.removeAllRanges()

  const sanitized = text.replace(/\s+/g, ' ').trim()
  const quoteSnippet = sanitized.length > 120 ? sanitized.slice(0, 117) + '...' : sanitized
  const quotePrompt = `关于「${quoteSnippet}」，我想问：`

  if (!inputPrompt.value.trim()) {
    inputPrompt.value = quotePrompt
  } else {
    inputPrompt.value = `${inputPrompt.value}\n\n${quotePrompt}`
  }

  nextTick(() => {
    if (textareaRef.value) {
      textareaRef.value.focus()
      textareaRef.value.setSelectionRange(inputPrompt.value.length, inputPrompt.value.length)
    }
  })
  showToast('🤖 已将选中文本引用至输入框')
}

function toggleProjectExpand(projectId: string) {
  expandedProjects.value[projectId] = !isProjectExpanded(projectId)
}

function isProjectExpanded(projectId: string): boolean {
  if (expandedProjects.value[projectId] === undefined) {
    return true
  }
  return expandedProjects.value[projectId]
}

function handleSelectSession(projectId: string, sessionId: string) {
  codexStore.selectSession(projectId, sessionId)
  scrollToBottom()
}

async function handleNewChat(projectId?: string) {
  const sessId = await codexStore.createSession(projectId)
  if (sessId) {
    showToast('✨ 已在当前工程下开辟新会话')
    scrollToBottom()
  }
}

async function handleDeleteProject(proj: CodexProject) {
  if (codexStore.projects.length <= 1) {
    showToast('⚠️ 至少保留一个工程项目，不可全部移除')
    return
  }
  if (!confirm(`确定要解除挂载项目「${proj.name}」吗？\n（仅解除挂载列表，不会物理删除磁盘上的源码文件）`)) {
    return
  }
  const ok = await codexStore.deleteProject(proj.id)
  if (ok) {
    showToast(`✓ 已成功移除项目「${proj.name}」`)
  } else {
    showToast('❌ 移除项目失败')
  }
}

async function handleDeleteSession(projectId: string, sess: CodexSession) {
  if (!confirm(`确定要删除会话「${sess.title}」吗？`)) {
    return
  }
  const ok = await codexStore.deleteSession(projectId, sess.id)
  if (ok) {
    showToast(`✓ 已删除会话「${sess.title}」`)
  } else {
    showToast('❌ 删除会话失败')
  }
}

function handleSendSuggestion(text: string) {
  inputPrompt.value = text
  nextTick(() => {
    handleSend()
  })
}

// -------------------------------------------------------------
// 权限安全模式选择 (Tooltip / Popover 形式切换)
// -------------------------------------------------------------
function selectPermissionMode(mode: ExecutionMode) {
  codexStore.setExecutionMode(mode)
  showPermissionTooltip.value = false
  const labelMap: Record<ExecutionMode, string> = {
    auto: '⚡ 完全访问 (全自动执行)',
    confirm_sensitive: '🛡️ 敏感操作确认 (安全推荐)',
    confirm_all: '🔒 全量严格审批',
  }
  showToast(`✓ 已切换权限模式：${labelMap[mode]}`)
}

function handleClickOutside(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (permissionTooltipRef.value && !permissionTooltipRef.value.contains(target as Node)) {
    showPermissionTooltip.value = false
  }
  if (modelPopoverRef.value && !modelPopoverRef.value.contains(target as Node)) {
    showModelPopover.value = false
  }
  if (modeMenuRef.value && !modeMenuRef.value.contains(target as Node)) {
    showModeMenu.value = false
  }
  if (!target.closest('#ask-alpha-selection-tooltip')) {
    selectionTooltip.value.visible = false
  }
}

// -------------------------------------------------------------
// 挂载与导入工程项目模态框 (统一全局层级治理)
// -------------------------------------------------------------
const showProjectModal = ref(false)

function openProjectModal() {
  showProjectModal.value = true
}

// -------------------------------------------------------------
// MCP 动态热插拔管理 (Dynamic Plug & Unplug)
// -------------------------------------------------------------
async function fetchMcpServers() {
  try {
    loadingMcp.value = true
    const res = await fetch('/api/v1/agent/mcp/servers')
    if (res.ok) {
      const data = await res.json()
      mcpServers.value = data.servers || []
    }
  } catch (e) {
    console.error('Failed to load MCP servers:', e)
  } finally {
    loadingMcp.value = false
  }
}

async function toggleMcpServer(server: any) {
  const newStatus = !server.enabled
  try {
    const res = await fetch(`/api/v1/agent/mcp/servers/${server.name}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: newStatus }),
    })
    if (res.ok) {
      server.enabled = newStatus
      showToast(newStatus ? `🔌 已成功挂载 MCP: ${server.name}` : `⏹️ 已动态拔出断开 MCP: ${server.name}`)
      await fetchMcpServers()
    } else {
      showToast('❌ MCP 状态切换失败')
    }
  } catch (e) {
    showToast('❌ 网络异常')
  }
}

const totalActiveMcpTools = computed(() => {
  return mcpServers.value
    .filter((s) => s.enabled)
    .reduce((acc, cur) => acc + (cur.tools_count || 0), 0)
})

// 分层解耦 MCP 数据分组：stock, user, other(custom), admin
const expandedMcpMap = ref<Record<string, boolean>>({
  'mcp-stock': false,
  'mcp-user': false,
  'admin-system-tools': false,
})

function toggleMcpExpanded(name: string) {
  expandedMcpMap.value[name] = !expandedMcpMap.value[name]
}

const stockServer = computed(() =>
  mcpServers.value.find((s) => s.name === 'mcp-stock' || s.group === 'stock' || s.group === 'system')
)
const userServer = computed(() =>
  mcpServers.value.find((s) => s.name === 'mcp-user' || s.group === 'user')
)
const customServers = computed(() =>
  mcpServers.value.filter(
    (s) =>
      s.name !== 'mcp-stock' &&
      s.name !== 'stock-data-mcp' &&
      s.name !== 'mcp-user' &&
      s.name !== 'admin-system-tools' &&
      s.group !== 'stock' &&
      s.group !== 'system' &&
      s.group !== 'user' &&
      s.group !== 'admin'
  )
)
const adminServer = computed(() =>
  mcpServers.value.find((s) => s.name === 'admin-system-tools' || s.group === 'admin')
)

// 单个工具独立开关
async function toggleMcpTool(server: any, tool: any) {
  const newStatus = !tool.enabled
  try {
    const res = await fetch(`/api/v1/agent/mcp/servers/${server.name}/tools/${tool.name}/toggle`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
      },
      body: JSON.stringify({ enabled: newStatus, server_name: server.name }),
    })
    if (res.ok) {
      tool.enabled = newStatus
      showToast(newStatus ? `✓ 工具 [${tool.name}] 已启用` : `⏹ 工具 [${tool.name}] 已停用`)
    } else {
      const data = await res.json().catch(() => ({}))
      showToast(data.detail || '❌ 工具切换失败')
    }
  } catch {
    showToast('❌ 网络请求失败')
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

  const minW = 480
  const minH = 420

  let newX = resizeInitialX
  let newY = resizeInitialY
  let newW = resizeInitialW
  let newH = resizeInitialH

  if (activeCorner === 'se') {
    newW = Math.max(minW, resizeInitialW + deltaX)
    newH = Math.max(minH, resizeInitialH + deltaY)
  } else if (activeCorner === 'sw') {
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

  aiStore.updatePosition(newX, newY)
  aiStore.updateSize(newW, newH)
}

function onCornerMouseUp() {
  isCornerResizing = false
  activeCorner = null
  window.removeEventListener('mousemove', onCornerMouseMove)
  window.removeEventListener('mouseup', onCornerMouseUp)
}

// -------------------------------------------------------------
// 悬浮胶囊自由拖动 (Trigger Capsule Draggable)
// -------------------------------------------------------------
const { triggerPosition: triggerPos } = storeToRefs(aiStore)

let isDraggingTrigger = false
let triggerMouseStartX = 0
let triggerMouseStartY = 0
let triggerInitialX = 0
let triggerInitialY = 0
let hasTriggerMoved = false

function onTriggerMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  isDraggingTrigger = true
  hasTriggerMoved = false
  triggerMouseStartX = e.clientX
  triggerMouseStartY = e.clientY
  triggerInitialX = triggerPos.value?.x ?? (typeof window !== 'undefined' ? window.innerWidth - 232 : 1150)
  triggerInitialY = triggerPos.value?.y ?? (typeof window !== 'undefined' ? window.innerHeight - 64 : 720)

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

  aiStore.updateTriggerPosition(triggerInitialX + deltaX, triggerInitialY + deltaY)
}

function onTriggerMouseUp() {
  if (!isDraggingTrigger) return
  isDraggingTrigger = false
  window.removeEventListener('mousemove', onTriggerMouseMove)
  window.removeEventListener('mouseup', onTriggerMouseUp)

  if (!hasTriggerMoved && triggerPos.value) {
    aiStore.open(triggerPos.value)
  }
}

// 视口改变时保证悬浮胶囊始终在安全屏幕内
function onWindowResize() {
  if (typeof window === 'undefined') return
  const maxX = Math.max(10, window.innerWidth - 220)
  const maxY = Math.max(10, window.innerHeight - 50)
  if (triggerPos.value && (triggerPos.value.x > maxX || triggerPos.value.y > maxY)) {
    aiStore.updateTriggerPosition(
      Math.min(triggerPos.value.x, maxX),
      Math.min(triggerPos.value.y, maxY)
    )
  }
}

// 全局快捷键支持 (⌘+L / Ctrl+L / 单键 L 呼出/收起，Esc 中断推演)
function handleGlobalKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented) return

  // 1. 组合键 ⌘+L 或 Ctrl+L
  const isCmdL = (e.metaKey || e.ctrlKey) && (e.key?.toLowerCase() === 'l' || e.code === 'KeyL')

  // 2. 单键 L（在非文本编辑态时直接单按呼出）
  const activeEl = document.activeElement as HTMLElement | null
  const isTyping = activeEl && (
    activeEl.tagName === 'INPUT' ||
    activeEl.tagName === 'TEXTAREA' ||
    activeEl.tagName === 'SELECT' ||
    activeEl.isContentEditable ||
    activeEl.closest('.monaco-editor')
  )
  const isSingleL = !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping && (e.key?.toLowerCase() === 'l' || e.code === 'KeyL')

  if (isCmdL || isSingleL) {
    e.preventDefault()
    aiStore.toggleOpen(triggerPos.value)
    return
  }

  if (aiStore.isOpen) {
    if (e.key === 'Escape') {
      if (showPermissionTooltip.value) {
        showPermissionTooltip.value = false
        return
      }
      if (codexStore.isStreaming) {
        e.preventDefault()
        handleStop()
      }
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('click', handleClickOutside)
  window.addEventListener('resize', onWindowResize)
  codexStore.fetchProjects()
  fetchMcpServers()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('click', handleClickOutside)
  window.removeEventListener('resize', onWindowResize)
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
    <!-- ========================================================================= -->
    <!-- 1. 收起状态：自由拖拽的暗色毛玻璃悬浮胶囊 -->
    <!-- ========================================================================= -->
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
        class="group flex items-center justify-between w-[216px] px-3 py-2 rounded-full bg-[#13151b]/95 hover:bg-[#181a23] border border-white/[0.14] hover:border-purple-500/50 shadow-2xl shadow-black/80 hover:shadow-purple-500/20 backdrop-blur-2xl transition-[box-shadow,border-color,background-color] duration-200 cursor-grab active:cursor-grabbing select-none"
        title="点击唤醒 Alpha 智能量化工作台 (快捷键 ⌘L / L)，按住左键自由拖动"
      >
        <div class="flex items-center space-x-2.5 min-w-0">
          <div class="relative flex-shrink-0 flex items-center justify-center w-7 h-7 rounded-xl bg-gradient-to-br from-purple-500/25 via-indigo-500/20 to-transparent border border-purple-500/30 text-sm shadow-sm group-hover:border-purple-400/60 transition-colors pointer-events-none">
            <span>🤖</span>
            <span
              class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-[#13151b]"
              :class="codexStore.isStreaming ? 'bg-amber-400 animate-ping' : 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'"
            ></span>
          </div>

          <div class="flex flex-col text-left pointer-events-none min-w-0">
            <div class="flex items-center space-x-1.5">
              <span class="text-xs font-semibold text-zinc-100 group-hover:text-purple-300 transition-colors tracking-wide truncate">Alpha Copilot</span>
            </div>
            <span class="text-[9px] text-zinc-400 font-mono flex items-center space-x-1 truncate">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block animate-pulse flex-shrink-0"></span>
              <span class="truncate">{{ codexStore.isStreaming ? 'Alpha 正在推演...' : '阿尔法投研工坊' }}</span>
            </span>
          </div>
        </div>

        <div class="ml-1 pl-2 border-l border-white/[0.1] flex items-center flex-shrink-0 pointer-events-none">
          <kbd class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.12] text-zinc-300 font-mono shadow-inner group-hover:border-purple-500/40 group-hover:text-purple-300 transition-colors">⌘L</kbd>
        </div>
      </div>
    </transition>

    <!-- ========================================================================= -->
    <!-- 2. 展开状态：集成 Codex 工作台大框架的高质感悬浮窗口 (Fixed Floating Window) -->
    <!-- ========================================================================= -->
    <div
      v-if="aiStore.isOpen"
      @mousedown.capture="focusAiWindow"
      :style="{
        position: 'fixed',
        left: `${aiStore.position.x}px`,
        top: `${aiStore.position.y}px`,
        width: `${aiStore.size.width}px`,
        height: `${aiStore.size.height}px`,
        zIndex: aiWindowZIndex,
      }"
      class="bg-[#14151b]/95 border border-white/[0.14] rounded-2xl shadow-2xl flex flex-col backdrop-blur-2xl select-none overflow-hidden"
    >
      <!-- 提示气泡 Toast -->
      <div
        v-if="toastMsg"
        class="absolute top-12 left-1/2 -translate-x-1/2 z-50 px-3.5 py-1.5 rounded-xl bg-emerald-500/90 text-white font-medium text-xs shadow-xl backdrop-blur-sm animate-bounce pointer-events-none"
      >
        {{ toastMsg }}
      </div>

      <!-- 2.1 极简专业标题栏 (去掉了 Mac 拟物红黄绿，无干扰、干净利落) -->
      <div
        @mousedown="onHeaderMouseDown"
        class="px-3.5 py-2 border-b border-white/[0.08] bg-white/[0.02] flex items-center justify-between shrink-0 cursor-grab active:cursor-grabbing select-none"
      >
        <!-- 左侧：侧栏切换开关 + 当前工程/会话面包屑 -->
        <div class="flex items-center space-x-2.5">
          <button
            @click="isSidebarOpen = !isSidebarOpen"
            class="p-1 rounded-lg hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-colors cursor-pointer text-xs"
            title="展开/收起项目侧栏"
          >
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7" />
            </svg>
          </button>

          <div class="flex items-center space-x-1.5 text-xs">
            <template v-if="codexStore.assistantMode === 'quant' || !authStore.isAdmin">
              <span class="font-bold text-white tracking-wide flex items-center space-x-1">
                <span>📈</span>
                <span>量化投研助手</span>
              </span>
              <span class="text-zinc-500">/</span>
              <span class="text-zinc-300 font-medium truncate max-w-[220px]">
                {{ codexStore.activeSession?.title || '新对话' }}
              </span>
            </template>
            <template v-else>
              <span class="font-bold text-white tracking-wide flex items-center space-x-1">
                <span>💻</span>
                <span>{{ codexStore.activeProject?.name || '项目' }}</span>
              </span>
              <span class="text-zinc-500">/</span>
              <span class="text-zinc-300 font-medium truncate max-w-[220px]">
                {{ codexStore.activeSession?.title || '新对话' }}
              </span>
            </template>

            <!-- 权限角色标识 -->
            <span
              v-if="authStore.isAdmin"
              class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30 font-mono"
              title="当前已激活超级管理员特权"
            >
              ⚡ Super Admin
            </span>
            <span
              v-else-if="authStore.isLoggedIn"
              class="px-1.5 py-0.2 rounded text-[9px] font-medium bg-blue-500/15 text-blue-300 border border-blue-500/25 font-mono"
              title="标准量化投研模式"
            >
              标准用户
            </span>
            <button
              v-else
              @click="authStore.openLogin()"
              class="px-1.5 py-0.2 rounded text-[9px] font-medium bg-white/[0.06] text-zinc-400 border border-white/[0.1] hover:text-white hover:bg-white/[0.1] cursor-pointer transition-colors"
              title="点击登录以解锁特权"
            >
              未登录 (访客)
            </button>
          </div>
        </div>

        <!-- 右侧：模式切换 (Tooltip切换卡片) + 开辟新会话 + Agent 配置 + 关闭窗口 (✕) -->
        <div class="flex items-center space-x-1.5 text-zinc-400 text-xs">
          <!-- 场景模式切换器 (右侧固定，Tooltip 浮层切换，极致节省空间) -->
          <div v-if="authStore.isAdmin" ref="modeMenuRef" class="relative">
            <button
              @click.stop="showModeMenu = !showModeMenu"
              :class="[
                'px-2 py-0.5 rounded-md text-[11px] font-medium transition-all flex items-center space-x-1 cursor-pointer border',
                codexStore.assistantMode === 'quant'
                  ? 'bg-purple-500/15 border-purple-500/35 text-purple-200 hover:bg-purple-500/25 shadow-xs'
                  : 'bg-amber-500/15 border-amber-500/35 text-amber-200 hover:bg-amber-500/25 shadow-xs',
              ]"
              title="点击切换场景模式 (投研 / 工程)"
            >
              <span class="text-xs">{{ codexStore.assistantMode === 'quant' ? '📈' : '💻' }}</span>
              <span>{{ codexStore.assistantMode === 'quant' ? '投研模式' : '工程模式' }}</span>
              <svg
                :class="['w-2.5 h-2.5 transition-transform duration-150 text-zinc-400', showModeMenu ? 'rotate-180' : '']"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            <!-- 模式切换浮层 Tooltip 菜单 -->
            <transition name="fade">
              <div
                v-if="showModeMenu"
                class="absolute right-0 top-full mt-1.5 w-60 bg-[#161722]/98 border border-white/[0.14] rounded-xl shadow-2xl p-1.5 z-50 backdrop-blur-xl space-y-1 text-left"
              >
                <div class="px-2 py-1 text-[10px] text-zinc-400 font-semibold tracking-wider uppercase border-b border-white/[0.06] flex items-center justify-between">
                  <span>场景模式切换</span>
                  <span class="text-[9px] text-purple-400 font-mono">⚡ Super Admin</span>
                </div>

                <button
                  @click.stop="selectAssistantMode('quant')"
                  :class="[
                    'w-full text-left p-2 rounded-lg text-xs transition-all flex items-start space-x-2.5 cursor-pointer',
                    codexStore.assistantMode === 'quant'
                      ? 'bg-purple-500/25 text-purple-200 border border-purple-500/30'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.05]',
                  ]"
                >
                  <span class="text-base leading-none">📈</span>
                  <div class="flex-1">
                    <div class="flex items-center justify-between font-semibold text-[11px] text-white">
                      <span>量化投研模式</span>
                      <span v-if="codexStore.assistantMode === 'quant'" class="text-[10px] text-purple-300">✓ 当前</span>
                    </div>
                    <div class="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                      纯净投研体验，免挂载项目，物理屏蔽终端与源码工具，专注行情与回测
                    </div>
                  </div>
                </button>

                <button
                  @click.stop="selectAssistantMode('devops')"
                  :class="[
                    'w-full text-left p-2 rounded-lg text-xs transition-all flex items-start space-x-2.5 cursor-pointer',
                    codexStore.assistantMode === 'devops'
                      ? 'bg-amber-500/25 text-amber-200 border border-amber-500/30'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.05]',
                  ]"
                >
                  <span class="text-base leading-none">💻</span>
                  <div class="flex-1">
                    <div class="flex items-center justify-between font-semibold text-[11px] text-white">
                      <span>工程与运维模式</span>
                      <span v-if="codexStore.assistantMode === 'devops'" class="text-[10px] text-amber-300">✓ 当前</span>
                    </div>
                    <div class="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                      代码工作台，挂载代码工程，赋能宿主机终端 Shell、测试验证与代码修改
                    </div>
                  </div>
                </button>
              </div>
            </transition>
          </div>

          <button
            @click="codexStore.createSession()"
            class="px-2 py-0.5 rounded-lg hover:bg-white/[0.08] hover:text-zinc-200 transition-colors cursor-pointer flex items-center space-x-1 text-[11px]"
            title="开辟新会话"
          >
            <span>＋</span>
            <span>新对话</span>
          </button>

          <button
            @click="router.push('/agent-settings')"
            class="p-1 rounded-lg hover:bg-white/[0.08] hover:text-zinc-200 transition-colors cursor-pointer"
            title="Agent 管理与配置中心"
          >
            ⚙️
          </button>

          <button
            @click="aiStore.close()"
            class="p-1 rounded-lg hover:bg-red-500/20 hover:text-red-300 transition-colors cursor-pointer"
            title="收起窗口 (⌘+J)"
          >
            ✕
          </button>
        </div>
      </div>

      <!-- 2.2 窗体主体区：左侧多项目树 + 右侧主画布推演 -->
      <div class="flex-1 flex overflow-hidden relative">
        <!-- 2.2.1 左侧边栏 (Projects & MCP Navigation，去除了底部的冗余用户信息) -->
        <div
          v-show="isSidebarOpen"
          class="w-56 shrink-0 bg-[#121318] border-r border-white/[0.08] flex flex-col justify-between"
        >
          <div class="p-2 space-y-2 overflow-y-auto flex-1">
            <!-- 快捷入口：新对话 -->
            <button
              @click="handleNewChat()"
              class="w-full flex items-center justify-between px-2.5 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-zinc-200 text-xs transition-colors cursor-pointer group"
            >
              <div class="flex items-center space-x-2">
                <span>📝</span>
                <span class="font-medium">新对话</span>
              </div>
              <span class="text-zinc-400 group-hover:text-white text-xs">＋</span>
            </button>

            <!-- @ MCP 插件 (点击滑出二级抽屉管理) -->
            <button
              @click="showMcpDrawer = !showMcpDrawer"
              :class="[
                'w-full flex items-center justify-between px-2.5 py-2 rounded-xl text-xs transition-all cursor-pointer border',
                showMcpDrawer
                  ? 'bg-purple-500/20 border-purple-500/40 text-purple-300 shadow-sm'
                  : 'bg-white/[0.03] border-white/[0.06] text-zinc-300 hover:text-white hover:bg-white/[0.07]',
              ]"
              title="查看与动态管理 MCP 数据服务及工具"
            >
              <div class="flex items-center space-x-2">
                <span>🔌</span>
                <span class="font-medium">MCP 插件与工具</span>
              </div>
              <span class="px-2 py-0.5 rounded-full text-[10px] font-mono bg-purple-500/20 text-purple-300">
                {{ totalActiveMcpTools }} 工具
              </span>
            </button>

            <!-- 场景 A：普通量化投研模式（无项目挂载、无代码工程杂音，仅展示极简纯粹的历史对话列表） -->
            <div v-if="codexStore.assistantMode === 'quant' || !authStore.isAdmin" class="pt-2">
              <div class="flex items-center justify-between px-1 pb-1.5 text-[11px] font-semibold text-zinc-400">
                <span>历史对话</span>
                <span class="text-[10px] text-zinc-500 font-mono">{{ codexStore.allSessions.length }} 个会话</span>
              </div>

              <!-- 历史对话会话列表 (纯净无项目噪音) -->
              <div class="space-y-0.5 max-h-[calc(100vh-320px)] overflow-y-auto">
                <div
                  v-for="item in codexStore.allSessions"
                  :key="item.session.id"
                  @click="handleSelectSession(item.project.id, item.session.id)"
                  :class="[
                    'group/sess flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-all duration-150',
                    codexStore.activeSessionId === item.session.id
                      ? 'bg-white/[0.14] text-white font-medium shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]',
                  ]"
                  :title="item.session.title"
                >
                  <div class="flex items-center space-x-1.5 truncate flex-1 mr-1">
                    <span class="text-xs text-zinc-500 group-hover/sess:text-zinc-300">💬</span>
                    <span class="truncate">{{ item.session.title }}</span>
                  </div>

                  <!-- 删除会话按钮 (悬停出现) -->
                  <button
                    @click.stop="handleDeleteSession(item.project.id, item.session)"
                    class="opacity-0 group-hover/sess:opacity-100 p-0.5 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-all cursor-pointer shrink-0"
                    title="删除该会话"
                  >
                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                <div v-if="codexStore.allSessions.length === 0" class="py-8 text-center text-zinc-500 text-xs">
                  暂无历史对话
                </div>
              </div>
            </div>

            <!-- 场景 B：工程与系统运维模式（仅超管主动切换至工程模式时展示项目挂载、导入与代码树） -->
            <div v-else class="pt-2">
              <div class="flex items-center justify-between px-1 pb-1.5 text-[11px] font-semibold text-zinc-400">
                <span>项目工程</span>
                <button
                  @click="openProjectModal"
                  class="text-xs px-2 py-0.5 rounded text-amber-400 hover:bg-amber-500/10 transition-colors cursor-pointer flex items-center space-x-0.5 font-medium"
                  title="挂载部署机工程目录或从本机上传工程项目"
                >
                  <span>＋ 挂载/导入</span>
                </button>
              </div>

              <!-- 项目树项 (仅显示当前真实工程，无虚假预设) -->
              <div class="space-y-1">
                <div v-for="proj in codexStore.projects" :key="proj.id" class="space-y-0.5">
                  <div
                    @click="toggleProjectExpand(proj.id)"
                    class="flex items-center justify-between px-2 py-1 rounded-lg text-xs font-medium cursor-pointer transition-colors group"
                    :class="codexStore.activeProjectId === proj.id ? 'text-zinc-100 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
                  >
                    <div class="flex items-center space-x-1.5 truncate">
                      <svg
                        :class="['w-3 h-3 text-zinc-400 transition-transform duration-200', isProjectExpanded(proj.id) ? 'rotate-90' : '']"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                      </svg>
                      <span class="text-xs">📁</span>
                      <span class="truncate">{{ proj.name }}</span>
                    </div>

                    <div class="flex items-center space-x-1 shrink-0">
                      <span
                        v-if="proj.host_type === 'remote'"
                        class="px-1 py-0.1 rounded text-[8px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/20"
                      >
                        部署机
                      </span>
                      <span
                        v-else
                        class="px-1 py-0.1 rounded text-[8px] font-mono bg-emerald-500/15 text-emerald-300 border border-emerald-500/20"
                      >
                        本机
                      </span>

                      <!-- 移除挂载项目按钮 (悬停出现) -->
                      <button
                        @click.stop="handleDeleteProject(proj)"
                        class="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-all cursor-pointer"
                        title="解除该项目挂载"
                      >
                        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </div>

                  <!-- 展开的项目会话列表 (灰色高亮胶囊) -->
                  <div v-show="isProjectExpanded(proj.id)" class="pl-4 pr-1 space-y-0.5">
                    <div
                      v-for="sess in proj.sessions"
                      :key="sess.id"
                      @click="handleSelectSession(proj.id, sess.id)"
                      :class="[
                        'group/sess flex items-center justify-between px-2 py-1 rounded-lg text-[11px] cursor-pointer transition-all duration-150',
                        codexStore.activeProjectId === proj.id && codexStore.activeSessionId === sess.id
                          ? 'bg-white/[0.14] text-white font-medium shadow-xs'
                          : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]',
                      ]"
                      :title="sess.title"
                    >
                      <span class="truncate flex-1 mr-1">{{ sess.title }}</span>

                      <!-- 删除会话按钮 (悬停出现) -->
                      <button
                        @click.stop="handleDeleteSession(proj.id, sess)"
                        class="opacity-0 group-hover/sess:opacity-100 p-0.5 rounded hover:bg-red-500/20 text-zinc-500 hover:text-red-400 transition-all cursor-pointer shrink-0"
                        title="删除该会话"
                      >
                        <svg class="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>

                    <button
                      @click="handleNewChat(proj.id)"
                      class="w-full text-left px-2 py-0.5 text-[10px] text-zinc-400 hover:text-purple-300 cursor-pointer flex items-center space-x-1"
                    >
                      <span>＋</span>
                      <span>新建任务会话</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 2.2.2 MCP 动态分层治理抽屉 (Separated Stock, User, Custom, Admin Sections) -->
        <transition name="slide-fade">
          <div
            v-if="showMcpDrawer"
            class="absolute top-0 left-56 bottom-0 w-88 bg-[#161720]/95 border-r border-white/[0.12] z-30 shadow-2xl p-4 flex flex-col justify-between backdrop-blur-xl"
          >
            <div class="space-y-3.5 flex-1 overflow-y-auto pr-0.5">
              <!-- 顶部标题与关闭 -->
              <div class="flex items-center justify-between border-b border-white/[0.08] pb-2.5">
                <div class="flex items-center space-x-2">
                  <span class="text-sm">🔌</span>
                  <span class="font-bold text-xs text-white">MCP 插件与工具治理</span>
                </div>
                <button
                  @click="showMcpDrawer = false"
                  class="text-zinc-400 hover:text-white text-xs cursor-pointer p-1 rounded hover:bg-white/[0.06] transition-colors"
                >
                  ✕
                </button>
              </div>

              <!-- ======================================================= -->
              <!-- 1. 金融行情服务 (stock) -->
              <!-- ======================================================= -->
              <div class="space-y-1.5">
                <div class="flex items-center justify-between px-1">
                  <div class="flex items-center space-x-1.5 text-xs font-bold text-sky-400">
                    <span>📈</span>
                    <span>金融行情服务 (stock)</span>
                  </div>
                  <span class="text-[10px] font-mono text-zinc-500">系统全局</span>
                </div>

                <div
                  v-if="stockServer"
                  class="p-3 rounded-xl bg-sky-500/[0.04] border border-sky-500/20 space-y-2.5"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-bold text-xs text-zinc-100">{{ stockServer.name }}</span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium bg-sky-500/20 text-sky-300 border border-sky-500/30">
                        {{ stockServer.tools_count }} 工具
                      </span>
                    </div>

                    <!-- 开关 -->
                    <button
                      @click="toggleMcpServer(stockServer)"
                      :class="[
                        'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        stockServer.enabled ? 'bg-sky-500' : 'bg-zinc-700',
                      ]"
                      :title="stockServer.enabled ? '点击断开行情中台服务' : '点击挂载行情中台服务'"
                    >
                      <div
                        :class="[
                          'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                          stockServer.enabled ? 'translate-x-4' : 'translate-x-0',
                        ]"
                      ></div>
                    </button>
                  </div>

                  <div class="text-[10px] text-zinc-400 leading-relaxed">
                    {{ stockServer.description }}
                  </div>

                  <div class="flex items-center justify-between text-[10px] font-mono text-zinc-500 pt-1 border-t border-white/[0.04]">
                    <span class="text-sky-300/80">端点: /mcp/stock</span>
                    <button
                      @click="toggleMcpExpanded(stockServer.name)"
                      class="text-zinc-400 hover:text-sky-300 cursor-pointer flex items-center space-x-0.5"
                    >
                      <span>{{ expandedMcpMap[stockServer.name] ? '收起工具' : '查看工具列表' }}</span>
                      <span class="text-[9px]">{{ expandedMcpMap[stockServer.name] ? '▲' : '▼' }}</span>
                    </button>
                  </div>

                  <!-- 展开工具列表 -->
                  <div
                    v-if="expandedMcpMap[stockServer.name]"
                    class="pt-1.5 space-y-1.5 max-h-52 overflow-y-auto pr-1 border-t border-white/[0.04]"
                  >
                    <div
                      v-for="tool in stockServer.tools"
                      :key="tool.name"
                      class="p-2 rounded-lg bg-black/40 border border-white/[0.04] text-[10px] space-y-1"
                    >
                      <div class="flex items-center justify-between">
                        <span class="font-mono font-bold truncate flex-1 mr-1" :class="tool.enabled && stockServer.enabled ? 'text-sky-300' : 'text-zinc-500'">
                          {{ tool.name }}
                        </span>
                        <button
                          @click.stop="toggleMcpTool(stockServer, tool)"
                          :class="[
                            'w-7 h-4 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200 shrink-0',
                            tool.enabled ? 'bg-sky-500' : 'bg-zinc-700'
                          ]"
                          :title="tool.enabled ? '点击禁用该工具' : '点击启用该工具'"
                        >
                          <div
                            :class="[
                              'bg-white w-3 h-3 rounded-full shadow transform transition-transform duration-200',
                              tool.enabled ? 'translate-x-3' : 'translate-x-0'
                            ]"
                          ></div>
                        </button>
                      </div>
                      <div class="text-zinc-400 text-[9px] leading-tight truncate">{{ tool.description }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ======================================================= -->
              <!-- 2. 用户数据服务 (user) -->
              <!-- ======================================================= -->
              <div class="space-y-1.5 pt-1">
                <div class="flex items-center justify-between px-1">
                  <div class="flex items-center space-x-1.5 text-xs font-bold text-violet-400">
                    <span>👤</span>
                    <span>用户专属数据 (user)</span>
                  </div>
                  <span class="text-[10px] font-mono text-violet-400/80">JWT 身份隔离</span>
                </div>

                <div
                  v-if="userServer"
                  class="p-3 rounded-xl bg-violet-500/[0.04] border border-violet-500/20 space-y-2.5"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-bold text-xs text-zinc-100">{{ userServer.name }}</span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium bg-violet-500/20 text-violet-300 border border-violet-500/30">
                        {{ userServer.tools_count }} 工具
                      </span>
                    </div>

                    <!-- 开关 (用户可自主控制个人数据权限) -->
                    <button
                      @click="toggleMcpServer(userServer)"
                      :class="[
                        'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        userServer.enabled ? 'bg-violet-500' : 'bg-zinc-700',
                      ]"
                      :title="userServer.enabled ? '点击关闭个人数据访问权限' : '点击开启个人数据访问权限'"
                    >
                      <div
                        :class="[
                          'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                          userServer.enabled ? 'translate-x-4' : 'translate-x-0',
                        ]"
                      ></div>
                    </button>
                  </div>

                  <div class="text-[10px] text-zinc-400 leading-relaxed">
                    {{ userServer.description }}
                  </div>

                  <div class="flex items-center justify-between text-[10px] font-mono text-zinc-500 pt-1 border-t border-white/[0.04]">
                    <span class="text-violet-300/80">端点: /mcp/user</span>
                    <button
                      @click="toggleMcpExpanded(userServer.name)"
                      class="text-zinc-400 hover:text-violet-300 cursor-pointer flex items-center space-x-0.5"
                    >
                      <span>{{ expandedMcpMap[userServer.name] ? '收起工具' : '查看工具列表' }}</span>
                      <span class="text-[9px]">{{ expandedMcpMap[userServer.name] ? '▲' : '▼' }}</span>
                    </button>
                  </div>

                  <!-- 展开工具列表 -->
                  <div
                    v-if="expandedMcpMap[userServer.name]"
                    class="pt-1.5 space-y-1.5 max-h-52 overflow-y-auto pr-1 border-t border-white/[0.04]"
                  >
                    <div
                      v-for="tool in userServer.tools"
                      :key="tool.name"
                      class="p-2 rounded-lg bg-black/40 border border-white/[0.04] text-[10px] space-y-1"
                    >
                      <div class="flex items-center justify-between">
                        <span class="font-mono font-bold truncate flex-1 mr-1" :class="tool.enabled && userServer.enabled ? 'text-violet-300' : 'text-zinc-500'">
                          {{ tool.name }}
                        </span>
                        <button
                          @click.stop="toggleMcpTool(userServer, tool)"
                          :class="[
                            'w-7 h-4 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200 shrink-0',
                            tool.enabled ? 'bg-violet-500' : 'bg-zinc-700'
                          ]"
                          :title="tool.enabled ? '点击禁用该工具' : '点击启用该工具'"
                        >
                          <div
                            :class="[
                              'bg-white w-3 h-3 rounded-full shadow transform transition-transform duration-200',
                              tool.enabled ? 'translate-x-3' : 'translate-x-0'
                            ]"
                          ></div>
                        </button>
                      </div>
                      <div class="text-zinc-400 text-[9px] leading-tight truncate">{{ tool.description }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ======================================================= -->
              <!-- 3. 超管专属系统级运维工具调用 (admin) -->
              <!-- ======================================================= -->
              <div v-if="authStore.isAdmin" class="space-y-1.5 pt-1">
                <div class="flex items-center justify-between px-1">
                  <div class="flex items-center space-x-1.5 text-xs font-bold text-rose-400">
                    <span>🛠️</span>
                    <span>系统级运维工具调用</span>
                  </div>
                  <span class="text-[10px] font-mono text-rose-400 bg-rose-500/10 px-1.5 py-0.2 rounded border border-rose-500/20 font-bold">
                    超管专属
                  </span>
                </div>

                <div
                  v-if="adminServer"
                  class="p-3 rounded-xl bg-rose-500/[0.04] border border-rose-500/25 space-y-2.5 shadow-sm"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-bold text-xs text-rose-200">{{ adminServer.name }}</span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium bg-rose-500/20 text-rose-300 border border-rose-500/30">
                        {{ adminServer.tools_count }} 运维工具
                      </span>
                    </div>

                    <!-- 超管专用开关 -->
                    <button
                      @click="toggleMcpServer(adminServer)"
                      :class="[
                        'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        adminServer.enabled ? 'bg-rose-500' : 'bg-zinc-700',
                      ]"
                      :title="adminServer.enabled ? '点击禁用系统级运维工具调用' : '点击启用系统级运维工具调用'"
                    >
                      <div
                        :class="[
                          'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                          adminServer.enabled ? 'translate-x-4' : 'translate-x-0',
                        ]"
                      ></div>
                    </button>
                  </div>

                  <div class="text-[10px] text-zinc-400 leading-relaxed">
                    {{ adminServer.description }}
                  </div>

                  <div class="flex items-center justify-between text-[10px] font-mono text-zinc-500 pt-1 border-t border-white/[0.04]">
                    <span :class="adminServer.enabled ? 'text-rose-400 font-medium' : 'text-zinc-500'">
                      {{ adminServer.enabled ? '● 已授权 AI 助手调用' : '⏹ 已关闭工具屏蔽' }}
                    </span>
                    <button
                      @click="toggleMcpExpanded(adminServer.name)"
                      class="text-zinc-400 hover:text-rose-300 cursor-pointer flex items-center space-x-0.5"
                    >
                      <span>{{ expandedMcpMap[adminServer.name] ? '收起工具' : '查看运维工具' }}</span>
                      <span class="text-[9px]">{{ expandedMcpMap[adminServer.name] ? '▲' : '▼' }}</span>
                    </button>
                  </div>

                  <!-- 展开工具列表 -->
                  <div
                    v-if="expandedMcpMap[adminServer.name]"
                    class="pt-1.5 space-y-1.5 max-h-52 overflow-y-auto pr-1 border-t border-white/[0.04]"
                  >
                    <div
                      v-for="tool in adminServer.tools"
                      :key="tool.name"
                      class="p-2 rounded-lg bg-black/40 border border-rose-500/15 text-[10px] space-y-1"
                    >
                      <div class="flex items-center justify-between">
                        <span class="font-mono font-bold truncate flex-1 mr-1" :class="tool.enabled && adminServer.enabled ? 'text-rose-300' : 'text-zinc-500'">
                          {{ tool.name }}
                        </span>
                        <button
                          @click.stop="toggleMcpTool(adminServer, tool)"
                          :class="[
                            'w-7 h-4 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200 shrink-0',
                            tool.enabled ? 'bg-rose-500' : 'bg-zinc-700'
                          ]"
                          :title="tool.enabled ? '点击禁用该运维工具' : '点击启用该运维工具'"
                        >
                          <div
                            :class="[
                              'bg-white w-3 h-3 rounded-full shadow transform transition-transform duration-200',
                              tool.enabled ? 'translate-x-3' : 'translate-x-0'
                            ]"
                          ></div>
                        </button>
                      </div>
                      <div class="text-zinc-400 text-[9px] leading-tight truncate">{{ tool.description }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ======================================================= -->
              <!-- 4. 扩展与其他服务 (other / 之后别的加载的，排在最后) -->
              <!-- ======================================================= -->
              <div class="space-y-1.5 pt-1">
                <div class="flex items-center justify-between px-1">
                  <div class="flex items-center space-x-1.5 text-xs font-bold text-amber-400">
                    <span>🧩</span>
                    <span>扩展与第三方服务 (other)</span>
                  </div>
                  <span class="text-[10px] font-mono text-zinc-500">{{ customServers.length }} 个服务</span>
                </div>

                <div v-if="customServers.length > 0" class="space-y-2">
                  <div
                    v-for="s in customServers"
                    :key="s.name"
                    class="p-3 rounded-xl bg-amber-500/[0.04] border border-amber-500/20 space-y-2"
                  >
                    <div class="flex items-center justify-between">
                      <span class="font-bold text-xs text-zinc-100">{{ s.name }}</span>
                      <button
                        @click="toggleMcpServer(s)"
                        :class="[
                          'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                          s.enabled ? 'bg-amber-500' : 'bg-zinc-700',
                        ]"
                      >
                        <div
                          :class="[
                            'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                            s.enabled ? 'translate-x-4' : 'translate-x-0',
                          ]"
                        ></div>
                      </button>
                    </div>
                    <div class="text-[10px] text-zinc-400">{{ s.description || '自定义扩展 MCP' }}</div>
                  </div>
                </div>
                <div
                  v-else
                  class="p-2.5 rounded-xl border border-dashed border-white/[0.08] text-center text-[10px] text-zinc-500"
                >
                  暂无其他扩展服务，可在下方高级配置中心添加
                </div>
              </div>
            </div>

            <div class="pt-2.5 border-t border-white/[0.08]">
              <button
                @click="router.push('/agent-settings'); showMcpDrawer = false"
                class="w-full py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs font-medium cursor-pointer transition-colors"
              >
                ⚙️ 前往设置中心查看各服务详细能力白皮书
              </button>
            </div>
          </div>
        </transition>

        <!-- 2.2.3 右侧主对话流与原图卡片输出 (Main Chat & Cards) -->
        <div class="flex-1 flex flex-col h-full overflow-hidden bg-[#14151b]">
          <!-- 对话消息滚动区 (优化紧凑间距，消除用户提问与 Agent 回答间的过大空隙) -->
          <div
            ref="chatContainer"
            @click="onChatContainerClick"
            @mouseup="handleAssistantTextMouseUp"
            @scroll="handleChatScroll"
            class="flex-1 overflow-y-auto px-5 py-3 space-y-2.5 select-text text-xs leading-relaxed"
          >
            <!-- 新会话欢迎界面 (当当前会话为空时呈现极客量化欢迎词与快捷卡片) -->
            <div
              v-if="!codexStore.currentMessages || codexStore.currentMessages.length === 0"
              class="h-full flex flex-col items-center justify-center text-center p-6 space-y-5 max-w-xl mx-auto select-none"
            >
              <div class="space-y-2.5">
                <div class="w-12 h-12 mx-auto rounded-2xl bg-gradient-to-tr from-purple-600/30 via-amber-500/20 to-blue-500/20 border border-white/10 flex items-center justify-center text-2xl shadow-lg shadow-purple-500/10">
                  ⚡
                </div>
                <div>
                  <h3 class="text-sm font-bold text-white tracking-wide">
                    Quant Copilot · 全栈工程智能体
                  </h3>
                  <p class="text-[11px] text-zinc-400 mt-1">
                    当前挂载工程：<span class="text-amber-300 font-mono font-medium">{{ codexStore.activeProject?.name || '量化工作台' }}</span>
                    <span v-if="codexStore.activeProject?.path" class="text-zinc-500 font-mono text-[10px] ml-1">({{ codexStore.activeProject.path }})</span>
                  </p>
                </div>
                <div class="text-[11px] text-zinc-400 leading-relaxed max-w-md mx-auto">
                  你好！我是你的量化投研与策略工程助手。具备全市场行情研判、QuantCore 2.0 策略极速回测与全栈运维权限。你可以随心向我提问，或点击下方快捷卡片开启推演：
                </div>
              </div>

              <!-- 4 大常用快捷启动卡片 -->
              <div class="grid grid-cols-2 gap-2.5 w-full text-left">
                <button
                  @click="handleSendSuggestion('查询 510300 沪深300 ETF 的实时行情与最新估值分位数')"
                  class="p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] hover:border-amber-500/40 transition-all duration-200 cursor-pointer group"
                >
                  <div class="flex items-center space-x-1.5 text-amber-300 font-semibold text-xs mb-1">
                    <span>📊</span>
                    <span class="group-hover:text-amber-200">行情快照与估值</span>
                  </div>
                  <div class="text-[10px] text-zinc-400 line-clamp-2">
                    查询 510300 沪深300 ETF 实时行情与估值分位数
                  </div>
                </button>

                <button
                  @click="handleSendSuggestion('帮我基于双均线金叉死叉编写一个符合 QuantCore 2.0 规范的 Python 量化策略')"
                  class="p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] hover:border-purple-500/40 transition-all duration-200 cursor-pointer group"
                >
                  <div class="flex items-center space-x-1.5 text-purple-300 font-semibold text-xs mb-1">
                    <span>💡</span>
                    <span class="group-hover:text-purple-200">生成双均线策略</span>
                  </div>
                  <div class="text-[10px] text-zinc-400 line-clamp-2">
                    编写金叉买入死叉平仓的标准流式量化策略代码
                  </div>
                </button>

                <button
                  @click="handleSendSuggestion('在量化沙箱中极速运行一次 510300 的双均线策略回测，并给出夏普比率与最大回撤')"
                  class="p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] hover:border-emerald-500/40 transition-all duration-200 cursor-pointer group"
                >
                  <div class="flex items-center space-x-1.5 text-emerald-300 font-semibold text-xs mb-1">
                    <span>🧪</span>
                    <span class="group-hover:text-emerald-200">沙箱极速回测</span>
                  </div>
                  <div class="text-[10px] text-zinc-400 line-clamp-2">
                    毫秒级执行历史回测，评估年化收益与最大回撤
                  </div>
                </button>

                <button
                  @click="handleSendSuggestion('执行 admin_inspect_system_and_services，全面体检当前服务器系统资源与各微服务状态')"
                  class="p-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] hover:border-blue-500/40 transition-all duration-200 cursor-pointer group"
                >
                  <div class="flex items-center space-x-1.5 text-blue-300 font-semibold text-xs mb-1">
                    <span>🛠️</span>
                    <span class="group-hover:text-blue-200">微服务全景体检</span>
                  </div>
                  <div class="text-[10px] text-zinc-400 line-clamp-2">
                    诊断 CPU/内存、Docker 容器与 6 大微服务健康度
                  </div>
                </button>
              </div>
            </div>

            <!-- 消息流列表 -->
            <template v-else>
              <div
                v-for="msg in codexStore.currentMessages"
                :key="msg.id"
              >
              <!-- 用户消息 (Codex 风格：气泡圆润，鼠标悬停下方呈现时间、复制与修改重写) -->
              <div v-if="msg.role === 'user'" class="flex flex-col items-end group">
                <div class="max-w-[85%] px-3.5 py-1.5 rounded-2xl bg-white/[0.08] border border-white/[0.1] text-zinc-100 text-xs shadow-xs select-text leading-relaxed">
                  {{ msg.content }}
                </div>
                <!-- Codex 风格底部操作区：紧凑贴合，鼠标移动上去显示时间、复制、修改 -->
                <div class="h-3.5 mt-0.5 flex items-center space-x-1.5 text-[10px] text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity duration-150 select-none pr-1">
                  <span class="text-[10px] text-zinc-400 font-sans tracking-tight">{{ formatWeekdayTime(msg.timestamp) }}</span>
                  <!-- 复制按钮 -->
                  <button
                    @click="copyText(msg.content)"
                    class="p-0.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer"
                    title="复制提问内容"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                  </button>
                  <!-- 修改并在输入框重写按钮 -->
                  <button
                    @click="handleEditMessage(msg.content)"
                    class="p-0.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer"
                    title="在输入框中重写"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 20h9"></path>
                      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                    </svg>
                  </button>
                </div>
              </div>

              <!-- Assistant 消息 (紧凑布局，包含 agent-assistant-message 类供划词选中文本识别) -->
              <div v-else class="space-y-2 max-w-[95%] agent-assistant-message group">
                <!-- 1. 推理中思考阶段提示 (当正在流式推演且正文尚未吐出时展示) -->
                <div
                  v-if="msg.thought && codexStore.isStreaming && (!msg.content || !msg.content.trim())"
                  class="flex items-center space-x-2 text-xs text-purple-300/90 font-mono py-1.5 px-3 rounded-xl bg-purple-500/10 border border-purple-500/20 animate-pulse"
                >
                  <span class="w-2 h-2 rounded-full bg-purple-400"></span>
                  <span class="truncate">{{ msg.thought }}</span>
                </div>

                <!-- 2.0 权限确认卡片 (当检测到敏感操作需要授权时常驻展示) -->
                <div
                  v-if="msg.waitingApproval"
                  class="rounded-xl border border-amber-500/40 bg-amber-500/[0.08] p-3.5 space-y-2.5 shadow-lg shadow-amber-500/10 backdrop-blur-md animate-fadeIn"
                >
                  <div class="flex items-start justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="text-xl shrink-0">🛡️</span>
                      <div>
                        <div class="text-xs font-bold text-amber-200 flex items-center space-x-2">
                          <span>执行权限安全确认</span>
                          <span class="px-1.5 py-0.2 rounded text-[9px] bg-amber-500/20 text-amber-300 border border-amber-500/30 font-mono">
                            {{ codexStore.executionMode === 'confirm_all' ? '全量审批模式' : '敏感操作拦截' }}
                          </span>
                        </div>
                        <div class="text-[11px] text-zinc-300 mt-0.5">
                          {{ msg.waitingApproval.reason }}
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 命令或参数预览 -->
                  <div class="rounded-lg bg-black/60 border border-white/[0.08] p-2.5 font-mono text-xs text-zinc-200 space-y-1">
                    <div class="text-[10px] text-zinc-500 flex items-center justify-between">
                      <span>工具名称: {{ formatToolName(msg.waitingApproval.name) }} ({{ msg.waitingApproval.name }})</span>
                      <span class="text-amber-400/90 font-bold">● 等待授权</span>
                    </div>
                    <div class="text-emerald-400 font-semibold select-all break-all whitespace-pre-wrap pt-0.5">
                      {{ msg.waitingApproval.arguments?.command || msg.waitingApproval.arguments?.action || formatArgs(msg.waitingApproval.arguments) }}
                    </div>
                  </div>

                  <!-- 操作按钮栏 -->
                  <div class="flex items-center justify-end space-x-2 pt-0.5">
                    <button
                      @click="codexStore.rejectToolCall(msg, msg.waitingApproval.id)"
                      class="px-3 py-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
                    >
                      ✕ 拒绝执行
                    </button>
                    <button
                      @click="codexStore.approveToolCall(msg, msg.waitingApproval.id)"
                      class="px-4 py-1.5 rounded-lg bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white font-bold text-xs shadow-md shadow-amber-500/25 cursor-pointer transition-all flex items-center space-x-1.5"
                    >
                      <span>✓</span>
                      <span>授权并执行指令</span>
                    </button>
                  </div>
                </div>

                <!-- 循环卫生守卫警示 (Guard Alert Banner · 借鉴 DSH) -->
                <div
                  v-if="msg.guardAlerts && msg.guardAlerts.length > 0"
                  class="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/25 text-amber-200 text-xs space-y-1 shadow-xs"
                >
                  <div class="flex items-center space-x-1.5 font-medium text-amber-300">
                    <span>🛡️</span>
                    <span>循环卫生守卫已介入 (Repeat Guard)</span>
                  </div>
                  <div class="text-[11px] text-amber-200/80 leading-relaxed">
                    检测到模型发起重复工具调用，守卫已自动注入防死循环提示并引导模型调整策略。
                  </div>
                </div>

                <!-- 2. 简约风工具链展示 (Minimalist Toolchain Accordion) -->
                <div
                  v-if="msg.toolCalls && msg.toolCalls.length > 0"
                  class="rounded-xl border border-white/[0.08] bg-white/[0.02] overflow-hidden text-xs transition-all shadow-xs"
                >
                  <!-- 顶栏摘要条 (点击展开/折叠) -->
                  <div
                    @click="toggleToolchain(msg.id)"
                    class="px-3 py-2 flex items-center justify-between cursor-pointer hover:bg-white/[0.04] transition-colors select-none group"
                  >
                    <div class="flex items-center space-x-2 text-zinc-300">
                      <!-- 运行中 vs 完成状态 -->
                      <span v-if="hasRunningTools(msg)" class="inline-flex items-center text-amber-400 text-xs font-medium">
                        <svg class="animate-spin w-3.5 h-3.5 mr-1.5" fill="none" viewBox="0 0 24 24">
                          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                        </svg>
                        <span>工具链推演中 ({{ countCompletedTools(msg) }}/{{ msg.toolCalls.length }})</span>
                      </span>
                      <span v-else class="flex items-center space-x-1.5 text-zinc-400 text-xs">
                        <span class="text-emerald-400 text-xs font-bold">✓</span>
                        <span class="font-medium text-zinc-300">已调用 {{ msg.toolCalls.length }} 个投研工具</span>
                      </span>

                      <!-- 简约工具标签预览 (如: [行情快照] [估值分析]) -->
                      <div class="hidden sm:flex items-center space-x-1 pl-1.5">
                        <span
                          v-for="tc in msg.toolCalls.slice(0, 3)"
                          :key="tc.id"
                          class="px-1.5 py-0.2 rounded text-[10px] font-mono bg-white/[0.05] text-zinc-400 border border-white/[0.06]"
                        >
                          {{ formatToolName(tc.name) }}
                        </span>
                        <span v-if="msg.toolCalls.length > 3" class="text-[10px] text-zinc-500 font-mono">
                          +{{ msg.toolCalls.length - 3 }}
                        </span>
                      </div>
                    </div>

                    <!-- 右侧折叠指示符与复制按钮 -->
                    <div class="flex items-center space-x-2 text-zinc-400 text-[11px]">
                      <!-- 一键复制全部工具链 -->
                      <button
                        @click.stop="copyToolchain(msg.toolCalls)"
                        class="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-white hover:bg-white/[0.08] transition-colors flex items-center space-x-1 cursor-pointer"
                        title="一键复制全部工具调用参数与执行结果"
                      >
                        <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                        </svg>
                        <span>复制工具链</span>
                      </button>

                      <div class="flex items-center space-x-1 group-hover:text-zinc-300 transition-colors">
                        <span>{{ isToolchainExpanded(msg) ? '收起详情' : '展开详情' }}</span>
                        <svg
                          :class="['w-3.5 h-3.5 transition-transform duration-200', isToolchainExpanded(msg) ? 'rotate-180' : '']"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                        </svg>
                      </div>
                    </div>
                  </div>

                  <!-- 展开的工具链调用列表 (简约极客风) -->
                  <div
                    v-show="isToolchainExpanded(msg)"
                    class="px-3 pb-2.5 pt-1 border-t border-white/[0.04] space-y-2 bg-black/25"
                  >
                    <div
                      v-for="(tc, tcIdx) in msg.toolCalls"
                      :key="tc.id || tcIdx"
                      class="p-2 rounded-lg bg-white/[0.02] border border-white/[0.05] space-y-1.5 transition-colors"
                    >
                      <!-- 工具单项标题行 -->
                      <div class="flex items-center justify-between text-[11px]">
                        <div class="flex items-center space-x-1.5 font-mono">
                          <span class="text-sm leading-none">{{ getToolIcon(tc.name) }}</span>
                          <span class="font-semibold text-zinc-200">{{ formatToolName(tc.name) }}</span>
                          <span class="text-zinc-500 text-[10px]">({{ tc.name }})</span>
                        </div>

                        <!-- 单项状态标识与操作 -->
                        <div class="flex items-center space-x-1.5">
                          <span
                            v-if="tc.status === 'calling'"
                            class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-amber-500/15 text-amber-300 border border-amber-500/25 animate-pulse flex items-center space-x-1"
                          >
                            <span>●</span>
                            <span>调用中...</span>
                          </span>
                          <span
                            v-else-if="tc.status === 'waiting_approval'"
                            class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-amber-500/25 text-amber-300 border border-amber-500/40 animate-pulse flex items-center space-x-1"
                          >
                            <span>🛡️</span>
                            <span>待授权</span>
                          </span>
                          <span
                            v-else-if="tc.status === 'rejected'"
                            class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-zinc-800 text-zinc-400 border border-zinc-700/50"
                          >
                            ✕ 已拒绝
                          </span>
                          <span
                            v-else-if="tc.status === 'done'"
                            class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-emerald-500/15 text-emerald-300 border border-emerald-500/25"
                          >
                            ✓ 完成
                          </span>
                          <span
                            v-else
                            class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-rose-500/15 text-rose-300 border border-rose-500/25"
                          >
                            ✕ 异常
                          </span>

                          <!-- 复制单项工具调用参数与结果 -->
                          <button
                            @click.stop="copySingleTool(tc)"
                            class="p-0.5 rounded text-zinc-400 hover:text-white hover:bg-white/[0.08] transition-colors cursor-pointer"
                            title="复制该工具调用详情"
                          >
                            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                          </button>
                        </div>
                      </div>

                      <!-- 工具入参参数 (简约单行) -->
                      <div
                        v-if="tc.arguments && Object.keys(tc.arguments).length > 0"
                        class="text-[10px] font-mono text-zinc-400 bg-black/40 px-2 py-1 rounded border border-white/[0.03]"
                      >
                        <span class="text-zinc-500">参数: </span>
                        <span class="text-zinc-300">{{ formatArgs(tc.arguments) }}</span>
                      </div>

                      <!-- 工具实时输出 / 返回结果 (支持实时 Live Streaming 日志) -->
                      <div v-if="tc.liveOutput || tc.outputPreview" class="pt-0.5">
                        <div
                          @click="togglePreview(tc.id)"
                          class="text-[10px] text-zinc-400 hover:text-zinc-200 cursor-pointer flex items-center justify-between select-none py-0.5"
                        >
                          <div class="flex items-center space-x-1">
                            <span>{{ (isPreviewExpanded(tc.id) || tc.status === 'calling') ? '▾' : '▸' }}</span>
                            <span :class="{'text-amber-300 font-semibold': tc.status === 'calling'}">
                              {{ tc.status === 'calling' ? '实时执行日志 (Streaming)' : '查看执行输出结果' }}
                            </span>
                            <span v-if="tc.status === 'calling'" class="inline-flex w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping ml-1"></span>
                          </div>
                          <span v-if="tc.liveOutput" class="text-[9px] font-mono text-zinc-500">
                            {{ tc.liveOutput.split('\n').filter(Boolean).length }} 行输出
                          </span>
                        </div>
                        <div
                          v-show="isPreviewExpanded(tc.id) || tc.status === 'calling'"
                          class="mt-1 p-2.5 rounded-lg bg-[#0b0c10] border border-white/[0.08] text-[10px] font-mono text-emerald-300/90 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap leading-relaxed select-text shadow-inner"
                        >
                          <div class="text-zinc-500 pb-1 border-b border-white/[0.04] flex items-center justify-between mb-1.5 text-[9px] select-none">
                            <span>&gt;_ 终端输出 (STDOUT/STDERR)</span>
                            <div class="flex items-center space-x-2">
                              <span v-if="tc.status === 'calling'" class="text-amber-400 animate-pulse font-bold">● LIVE</span>
                              <button
                                @click.stop="copyText(tc.liveOutput || tc.outputPreview || '', '📋 终端输出已复制')"
                                class="hover:text-zinc-200 transition-colors cursor-pointer flex items-center space-x-0.5 px-1.5 py-0.2 rounded hover:bg-white/[0.08]"
                                title="复制终端完整输出"
                              >
                                <span>复制输出</span>
                              </button>
                            </div>
                          </div>
                          <span>{{ tc.liveOutput || tc.outputPreview }}</span>
                          <span v-if="tc.status === 'calling'" class="inline-block w-1.5 h-3 bg-emerald-400 ml-0.5 animate-pulse align-middle"></span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 3. 正文内容 (Markdown 渲染 + 语法高亮) -->
                <div
                  v-if="msg.content"
                  class="agent-markdown text-zinc-200 leading-relaxed"
                  v-html="renderMarkdown(msg.content)"
                ></div>

                <!-- 4. 独立纯文本/代码卡片 (Card Container，带语法高亮与操作栏) -->
                <div
                  v-for="(card, cIdx) in msg.cards"
                  :key="cIdx"
                  class="rounded-xl border border-white/[0.1] bg-[#1a1b22] overflow-hidden shadow-sm"
                >
                  <div class="px-3 py-1.5 bg-white/[0.03] border-b border-white/[0.06] flex items-center justify-between text-[11px]">
                    <div class="flex items-center space-x-1.5 text-zinc-300 font-mono">
                      <span class="text-purple-400">&lt;/&gt;</span>
                      <span class="font-medium">{{ card.title || '纯文本' }}</span>
                    </div>
                    <!-- 一键插入工作台与复制代码 -->
                    <div class="flex items-center space-x-2.5 text-zinc-400">
                      <button
                        @click="applyCodeToEditor(card.content)"
                        class="hover:text-amber-400 transition-colors cursor-pointer flex items-center space-x-1 text-[10px]"
                        title="一键插入到策略代码工作台"
                      >
                        <span>⚡ 载入工作台</span>
                      </button>
                      <button
                        @click="copyText(card.content)"
                        class="hover:text-white transition-colors cursor-pointer flex items-center space-x-1 text-[10px]"
                        title="复制代码"
                      >
                        <span>📋 复制</span>
                      </button>
                    </div>
                  </div>
                  <div
                    class="p-3 text-[11px] font-mono text-zinc-200 overflow-x-auto whitespace-pre leading-relaxed bg-[#0d0e14]"
                    v-html="highlightCodeSnippet(card.content, card.language)"
                  ></div>
                </div>

                <!-- 消息操作条 (Codex 风格：紧凑贴合，鼠标悬停在消息块时展示时间与复制) -->
                <div class="h-4 mt-1 flex items-center space-x-2 text-[10px] text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity duration-150 select-none">
                  <span class="text-[10px] font-sans text-zinc-400 tracking-tight">{{ formatWeekdayTime(msg.timestamp) }}</span>

                  <!-- 若消息包含工具链，提供一键复制完整记录（含工具链与输出） -->
                  <button
                    v-if="msg.toolCalls && msg.toolCalls.length > 0"
                    @click="copyFullMessage(msg)"
                    class="p-0.5 px-1.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer flex items-center space-x-1 text-purple-300 hover:text-purple-200"
                    title="复制完整推演记录（包含工具链步骤、命令输出与结论）"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <span>复制完整记录</span>
                  </button>

                  <!-- 复制正文内容按钮 -->
                  <button
                    v-if="msg.content && msg.content.trim()"
                    @click="copyText(msg.content, '📋 正文已复制到剪贴板')"
                    class="p-0.5 px-1.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer flex items-center space-x-1"
                    :title="(msg.toolCalls && msg.toolCalls.length > 0) ? '仅复制分析正文' : '复制回答内容'"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <span>{{ (msg.toolCalls && msg.toolCalls.length > 0) ? '仅复制正文' : '复制' }}</span>
                  </button>

                  <!-- 若仅有工具链而无正文，提供直接复制工具链按钮 -->
                  <button
                    v-else-if="msg.toolCalls && msg.toolCalls.length > 0"
                    @click="copyToolchain(msg.toolCalls)"
                    class="p-0.5 px-1.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer flex items-center space-x-1"
                    title="复制工具链执行结果"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <span>复制工具链</span>
                  </button>
                </div>
              </div>
            </div>
            </template>

            <!-- 推演动态提示 -->
            <div v-if="codexStore.isStreaming && !activeRunningTool" class="flex items-center space-x-2 text-xs text-amber-400 font-mono py-1">
              <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping"></span>
              <span>Alpha 正在结合工程上下文深度推演...</span>
            </div>
          </div>

          <!-- 常驻执行状态驻守条 (当正在执行命令或流式推演时常驻吸附显示) -->
          <div
            v-if="codexStore.isStreaming"
            class="px-3.5 py-2 bg-gradient-to-r from-purple-950/70 via-[#181924] to-[#12131a] border-t border-purple-500/25 flex items-center justify-between text-xs text-zinc-300 select-none shrink-0 shadow-lg shadow-black/40 backdrop-blur-md"
          >
            <div class="flex items-center space-x-2.5 truncate min-w-0 flex-1">
              <div class="relative flex items-center justify-center w-3 h-3 shrink-0">
                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2 w-2 bg-amber-400"></span>
              </div>
              <div class="flex items-center space-x-2 truncate min-w-0">
                <span class="font-bold text-[11px] text-amber-300 shrink-0">
                  {{ activeRunningTool ? '终端指令执行中' : 'AI 深度推演中' }}
                </span>
                <span v-if="activeRunningTool" class="text-zinc-400 font-mono text-[11px] truncate">
                  {{ formatToolName(activeRunningTool.name) }}: <span class="text-zinc-200">{{ activeRunningTool.arguments?.command || activeRunningTool.arguments?.action || activeRunningTool.name }}</span>
                </span>
                <span v-else-if="latestAssistantMessage?.thought" class="text-zinc-400 text-[11px] truncate">
                  {{ latestAssistantMessage.thought }}
                </span>
              </div>
            </div>

            <div class="flex items-center space-x-2 shrink-0 pl-3">
              <!-- 实时执行计时器 -->
              <span class="font-mono text-[11px] px-2 py-0.5 rounded-md bg-white/[0.06] text-purple-200 border border-purple-500/25 flex items-center space-x-1">
                <span>⏱️</span>
                <span>{{ formatElapsed(streamingElapsed) }}</span>
              </span>

              <!-- 手动中断按钮 -->
              <button
                @click="codexStore.stopStreaming()"
                class="px-2.5 py-1 rounded-md bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 text-[10px] font-medium cursor-pointer transition-colors flex items-center space-x-1"
                title="中断当前执行"
              >
                <span>⏹</span>
                <span>中断</span>
              </button>
            </div>
          </div>

          <!-- 2.2.4 底部智能提问底座 (去除了未实现的语音与附件，专注核心提问与权限 Tooltip) -->
          <div class="p-3 shrink-0 bg-[#14151b]/95 border-t border-white/[0.06]">
            <div class="rounded-2xl bg-[#1d1e26] border border-white/[0.12] p-2.5 shadow-xl transition-all focus-within:border-purple-500/50">
              <textarea
                ref="textareaRef"
                v-model="inputPrompt"
                @compositionstart="onCompositionStart"
                @compositionend="onCompositionEnd"
                @keydown="onTextareaKeydown"
                placeholder="随心输入..."
                rows="2"
                class="w-full bg-transparent resize-none border-none outline-hidden text-xs text-zinc-100 placeholder-zinc-500 px-1.5 leading-relaxed"
              ></textarea>

              <div class="flex items-center justify-between pt-1.5 px-0.5">
                <!-- 左侧：权限访问控制 (点击弹出 Tooltip 菜单切换) -->
                <div class="relative" ref="permissionTooltipRef">
                  <button
                    @click.stop="showPermissionTooltip = !showPermissionTooltip"
                    :class="[
                      'flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold cursor-pointer transition-all border shadow-xs',
                      codexStore.executionMode === 'auto'
                        ? 'bg-amber-500/15 text-amber-300 border-amber-500/35 hover:bg-amber-500/25'
                        : codexStore.executionMode === 'confirm_sensitive'
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/35 hover:bg-emerald-500/25'
                        : 'bg-rose-500/15 text-rose-300 border-rose-500/35 hover:bg-rose-500/25',
                    ]"
                    title="点击展开执行权限安全模式"
                  >
                    <span>{{ codexStore.executionMode === 'auto' ? '⚡' : codexStore.executionMode === 'confirm_sensitive' ? '🛡️' : '🔒' }}</span>
                    <span>{{ codexStore.executionMode === 'auto' ? '完全访问' : codexStore.executionMode === 'confirm_sensitive' ? '敏感确认' : '全量审批' }}</span>
                    <span class="text-[9px] opacity-70">▾</span>
                  </button>

                  <!-- 权限切换 Tooltip 浮动菜单 -->
                  <transition name="popover">
                    <div
                      v-if="showPermissionTooltip"
                      class="absolute bottom-full mb-2 left-0 w-64 rounded-2xl bg-[#1c1d25] border border-white/[0.14] shadow-2xl p-2 z-50 text-xs space-y-1 backdrop-blur-xl"
                    >
                      <div class="px-2 py-1 text-[10px] font-bold text-zinc-400 uppercase tracking-wider border-b border-white/[0.06] flex items-center justify-between">
                        <span>执行权限模式</span>
                        <span class="text-[9px] text-zinc-500 font-normal">点击即时切换</span>
                      </div>

                      <!-- 模式 1: 完全访问 -->
                      <button
                        @click.stop="selectPermissionMode('auto')"
                        :class="[
                          'w-full text-left p-2 rounded-xl transition-all cursor-pointer flex items-start space-x-2',
                          codexStore.executionMode === 'auto'
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                            : 'hover:bg-white/[0.06] text-zinc-300',
                        ]"
                      >
                        <span class="text-sm">⚡</span>
                        <div class="flex-1">
                          <div class="flex items-center justify-between font-bold text-xs">
                            <span>完全访问 (Auto)</span>
                            <span v-if="codexStore.executionMode === 'auto'" class="text-amber-400 text-xs font-mono">✓</span>
                          </div>
                          <div class="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                            自主推演与全速工具执行，无需人工授权确认。
                          </div>
                        </div>
                      </button>

                      <!-- 模式 2: 敏感确认 -->
                      <button
                        @click.stop="selectPermissionMode('confirm_sensitive')"
                        :class="[
                          'w-full text-left p-2 rounded-xl transition-all cursor-pointer flex items-start space-x-2',
                          codexStore.executionMode === 'confirm_sensitive'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : 'hover:bg-white/[0.06] text-zinc-300',
                        ]"
                      >
                        <span class="text-sm">🛡️</span>
                        <div class="flex-1">
                          <div class="flex items-center justify-between font-bold text-xs">
                            <span>敏感写操作确认 (推荐)</span>
                            <span v-if="codexStore.executionMode === 'confirm_sensitive'" class="text-emerald-400 text-xs font-mono">✓</span>
                          </div>
                          <div class="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                            源码修改、Shell 运维与 Docker 治理前暂停等待人工批准。
                          </div>
                        </div>
                      </button>

                      <!-- 模式 3: 全量审批 -->
                      <button
                        @click.stop="selectPermissionMode('confirm_all')"
                        :class="[
                          'w-full text-left p-2 rounded-xl transition-all cursor-pointer flex items-start space-x-2',
                          codexStore.executionMode === 'confirm_all'
                            ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                            : 'hover:bg-white/[0.06] text-zinc-300',
                        ]"
                      >
                        <span class="text-sm">🔒</span>
                        <div class="flex-1">
                          <div class="flex items-center justify-between font-bold text-xs">
                            <span>全量严格审批 (Strict)</span>
                            <span v-if="codexStore.executionMode === 'confirm_all'" class="text-rose-400 text-xs font-mono">✓</span>
                          </div>
                          <div class="text-[10px] text-zinc-400 mt-0.5 leading-snug">
                            包括行情读取在内的所有工具执行前均强制人工审核。
                          </div>
                        </div>
                      </button>
                    </div>
                  </transition>
                </div>

                <!-- 右侧：模型与思考程度选择器 (点击弹出 Tooltip 菜单切换) + 发送按钮 -->
                <div class="flex items-center space-x-2">
                  <!-- 模型与思考深度 Popover 触发胶囊 -->
                  <div class="relative" ref="modelPopoverRef">
                    <button
                      @click.stop="showModelPopover = !showModelPopover"
                      class="flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.1] text-zinc-300 hover:text-white transition-all cursor-pointer shadow-xs"
                      title="点击切换推理模型 (支持 AGY 与标准双矩阵)"
                    >
                      <span class="text-[11px]">{{ currentThinkingOption.icon }}</span>
                      <span
                        class="px-1 py-0.1 rounded text-[8px] font-mono font-bold"
                        :class="currentModelItem?.isAgy ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'"
                      >
                        {{ currentModelItem?.isAgy ? 'AGY' : '标准' }}
                      </span>
                      <span class="font-mono text-zinc-200 font-semibold">{{ currentModelItem?.name }}</span>
                      <span class="px-1 py-0.1 rounded text-[8px] font-mono bg-purple-500/20 text-purple-300 border border-purple-500/30">
                        {{ currentThinkingOption.badge }}
                      </span>
                      <span class="text-[8px] opacity-70">▾</span>
                    </button>

                    <!-- 模型与思考深度 Tooltip 浮动菜单 -->
                    <transition name="popover">
                      <div
                        v-if="showModelPopover"
                        class="absolute bottom-full mb-2 right-0 w-88 rounded-2xl bg-[#1c1d25] border border-white/[0.14] shadow-2xl p-3 z-50 text-xs space-y-3 backdrop-blur-2xl"
                      >
                        <!-- 模块 1: 推理模型 -->
                        <div class="space-y-2">
                          <div class="flex items-center justify-between pb-1 border-b border-white/[0.06]">
                            <span class="text-[10px] font-bold text-zinc-300 uppercase tracking-wider flex items-center space-x-1">
                              <span>🤖</span>
                              <span>推理模型矩阵 (AGY & 标准)</span>
                            </span>
                            <span
                              class="text-[9px] font-mono px-1.5 py-0.2 rounded border"
                              :class="currentModelItem?.isAgy ? 'bg-amber-500/10 text-amber-400 border-amber-500/30' : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'"
                            >
                              {{ currentModelItem?.isAgy ? '⚡ AGY 预热池' : '🌐 标准直连' }}
                            </span>
                          </div>

                          <!-- 专区筛选切换 Tab: 全部 / AGY 预热池 / 标准直连 -->
                          <div class="flex items-center p-0.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-[10px]">
                            <button
                              @click.stop="modelFilterTab = 'all'"
                              :class="modelFilterTab === 'all' ? 'bg-white/10 text-white font-bold shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
                              class="flex-1 py-0.8 rounded-md transition-all cursor-pointer text-center"
                            >
                              全部 ({{ AVAILABLE_MODELS.length }})
                            </button>
                            <button
                              @click.stop="modelFilterTab = 'agy'"
                              :class="modelFilterTab === 'agy' ? 'bg-amber-500/20 text-amber-300 font-bold shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
                              class="flex-1 py-0.8 rounded-md transition-all cursor-pointer text-center flex items-center justify-center space-x-1"
                            >
                              <span>⚡ AGY ({{ AVAILABLE_MODELS.filter(m => m.isAgy).length }})</span>
                            </button>
                            <button
                              @click.stop="modelFilterTab = 'standard'"
                              :class="modelFilterTab === 'standard' ? 'bg-emerald-500/20 text-emerald-300 font-bold shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
                              class="flex-1 py-0.8 rounded-md transition-all cursor-pointer text-center flex items-center justify-center space-x-1"
                            >
                              <span>🌐 标准 ({{ AVAILABLE_MODELS.filter(m => !m.isAgy).length }})</span>
                            </button>
                          </div>

                          <div class="space-y-1 max-h-52 overflow-y-auto pr-0.5">
                            <button
                              v-for="m in filteredModelList"
                              :key="m.id"
                              @click.stop="selectModel(m.id)"
                              :class="[
                                'w-full text-left p-2 rounded-xl transition-all cursor-pointer flex items-start space-x-2 border',
                                codexStore.aiModel === m.id
                                  ? (m.isAgy ? 'bg-amber-500/15 border-amber-500/40 text-amber-100 shadow-xs' : 'bg-emerald-500/15 border-emerald-500/40 text-emerald-100 shadow-xs')
                                  : 'bg-white/[0.02] border-transparent hover:bg-white/[0.06] text-zinc-300',
                              ]"
                            >
                              <div class="flex-1 min-w-0">
                                <div class="flex items-center justify-between">
                                  <div class="flex items-center space-x-1.5">
                                    <span class="font-bold text-xs text-white">{{ m.name }}</span>
                                    <span
                                      :class="[
                                        'px-1.5 py-0.2 rounded text-[9px] font-mono',
                                        m.isDefault ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold' : (m.isAgy ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold' : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold'),
                                      ]"
                                    >
                                      {{ m.tag }}
                                    </span>
                                  </div>
                                  <span v-if="codexStore.aiModel === m.id" class="text-amber-400 font-bold text-xs">✓</span>
                                </div>
                                <div class="text-[10px] text-zinc-400 mt-0.5 truncate leading-tight">
                                  {{ m.description }}
                                </div>
                              </div>
                            </button>
                          </div>
                        </div>

                        <!-- 模块 2: 思考程度 (Reasoning Effort) -->
                        <div class="space-y-1.5 pt-1 border-t border-white/[0.06]">
                          <div class="flex items-center justify-between pb-1">
                            <span class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider flex items-center space-x-1">
                              <span>🧠</span>
                              <span>思考程度 (Reasoning Depth)</span>
                            </span>
                            <span class="text-[9px] text-zinc-500">点击切换深度</span>
                          </div>

                          <div class="grid grid-cols-2 gap-1.5">
                            <button
                              v-for="opt in THINKING_LEVEL_OPTIONS"
                              :key="opt.level"
                              @click.stop="selectThinkingLevel(opt.level)"
                              :class="[
                                'text-left p-1.5 rounded-xl transition-all cursor-pointer border flex flex-col justify-between',
                                codexStore.thinkingLevel === opt.level
                                  ? 'bg-amber-500/20 border-amber-500/40 text-amber-200'
                                  : 'bg-white/[0.02] border-white/[0.04] hover:bg-white/[0.06] text-zinc-400',
                              ]"
                              :title="opt.description"
                            >
                              <div class="flex items-center justify-between">
                                <span class="text-xs">{{ opt.icon }}</span>
                                <span v-if="codexStore.thinkingLevel === opt.level" class="text-amber-400 text-[10px] font-bold">✓</span>
                              </div>
                              <div class="mt-1">
                                <div class="text-[11px] font-semibold text-zinc-200">{{ opt.label }}</div>
                                <div class="text-[9px] text-zinc-400 leading-tight">{{ opt.badge }}</div>
                              </div>
                            </button>
                          </div>
                        </div>
                      </div>
                    </transition>
                  </div>

                  <button
                    v-if="!codexStore.isStreaming"
                    @click="handleSend"
                    :disabled="!inputPrompt.trim()"
                    class="w-6 h-6 rounded-full bg-white text-black hover:bg-zinc-200 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-xs font-bold transition-all cursor-pointer shadow-sm"
                  >
                    ↑
                  </button>
                  <button
                    v-else
                    @click="codexStore.stopStreaming"
                    class="w-6 h-6 rounded-full bg-amber-500 text-black hover:bg-amber-400 flex items-center justify-center text-[10px] font-bold transition-all cursor-pointer shadow-sm"
                    title="停止生成 (Esc)"
                  >
                    ■
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 2.3 独立高阶工程模态框 (统一全局层级治理 · 保证在最顶层) -->
      <ProjectModal
        v-model:show="showProjectModal"
        @mounted="scrollToBottom"
      />

      <!-- 四个角拉伸调整尺寸手柄 (Resize Handles) -->
      <div
        @mousedown="onCornerMouseDown('nw', $event)"
        class="absolute top-0 left-0 w-3.5 h-3.5 cursor-nwse-resize z-50"
      ></div>
      <div
        @mousedown="onCornerMouseDown('ne', $event)"
        class="absolute top-0 right-0 w-3.5 h-3.5 cursor-nesw-resize z-50"
      ></div>
      <div
        @mousedown="onCornerMouseDown('sw', $event)"
        class="absolute bottom-0 left-0 w-3.5 h-3.5 cursor-nesw-resize z-50"
      ></div>
      <div
        @mousedown="onCornerMouseDown('se', $event)"
        class="absolute bottom-0 right-0 w-3.5 h-3.5 cursor-nwse-resize z-50"
      ></div>
    </div>

    <!-- 3. 选中文本弹出气泡快捷提问 (Ask 阿尔法 Tooltip) -->
    <transition name="popover">
      <div
        v-if="selectionTooltip.visible"
        id="ask-alpha-selection-tooltip"
        :style="{
          position: 'fixed',
          left: `${selectionTooltip.x}px`,
          top: `${selectionTooltip.y}px`,
          transform: 'translate(-50%, -100%)',
          zIndex: 100000,
        }"
        @mousedown.stop
        @click.stop="handleAskAlpha"
        class="flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-[#181924]/95 hover:bg-purple-600 text-white border border-purple-400/40 shadow-2xl shadow-purple-950/70 cursor-pointer backdrop-blur-2xl transition-all duration-150 hover:scale-105 select-none group"
        title="引用选中内容向阿尔法提问"
      >
        <span class="text-xs group-hover:rotate-12 transition-transform">🤖</span>
        <span class="text-xs font-semibold tracking-wide text-zinc-100 group-hover:text-white">Ask 阿尔法</span>
        <span class="text-[10px] text-purple-300 group-hover:text-white font-mono opacity-80">↵</span>
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.2s ease-out;
}

.slide-fade-enter-from,
.slide-fade-leave-to {
  transform: translateX(-10px);
  opacity: 0;
}

.popover-enter-active,
.popover-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.popover-enter-from,
.popover-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}

::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 9999px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
