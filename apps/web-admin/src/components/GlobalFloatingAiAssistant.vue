<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { renderMarkdown, highlightCodeSnippet } from '@/utils/markdown'
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
  AVAILABLE_MODELS,
  THINKING_LEVEL_OPTIONS,
} from '@/stores/codexWorkspace'

const router = useRouter()
const aiStore = useAiStore()
const authStore = useAuthStore()
const strategyStore = useStrategyStore()
const codexStore = useCodexWorkspaceStore()

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
const expandedProjects = ref<Record<string, boolean>>({})

// 当前激活模型与思考程度
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

function copyText(code: string) {
  navigator.clipboard.writeText(code)
  showToast('📋 已复制到剪贴板')
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
  // 用户手动操作过一次，以用户选择为准（防闪烁）
  if (expandedToolchains.value[msg.id] !== undefined) {
    return expandedToolchains.value[msg.id]
  }
  // 未手动操作时：有工具运行中 → 自动展开一次（并记录）
  if (hasRunningTools(msg) && !autoExpandedToolchains.value.has(msg.id)) {
    autoExpandedToolchains.value.add(msg.id)
    expandedToolchains.value[msg.id] = true
    return true
  }
  // 默认收起
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

// 事件代理：捕获 Markdown 代码块内的“复制”与“载入工作台”按钮点击
function onChatContainerClick(e: MouseEvent) {
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
  if (!target.closest('#ask-alpha-selection-tooltip')) {
    selectionTooltip.value.visible = false
  }
}

// -------------------------------------------------------------
// 挂载与导入工程项目模态框 (Server File Tree & Client Upload)
// -------------------------------------------------------------
const showProjectModal = ref(false)
const projectModalTab = ref<'server' | 'upload'>('server')

// Tab 1: 服务端工程状态 (方案 A: 部署机智能探测 + 目录树挂载)
const serverSubTab = ref<'auto' | 'tree'>('auto')
const discoveredProjects = ref<DiscoveredProjectItem[]>([])
const loadingDiscovered = ref(false)
const fsLoading = ref(false)
const fsResult = ref<FileSystemBrowseResult | null>(null)
const selectedServerFolder = ref<string>('')
const serverProjectName = ref<string>('')
const serverHostType = ref<'remote' | 'local'>('remote')
const serverMachineName = ref<string>('Ubuntu 部署机')
const showHiddenFiles = ref(false)
const customPathInput = ref('')

// Tab 2: 访问机客户端上传状态
const uploadFiles = ref<File[]>([])
const uploadZipFile = ref<File | null>(null)
const uploadProjectName = ref('')
const uploadDestinationDir = ref('')
const uploadHostType = ref<'remote' | 'local'>('remote')
const uploadMachineName = ref('当前部署机节点 (Ubuntu/Linux)')
const isUploading = ref(false)
const uploadFolderInputRef = ref<HTMLInputElement | null>(null)
const uploadZipInputRef = ref<HTMLInputElement | null>(null)

async function openProjectModal() {
  showProjectModal.value = true
  // 默认启动智能工程探测 (零路径门槛)
  loadDiscoveredProjects()
  if (!fsResult.value) {
    loadServerFs()
  }
}

async function loadDiscoveredProjects() {
  try {
    loadingDiscovered.value = true
    const list = await codexStore.discoverSystemProjects()
    discoveredProjects.value = list
  } catch (err: any) {
    console.error('Failed to discover projects:', err)
  } finally {
    loadingDiscovered.value = false
  }
}

async function handleMountDiscoveredProject(proj: DiscoveredProjectItem) {
  const ok = await codexStore.createProject({
    name: proj.name,
    host_type: serverHostType.value,
    path: proj.path,
    machine_name: serverMachineName.value,
    description: `自动探测挂载: ${proj.path}`,
  })

  if (ok) {
    showToast(`✓ 已成功挂载工程: ${proj.name}`)
    showProjectModal.value = false
    scrollToBottom()
    // 重新拉取探测状态以刷新 mounted 标记
    loadDiscoveredProjects()
  } else {
    showToast('❌ 挂载工程失败')
  }
}

async function loadServerFs(targetPath?: string) {
  try {
    fsLoading.value = true
    const res = await codexStore.fetchFileSystem(targetPath, showHiddenFiles.value)
    if (res) {
      fsResult.value = res
      customPathInput.value = res.current_path
      selectedServerFolder.value = res.current_path
      serverProjectName.value = res.current_path.split('/').filter(Boolean).pop() || 'new-project'
      if (res.system_info?.os === 'Linux') {
        serverMachineName.value = 'Ubuntu 部署机'
        serverHostType.value = 'remote'
      } else {
        serverMachineName.value = '本机环境'
        serverHostType.value = 'local'
      }
    }
  } finally {
    fsLoading.value = false
  }
}

function selectServerItem(item: FileSystemItem) {
  if (item.is_dir) {
    selectedServerFolder.value = item.path
    serverProjectName.value = item.name
  }
}

function enterServerDirectory(item: FileSystemItem) {
  if (item.is_dir) {
    loadServerFs(item.path)
  }
}

async function handleConfirmMountServerProject() {
  const path = selectedServerFolder.value || fsResult.value?.current_path
  if (!path) {
    showToast('⚠️ 请选择待挂载的部署机目录')
    return
  }

  const name = serverProjectName.value.trim() || path.split('/').filter(Boolean).pop() || 'my-project'
  const ok = await codexStore.createProject({
    name,
    host_type: serverHostType.value,
    path,
    machine_name: serverMachineName.value,
    description: `部署机工程目录挂载: ${path}`,
  })

  if (ok) {
    showToast(`✓ 已成功挂载工程: ${name}`)
    showProjectModal.value = false
    scrollToBottom()
  } else {
    showToast('❌ 挂载工程失败')
  }
}

function triggerUploadFolderPicker() {
  uploadFolderInputRef.value?.click()
}

function triggerUploadZipPicker() {
  uploadZipInputRef.value?.click()
}

function onClientFolderSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return

  uploadFiles.value = Array.from(files)
  uploadZipFile.value = null
  const relativePath = files[0].webkitRelativePath || ''
  const folderName = relativePath.split('/')[0] || 'local-strategy'
  uploadProjectName.value = folderName
  showToast(`📁 已选中本地文件夹: ${folderName} (${files.length} 个文件)`)
}

function onClientZipSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return

  uploadZipFile.value = files[0]
  uploadFiles.value = []
  uploadProjectName.value = files[0].name.replace(/\.zip$/i, '')
  showToast(`📦 已选中 Zip 压缩包: ${files[0].name}`)
}

async function handleUploadAndMount() {
  if (uploadFiles.value.length === 0 && !uploadZipFile.value) {
    showToast('⚠️ 请先选择本地文件夹或 .zip 文件')
    return
  }

  isUploading.value = true
  try {
    const filesToSend = uploadZipFile.value ? [uploadZipFile.value] : uploadFiles.value
    const proj = await codexStore.uploadProjectFolder({
      projectName: uploadProjectName.value.trim() || 'uploaded-project',
      files: filesToSend,
      destinationDir: uploadDestinationDir.value.trim() || undefined,
      hostType: uploadHostType.value,
      machineName: uploadMachineName.value,
    })

    if (proj) {
      showToast(`🚀 工程 ${proj.name} 已成功上传并挂载至部署机！`)
      showProjectModal.value = false
      uploadFiles.value = []
      uploadZipFile.value = null
      scrollToBottom()
    } else {
      showToast('❌ 上传部署失败，请重试')
    }
  } catch (err) {
    showToast('❌ 上传异常')
  } finally {
    isUploading.value = false
  }
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

function onTriggerMouseUp() {
  if (!isDraggingTrigger) return
  isDraggingTrigger = false
  window.removeEventListener('mousemove', onTriggerMouseMove)
  window.removeEventListener('mouseup', onTriggerMouseUp)

  if (!hasTriggerMoved && triggerPos.value) {
    aiStore.open(triggerPos.value)
  }
}

// 全局快捷键支持 (⌘+J 呼出，Esc 中断推演)
function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') {
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
  codexStore.fetchProjects()
  fetchMcpServers()
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('click', handleClickOutside)
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
        class="group flex items-center space-x-2.5 pl-3 pr-3.5 py-2 rounded-full bg-[#13151b]/95 hover:bg-[#181a23] border border-white/[0.14] hover:border-purple-500/50 shadow-2xl shadow-black/80 hover:shadow-purple-500/20 backdrop-blur-2xl transition-shadow duration-200 cursor-grab active:cursor-grabbing select-none"
        title="点击唤醒 Alpha 智能量化工作台 (⌘+J)，按住左键自由拖动"
      >
        <div class="relative flex items-center justify-center w-7 h-7 rounded-xl bg-gradient-to-br from-purple-500/25 via-indigo-500/20 to-transparent border border-purple-500/30 text-sm shadow-sm group-hover:border-purple-400/60 transition-colors pointer-events-none">
          <span>🤖</span>
          <span
            class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-[#13151b]"
            :class="codexStore.isStreaming ? 'bg-amber-400 animate-ping' : 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'"
          ></span>
        </div>

        <div class="flex flex-col text-left pointer-events-none">
          <div class="flex items-center space-x-1.5">
            <span class="text-xs font-semibold text-zinc-100 group-hover:text-purple-300 transition-colors tracking-wide">Alpha Copilot</span>
          </div>
          <span class="text-[9px] text-zinc-400 font-mono flex items-center space-x-1">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block animate-pulse"></span>
            <span>{{ codexStore.isStreaming ? 'Alpha 正在推演...' : '阿尔法投研工坊' }}</span>
          </span>
        </div>

        <div class="ml-1 pl-2 border-l border-white/[0.1] flex items-center pointer-events-none">
          <kbd class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.06] border border-white/[0.12] text-zinc-300 font-mono shadow-inner group-hover:border-purple-500/40 group-hover:text-purple-300 transition-colors">⌘J</kbd>
        </div>
      </div>
    </transition>

    <!-- ========================================================================= -->
    <!-- 2. 展开状态：集成 Codex 工作台大框架的高质感悬浮窗口 (Fixed Floating Window) -->
    <!-- ========================================================================= -->
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
            <span class="font-bold text-white tracking-wide flex items-center space-x-1">
              <span>📁</span>
              <span>{{ codexStore.activeProject?.name || '项目' }}</span>
            </span>
            <span class="text-zinc-500">/</span>
            <span class="text-zinc-300 font-medium truncate max-w-[280px]">
              {{ codexStore.activeSession?.title || '新对话' }}
            </span>
          </div>
        </div>

        <!-- 右侧：开辟新会话 + Agent 配置 + 关闭窗口 (✕) -->
        <div class="flex items-center space-x-1.5 text-zinc-400 text-xs">
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

            <!-- @ MCP 插件 (支持动态热插拔入口) -->
            <button
              @click="showMcpDrawer = !showMcpDrawer"
              :class="[
                'w-full flex items-center justify-between px-2.5 py-1.5 rounded-xl text-xs transition-all cursor-pointer border',
                showMcpDrawer
                  ? 'bg-purple-500/20 border-purple-500/40 text-purple-300 shadow-sm'
                  : 'bg-white/[0.03] border-white/[0.06] text-zinc-300 hover:text-white hover:bg-white/[0.07]',
              ]"
              title="查看与动态插拔 MCP 服务"
            >
              <div class="flex items-center space-x-2">
                <span>@</span>
                <span>MCP 插件</span>
              </div>
              <span class="px-1.5 py-0.2 rounded-full text-[9px] font-mono bg-purple-500/25 text-purple-300">
                {{ totalActiveMcpTools }} 工具
              </span>
            </button>

            <!-- 项目折叠列表区 -->
            <div class="pt-2">
              <div class="flex items-center justify-between px-1 pb-1.5 text-[11px] font-semibold text-zinc-400">
                <span>项目</span>
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
                  </div>

                  <!-- 展开的项目会话列表 (灰色高亮胶囊) -->
                  <div v-show="isProjectExpanded(proj.id)" class="pl-4 pr-1 space-y-0.5">
                    <div
                      v-for="sess in proj.sessions"
                      :key="sess.id"
                      @click="handleSelectSession(proj.id, sess.id)"
                      :class="[
                        'px-2 py-1 rounded-lg text-[11px] cursor-pointer truncate transition-all duration-150',
                        codexStore.activeProjectId === proj.id && codexStore.activeSessionId === sess.id
                          ? 'bg-white/[0.14] text-white font-medium shadow-xs'
                          : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]',
                      ]"
                      :title="sess.title"
                    >
                      {{ sess.title }}
                    </div>

                    <button
                      @click="handleNewChat(proj.id)"
                      class="w-full text-left px-2 py-0.5 text-[10px] text-zinc-400 hover:text-purple-300 cursor-pointer"
                    >
                      ＋ 新建任务
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 2.2.2 MCP 动态热插拔抽屉 (Dynamic Plug & Unplug Overlay) -->
        <transition name="slide-fade">
          <div
            v-if="showMcpDrawer"
            class="absolute top-0 left-56 bottom-0 w-80 bg-[#161720]/95 border-r border-white/[0.12] z-30 shadow-2xl p-4 flex flex-col justify-between backdrop-blur-xl"
          >
            <div class="space-y-3 flex-1 overflow-y-auto">
              <div class="flex items-center justify-between border-b border-white/[0.08] pb-2.5">
                <div class="flex items-center space-x-1.5">
                  <span class="text-sm">🔌</span>
                  <span class="font-bold text-xs text-white">MCP 动态热插拔</span>
                </div>
                <button
                  @click="showMcpDrawer = false"
                  class="text-zinc-400 hover:text-white text-xs cursor-pointer p-1"
                >
                  ✕
                </button>
              </div>

              <div class="text-[11px] text-zinc-400 leading-relaxed">
                随时动态挂载或安全拔出断开 MCP 服务器，微服务免重启即时生效。
              </div>

              <!-- MCP 列表与开关 -->
              <div class="space-y-2.5 pt-1">
                <div
                  v-for="s in mcpServers"
                  :key="s.name"
                  class="p-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06] space-y-2"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-1.5">
                      <span class="font-bold text-xs text-zinc-100">{{ s.name }}</span>
                    </div>

                    <!-- 动态热插拔 Switch 开关 -->
                    <button
                      @click="toggleMcpServer(s)"
                      :class="[
                        'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        s.enabled ? 'bg-emerald-500' : 'bg-zinc-700',
                      ]"
                      :title="s.enabled ? '点击拔出断开该 MCP' : '点击挂载接入该 MCP'"
                    >
                      <div
                        :class="[
                          'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                          s.enabled ? 'translate-x-4' : 'translate-x-0',
                        ]"
                      ></div>
                    </button>
                  </div>

                  <div class="text-[10px] text-zinc-400 leading-snug">
                    {{ s.description || '自定义 MCP 服务' }}
                  </div>

                  <div class="flex items-center justify-between text-[10px] font-mono text-zinc-500 pt-1 border-t border-white/[0.04]">
                    <span>分类: {{ s.category }}</span>
                    <span :class="s.enabled ? 'text-emerald-400 font-bold' : 'text-zinc-500'">
                      {{ s.enabled ? `✓ 已挂载 (${s.tools_count} 工具)` : '⏹️ 已拔出断开' }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div class="pt-3 border-t border-white/[0.08]">
              <button
                @click="router.push('/agent-settings'); showMcpDrawer = false"
                class="w-full py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs font-medium cursor-pointer transition-colors"
              >
                ⚙️ 前往高级配置中心管理新 MCP
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

                    <!-- 右侧折叠指示符 -->
                    <div class="flex items-center space-x-1 text-zinc-400 text-[11px] group-hover:text-zinc-300 transition-colors">
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

                        <!-- 单项状态标识 -->
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
                            <span v-if="tc.status === 'calling'" class="text-amber-400 animate-pulse font-bold">● LIVE</span>
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
                <div class="h-3.5 mt-0.5 flex items-center space-x-1.5 text-[10px] text-zinc-400 opacity-0 group-hover:opacity-100 transition-opacity duration-150 select-none">
                  <span class="text-[10px] font-sans text-zinc-400 tracking-tight">{{ formatWeekdayTime(msg.timestamp) }}</span>
                  <button
                    @click="copyText(msg.content)"
                    class="p-0.5 rounded hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer flex items-center space-x-1"
                    title="复制回答内容"
                  >
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <span>复制</span>
                  </button>
                </div>
              </div>
            </div>

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
                      title="点击切换推理模型与思考程度"
                    >
                      <span class="text-[11px]">{{ currentThinkingOption.icon }}</span>
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
                        class="absolute bottom-full mb-2 right-0 w-80 rounded-2xl bg-[#1c1d25] border border-white/[0.14] shadow-2xl p-3 z-50 text-xs space-y-3 backdrop-blur-2xl"
                      >
                        <!-- 模块 1: 推理模型 (从新到旧 5 个已验通模型) -->
                        <div class="space-y-1.5">
                          <div class="flex items-center justify-between pb-1 border-b border-white/[0.06]">
                            <span class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider flex items-center space-x-1">
                              <span>🤖</span>
                              <span>推理模型 (默认 Lite 极速及前沿推演)</span>
                            </span>
                            <span class="text-[9px] text-emerald-400 font-mono">Key 驱动</span>
                          </div>

                          <div class="space-y-1 max-h-48 overflow-y-auto pr-0.5">
                            <button
                              v-for="m in AVAILABLE_MODELS"
                              :key="m.id"
                              @click.stop="selectModel(m.id)"
                              :class="[
                                'w-full text-left p-2 rounded-xl transition-all cursor-pointer flex items-start space-x-2 border',
                                codexStore.aiModel === m.id
                                  ? 'bg-purple-500/20 border-purple-500/40 text-purple-200 shadow-xs'
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
                                        m.isDefault ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 font-bold' : m.isLatest ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 font-bold' : 'bg-white/[0.06] text-zinc-400',
                                      ]"
                                    >
                                      {{ m.tag }}
                                    </span>
                                  </div>
                                  <span v-if="codexStore.aiModel === m.id" class="text-purple-400 font-bold text-xs">✓</span>
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

      <!-- 2.3 挂载与导入工程模态框 (Server File Tree & Client Upload Modal) -->
      <transition name="fade">
        <div
          v-if="showProjectModal"
          class="absolute inset-0 bg-[#0e1017]/95 backdrop-blur-2xl z-50 flex flex-col p-5 overflow-hidden select-none animate-fadeIn border border-white/[0.12] rounded-2xl"
        >
          <!-- 模态框顶栏 -->
          <div class="flex items-center justify-between pb-3 border-b border-white/[0.08] shrink-0">
            <div class="flex items-center space-x-2.5">
              <div class="w-8 h-8 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center text-sm shadow-sm text-purple-300">
                📁
              </div>
              <div>
                <h3 class="text-sm font-bold text-white flex items-center space-x-2">
                  <span>挂载与导入量化工程</span>
                  <span class="text-[10px] font-normal px-2 py-0.5 rounded-full bg-white/[0.06] text-zinc-400 border border-white/[0.08]">
                    {{ fsResult?.system_info?.os === 'Linux' ? '🐧 Ubuntu 部署机节点' : '💻 当前服务节点' }}
                  </span>
                </h3>
                <p class="text-[11px] text-zinc-400">支持部署机智能探测一键挂载 · 目录树浏览 · 访问机客户端一键上传</p>
              </div>
            </div>

            <button
              @click="showProjectModal = false"
              class="w-7 h-7 rounded-lg hover:bg-white/[0.08] text-zinc-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              title="关闭"
            >
              ✕
            </button>
          </div>

          <!-- 双 Tab 切换栏 -->
          <div class="flex items-center space-x-2 pt-3 pb-2 shrink-0 border-b border-white/[0.06]">
            <button
              @click="projectModalTab = 'server'"
              :class="[
                'flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all border',
                projectModalTab === 'server'
                  ? 'bg-purple-500/20 text-purple-200 border-purple-500/40 shadow-xs'
                  : 'bg-white/[0.03] text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-white/[0.06]'
              ]"
            >
              <span>🖥️</span>
              <span>部署机已有工程 (智能探测 / 目录树)</span>
            </button>

            <button
              @click="projectModalTab = 'upload'"
              :class="[
                'flex items-center space-x-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all border',
                projectModalTab === 'upload'
                  ? 'bg-purple-500/20 text-purple-200 border-purple-500/40 shadow-xs'
                  : 'bg-white/[0.03] text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-white/[0.06]'
              ]"
            >
              <span>💻</span>
              <span>访问机本地上传 (从当前电脑上传至部署机)</span>
            </button>
          </div>

          <!-- Tab 1 内容：部署机工程管理 (智能探测 / 目录树) -->
          <div v-if="projectModalTab === 'server'" class="flex-1 flex flex-col min-h-0 pt-2.5 space-y-2.5">
            <!-- 模式切换：智能探测工程 vs 目录树自定义浏览 -->
            <div class="flex items-center justify-between pb-1 shrink-0">
              <div class="flex items-center space-x-1 bg-black/40 p-1 rounded-xl border border-white/[0.08]">
                <button
                  @click="serverSubTab = 'auto'"
                  :class="[
                    'px-3 py-1 rounded-lg text-xs font-semibold cursor-pointer transition-all flex items-center space-x-1.5',
                    serverSubTab === 'auto'
                      ? 'bg-purple-500/25 text-purple-200 border border-purple-500/40 shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  ]"
                >
                  <span>✨ 智能探测工程</span>
                  <span class="px-1.5 py-0.2 rounded-full text-[9px] bg-purple-500/30 text-purple-200 border border-purple-500/40">
                    免输路径 · 推荐
                  </span>
                </button>
                <button
                  @click="serverSubTab = 'tree'"
                  :class="[
                    'px-3 py-1 rounded-lg text-xs font-semibold cursor-pointer transition-all flex items-center space-x-1.5',
                    serverSubTab === 'tree'
                      ? 'bg-purple-500/25 text-purple-200 border border-purple-500/40 shadow-xs'
                      : 'text-zinc-400 hover:text-zinc-200'
                  ]"
                >
                  <span>📂 目录树浏览</span>
                  <span class="text-[10px] text-zinc-500">自定义路径</span>
                </button>
              </div>

              <div class="flex items-center space-x-2">
                <button
                  v-if="serverSubTab === 'auto'"
                  @click="loadDiscoveredProjects"
                  :disabled="loadingDiscovered"
                  class="px-2.5 py-1 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-zinc-300 hover:text-white text-xs cursor-pointer transition-colors flex items-center space-x-1.5 border border-white/[0.08]"
                  title="重新扫描部署机工程"
                >
                  <span :class="{'animate-spin': loadingDiscovered}">🔄</span>
                  <span>{{ loadingDiscovered ? '扫描中...' : '重新扫描' }}</span>
                </button>
              </div>
            </div>

            <!-- 子视图 1: 智能探测工程列表 (推荐 · 零路径手输) -->
            <div v-if="serverSubTab === 'auto'" class="flex-1 flex flex-col min-h-0 space-y-2">
              <div class="text-[11px] text-zinc-400 flex items-center justify-between shrink-0 px-1">
                <span>系统已自动为您扫描部署机常用目录下的量化/代码工程：</span>
                <span class="text-zinc-500 font-mono">共发现 {{ discoveredProjects.length }} 个工程</span>
              </div>

              <!-- 加载中 -->
              <div v-if="loadingDiscovered" class="flex-1 flex flex-col items-center justify-center space-y-2 text-zinc-400 text-xs py-12 rounded-xl bg-black/30 border border-white/[0.06]">
                <svg class="animate-spin w-5 h-5 text-purple-400" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <span>正在自动扫描部署机磁盘中的代码与策略工程...</span>
              </div>

              <!-- 列表为空 -->
              <div v-else-if="discoveredProjects.length === 0" class="flex-1 flex flex-col items-center justify-center space-y-2.5 text-zinc-400 text-xs py-12 rounded-xl bg-black/30 border border-white/[0.06] text-center px-4">
                <div class="text-3xl">🔍</div>
                <div class="text-sm font-semibold text-zinc-300">未在常见目录扫描到独立工程</div>
                <div class="text-[11px] text-zinc-500 max-w-sm leading-relaxed">
                  系统已检查当前工作区根目录及其上层兄弟目录。如果您将代码放置在特殊路径，可切换至「目录树浏览」点击选取，或通过「访问机本地上传」上传本地工程。
                </div>
                <div class="flex items-center space-x-2 pt-2">
                  <button
                    @click="serverSubTab = 'tree'"
                    class="px-3.5 py-1.5 rounded-lg bg-white/[0.08] hover:bg-white/[0.15] text-zinc-200 text-xs cursor-pointer transition-colors"
                  >
                    切换至目录树浏览 ➔
                  </button>
                  <button
                    @click="projectModalTab = 'upload'"
                    class="px-3.5 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-200 text-xs cursor-pointer transition-colors border border-purple-500/30"
                  >
                    从本机上传工程 ➔
                  </button>
                </div>
              </div>

              <!-- 工程卡片列表 -->
              <div v-else class="flex-1 overflow-y-auto pr-1 space-y-2 min-h-0">
                <div
                  v-for="proj in discoveredProjects"
                  :key="proj.path"
                  class="p-3.5 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.08] hover:border-purple-500/40 transition-all flex items-center justify-between space-x-3 group"
                >
                  <div class="flex items-start space-x-3 min-w-0 flex-1">
                    <div class="w-10 h-10 rounded-xl bg-purple-500/15 border border-purple-500/30 flex items-center justify-center text-xl shrink-0 mt-0.5">
                      <span v-if="proj.tags?.some(t => t.includes('量化'))">⚡</span>
                      <span v-else-if="proj.tags?.some(t => t.toLowerCase().includes('python'))">🐍</span>
                      <span v-else-if="proj.tags?.some(t => t.toLowerCase().includes('web'))">🌐</span>
                      <span v-else>📁</span>
                    </div>

                    <div class="min-w-0 flex-1 space-y-1">
                      <div class="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span class="text-sm font-bold text-zinc-100 group-hover:text-purple-200 transition-colors truncate">
                          {{ proj.name }}
                        </span>

                        <span
                          v-if="proj.is_current"
                          class="px-2 py-0.5 rounded-md text-[10px] font-mono bg-purple-500/25 text-purple-200 border border-purple-500/40 shrink-0 font-bold"
                        >
                          ⭐ 当前运行根工程
                        </span>

                        <span
                          v-for="tag in proj.tags || []"
                          :key="tag"
                          :class="[
                            'px-2 py-0.5 rounded-md text-[10px] font-mono shrink-0',
                            tag.includes('量化')
                              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold'
                              : tag.toLowerCase().includes('python')
                              ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                              : tag.toLowerCase().includes('web')
                              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                              : 'bg-white/[0.06] text-zinc-300 border border-white/[0.08]'
                          ]"
                        >
                          {{ tag }}
                        </span>
                      </div>

                      <div class="flex items-center space-x-1.5 text-[11px] text-zinc-400 font-mono truncate">
                        <span class="text-zinc-500 shrink-0">路径:</span>
                        <span class="truncate text-zinc-300 select-all font-mono" :title="proj.path">{{ proj.path }}</span>
                      </div>

                      <div class="text-[10px] text-zinc-500 truncate">
                        <span>{{ proj.description }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- 右侧操作 -->
                  <div class="shrink-0 flex items-center pl-2">
                    <button
                      v-if="proj.is_mounted"
                      disabled
                      class="px-3.5 py-1.5 rounded-lg bg-zinc-800/80 text-zinc-400 text-xs font-medium cursor-not-allowed border border-zinc-700/50 flex items-center space-x-1"
                    >
                      <span>✓</span>
                      <span>已挂载</span>
                    </button>
                    <button
                      v-else
                      @click="handleMountDiscoveredProject(proj)"
                      class="px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-600 hover:to-indigo-700 text-white font-bold text-xs shadow-md shadow-purple-500/25 transition-all cursor-pointer flex items-center space-x-1"
                    >
                      <span>＋</span>
                      <span>一键挂载</span>
                    </button>
                  </div>
                </div>
              </div>

              <!-- 底部操作提示 -->
              <div class="pt-2 border-t border-white/[0.04] flex items-center justify-between text-[11px] text-zinc-500">
                <span>💡 提示：点击「一键挂载」即可立即将该工程接入 Alpha Copilot，无需手动输入路径。</span>
                <button
                  @click="showProjectModal = false"
                  class="px-3 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
                >
                  关闭
                </button>
              </div>
            </div>

            <!-- 子视图 2: 目录树浏览 (自定义路径) -->
            <div v-else class="flex-1 flex flex-col min-h-0 space-y-3">
              <!-- 路径输入栏与快捷跳转 -->
              <div class="space-y-2 shrink-0">
                <!-- 快捷入口 -->
                <div class="flex items-center space-x-2 text-[11px] overflow-x-auto pb-0.5">
                  <span class="text-zinc-500 shrink-0">快速跳转:</span>
                  <button
                    v-for="qr in fsResult?.quick_roots || []"
                    :key="qr.path"
                    @click="loadServerFs(qr.path)"
                    class="px-2 py-0.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-zinc-300 hover:text-white transition-colors cursor-pointer shrink-0 flex items-center space-x-1 border border-white/[0.05]"
                    :title="qr.path"
                  >
                    <span>{{ qr.icon }}</span>
                    <span>{{ qr.name }}</span>
                  </button>
                </div>

                <!-- 地址栏与面包屑 -->
                <div class="flex items-center space-x-2">
                  <div class="flex-1 flex items-center px-2.5 py-1.5 rounded-xl bg-black/40 border border-white/[0.1] text-xs font-mono text-zinc-200 focus-within:border-purple-500/50">
                    <span class="text-zinc-500 pr-1">📁</span>
                    <input
                      v-model="customPathInput"
                      @keydown.enter="loadServerFs(customPathInput)"
                      placeholder="输入或粘贴部署机绝对路径，如 /home/ubuntu/quant-strategies"
                      class="flex-1 bg-transparent border-none outline-hidden text-xs font-mono text-zinc-100 placeholder-zinc-500"
                    />
                    <button
                      @click="loadServerFs(customPathInput)"
                      class="px-2 py-0.5 rounded bg-white/[0.08] hover:bg-white/[0.15] text-zinc-300 hover:text-white text-[10px] cursor-pointer transition-colors"
                    >
                      前往
                    </button>
                  </div>

                  <label class="flex items-center space-x-1 text-[11px] text-zinc-400 cursor-pointer shrink-0">
                    <input
                      type="checkbox"
                      v-model="showHiddenFiles"
                      @change="loadServerFs(fsResult?.current_path)"
                      class="rounded accent-purple-500 cursor-pointer"
                    />
                    <span>显示隐藏项</span>
                  </label>
                </div>
              </div>

              <!-- 文件/目录列表卡片 -->
              <div class="flex-1 min-h-0 rounded-xl bg-black/30 border border-white/[0.08] flex flex-col overflow-hidden">
                <div class="px-3 py-1.5 bg-white/[0.02] border-b border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-400 shrink-0 font-medium">
                  <div class="flex items-center space-x-1 truncate max-w-[70%]">
                    <span class="text-zinc-500">当前位置:</span>
                    <span class="font-mono text-zinc-200 truncate">{{ fsResult?.current_path }}</span>
                  </div>
                  <div class="flex items-center space-x-2 font-mono text-[10px] text-zinc-500">
                    <span>共 {{ fsResult?.items?.length || 0 }} 项</span>
                    <span v-if="fsResult?.free_space_gb">可用 {{ fsResult.free_space_gb }} GB</span>
                  </div>
                </div>

                <!-- 列表加载态 -->
                <div v-if="fsLoading" class="flex-1 flex items-center justify-center space-x-2 text-zinc-400 text-xs">
                  <svg class="animate-spin w-4 h-4 text-purple-400" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                  </svg>
                  <span>正在扫描部署机文件系统...</span>
                </div>

                <!-- 列表内容 -->
                <div v-else class="flex-1 overflow-y-auto p-1.5 space-y-0.5">
                  <!-- 返回上级 -->
                  <div
                    v-if="fsResult?.parent_path"
                    @click="loadServerFs(fsResult.parent_path)"
                    class="flex items-center space-x-2 px-2.5 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-white hover:bg-white/[0.06] cursor-pointer transition-colors"
                  >
                    <span class="text-sm">↩️</span>
                    <span class="font-mono text-[11px]">.. (返回上一层目录)</span>
                  </div>

                  <!-- 遍历子项 -->
                  <div
                    v-for="item in fsResult?.items || []"
                    :key="item.path"
                    @click="selectServerItem(item)"
                    @dblclick="enterServerDirectory(item)"
                    :class="[
                      'flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-all select-none',
                      selectedServerFolder === item.path
                        ? 'bg-purple-500/25 border border-purple-500/40 text-white font-medium shadow-xs'
                        : 'hover:bg-white/[0.05] text-zinc-300'
                    ]"
                  >
                    <div class="flex items-center space-x-2 truncate">
                      <span class="text-sm shrink-0">{{ item.is_dir ? '📁' : '📄' }}</span>
                      <span class="truncate font-mono text-[11px]">{{ item.name }}</span>
                      <span
                        v-if="item.is_project"
                        class="px-1.5 py-0.2 rounded text-[9px] font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shrink-0 font-bold"
                      >
                        ✓ 识别为量化工程
                      </span>
                    </div>

                    <div class="flex items-center space-x-2 shrink-0 text-[10px] text-zinc-500 font-mono">
                      <button
                        v-if="item.is_dir"
                        @click.stop="enterServerDirectory(item)"
                        class="px-2 py-0.5 rounded hover:bg-white/[0.1] text-zinc-400 hover:text-zinc-200 transition-colors"
                        title="进入此文件夹"
                      >
                        进入 ➔
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 挂载确认操作区 -->
              <div class="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] space-y-2.5 shrink-0">
                <div class="grid grid-cols-2 gap-3">
                  <div class="space-y-1">
                    <label class="text-[10px] font-medium text-zinc-400">工程显示名称</label>
                    <input
                      v-model="serverProjectName"
                      placeholder="如: quant-alpha-v1"
                      class="w-full px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/[0.1] text-xs font-mono text-zinc-100 placeholder-zinc-500 outline-hidden focus:border-purple-500/50"
                    />
                  </div>
                  <div class="space-y-1">
                    <label class="text-[10px] font-medium text-zinc-400">部署机器节点名称</label>
                    <input
                      v-model="serverMachineName"
                      placeholder="如: Ubuntu-Prod-01"
                      class="w-full px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/[0.1] text-xs font-mono text-zinc-100 placeholder-zinc-500 outline-hidden focus:border-purple-500/50"
                    />
                  </div>
                </div>

                <div class="flex items-center justify-between pt-1 border-t border-white/[0.04]">
                  <div class="text-[11px] text-zinc-400 font-mono truncate max-w-[65%]">
                    <span class="text-zinc-500">拟挂载路径: </span>
                    <span class="text-purple-300 font-bold">{{ selectedServerFolder || fsResult?.current_path }}</span>
                  </div>

                  <div class="flex items-center space-x-2">
                    <button
                      @click="showProjectModal = false"
                      class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
                    >
                      取消
                    </button>
                    <button
                      @click="handleConfirmMountServerProject"
                      :disabled="!selectedServerFolder && !fsResult?.current_path"
                      class="px-4 py-1.5 rounded-xl bg-gradient-to-r from-purple-500 to-indigo-600 hover:from-purple-600 hover:to-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold text-xs shadow-lg shadow-purple-500/25 transition-all cursor-pointer flex items-center space-x-1.5"
                    >
                      <span>✓</span>
                      <span>立即挂载为工程</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Tab 2 内容：从当前访问机客户端上传工程至部署机 -->
          <div v-else class="flex-1 flex flex-col min-h-0 pt-3 space-y-3">
            <!-- 隐藏的本地文件夹与 Zip 选择器 -->
            <input
              ref="uploadFolderInputRef"
              type="file"
              webkitdirectory
              directory
              class="hidden"
              @change="onClientFolderSelected"
            />
            <input
              ref="uploadZipInputRef"
              type="file"
              accept=".zip"
              class="hidden"
              @change="onClientZipSelected"
            />

            <!-- 拖拽/上传选区 -->
            <div
              @click="triggerUploadFolderPicker"
              class="flex-1 min-h-[160px] border-2 border-dashed border-white/[0.15] hover:border-purple-500/50 rounded-2xl bg-white/[0.02] hover:bg-purple-500/[0.03] transition-all flex flex-col items-center justify-center p-6 space-y-3 cursor-pointer group"
            >
              <div class="w-12 h-12 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-2xl group-hover:scale-110 transition-transform">
                🚀
              </div>
              <div class="text-center space-y-1">
                <div class="text-xs font-bold text-zinc-200 group-hover:text-purple-300 transition-colors">
                  点击选择访问机上的本地工程文件夹 (自动打包上传)
                </div>
                <div class="text-[11px] text-zinc-500">
                  支持直接选择本地文件夹，或上传 .zip 策略工程压缩包至远端部署机
                </div>
              </div>

              <div class="flex items-center space-x-2.5 pt-1">
                <button
                  type="button"
                  @click.stop="triggerUploadFolderPicker"
                  class="px-3 py-1.5 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/40 text-xs font-medium cursor-pointer transition-colors"
                >
                  📁 选择本地文件夹
                </button>
                <button
                  type="button"
                  @click.stop="triggerUploadZipPicker"
                  class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 border border-white/[0.1] text-xs font-medium cursor-pointer transition-colors"
                >
                  📦 上传 .zip 压缩包
                </button>
              </div>
            </div>

            <!-- 已选择的待上传清单卡片 -->
            <div v-if="uploadFiles.length > 0 || uploadZipFile" class="p-3 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2.5">
              <div class="flex items-center justify-between text-xs pb-1.5 border-b border-white/[0.06]">
                <div class="flex items-center space-x-2">
                  <span class="text-emerald-400 font-bold">✓</span>
                  <span class="font-bold text-white">{{ uploadProjectName }}</span>
                </div>
                <span class="text-[10px] font-mono text-zinc-400">
                  {{ uploadZipFile ? `1 个 Zip 压缩包 (${(uploadZipFile.size / 1024 / 1024).toFixed(2)} MB)` : `已扫描 ${uploadFiles.length} 个文件` }}
                </span>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-1">
                  <label class="text-[10px] font-medium text-zinc-400">工程命名</label>
                  <input
                    v-model="uploadProjectName"
                    placeholder="项目名称"
                    class="w-full px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/[0.1] text-xs font-mono text-zinc-100 outline-hidden focus:border-purple-500/50"
                  />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] font-medium text-zinc-400">部署机目标目录 (留空使用默认存放区)</label>
                  <input
                    v-model="uploadDestinationDir"
                    placeholder="如: /home/ubuntu/quant_projects"
                    class="w-full px-2.5 py-1.5 rounded-lg bg-black/40 border border-white/[0.1] text-xs font-mono text-zinc-100 placeholder-zinc-500 outline-hidden focus:border-purple-500/50"
                  />
                </div>
              </div>
            </div>

            <!-- 上传操作按钮 -->
            <div class="flex items-center justify-end space-x-2 pt-1">
              <button
                @click="showProjectModal = false"
                class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
              >
                取消
              </button>
              <button
                @click="handleUploadAndMount"
                :disabled="uploadFiles.length === 0 && !uploadZipFile || isUploading"
                class="px-5 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold text-xs shadow-lg shadow-emerald-500/25 transition-all cursor-pointer flex items-center space-x-1.5"
              >
                <span v-if="isUploading" class="inline-block animate-spin">⏳</span>
                <span v-else>🚀</span>
                <span>{{ isUploading ? '正在上传并部署...' : '上传至部署机并挂载' }}</span>
              </button>
            </div>
          </div>
        </div>
      </transition>

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
