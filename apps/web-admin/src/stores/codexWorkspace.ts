import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export interface ProjectCardItem {
  type: string
  title: string
  language?: string
  content: string
}

export interface ToolCallItem {
  id: string
  name: string
  arguments?: Record<string, any>
  outputPreview?: string
  liveOutput?: string
  status: 'calling' | 'done' | 'failed' | 'waiting_approval' | 'rejected'
  step?: number
  requiresApprovalReason?: string
}

export interface WaitingApprovalItem {
  id: string
  name: string
  arguments: Record<string, any>
  reason: string
  step?: number
}

export interface ApprovedToolCallPayload {
  id: string
  name: string
  arguments: Record<string, any>
  step?: number
}

export interface CodexMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  cards?: ProjectCardItem[]
  toolCalls?: ToolCallItem[]
  thought?: string
  waitingApproval?: WaitingApprovalItem
}

export interface CodexSession {
  id: string
  project_id: string
  title: string
  last_snippet?: string
  created_at: number
  updated_at: number
  messages: CodexMessage[]
}

export interface CodexProject {
  id: string
  name: string
  host_type: 'local' | 'remote'
  machine_name: string
  machine_address?: string
  path: string
  description?: string
  created_at: number
  sessions: CodexSession[]
}

export interface FileSystemItem {
  name: string
  path: string
  is_dir: boolean
  is_project: boolean
  has_children: boolean
  size: number
  updated_at: number
}

export interface BreadcrumbItem {
  name: string
  path: string
}

export interface QuickRootItem {
  name: string
  path: string
  icon: string
}

export interface FileSystemBrowseResult {
  current_path: string
  parent_path: string | null
  breadcrumbs: BreadcrumbItem[]
  quick_roots: QuickRootItem[]
  items: FileSystemItem[]
  total_items: number
  free_space_gb: number
  system_info: {
    os: string
    node: string
    release: string
    machine: string
  }
}

export interface DiscoveredProjectItem {
  name: string
  path: string
  tags: string[]
  description: string
  updated_at: number
  is_mounted: boolean
  is_current: boolean
}

export type ExecutionMode = 'auto' | 'confirm_sensitive' | 'confirm_all'

export interface AvailableModelItem {
  id: string
  name: string
  series: string
  tag: string
  description: string
  isLatest?: boolean
  isDefault?: boolean
}

// 严格从用户网关渠道筛选的真实可用模型列表
export const AVAILABLE_MODELS: AvailableModelItem[] = [
  {
    id: 'gemini-flash-lite-latest',
    name: 'Gemini Flash Lite',
    series: 'Lite',
    tag: '默认极速',
    description: '系统默认轻量极速模型，毫秒级响应与超低延迟 (推荐默认)',
    isDefault: true,
  },
  {
    id: 'gemini-3.7-flash',
    name: 'Gemini 3.7 Flash',
    series: '3.7',
    tag: '最新旗舰',
    description: '2026 前沿推理旗舰，超快响应与深度多模态思考',
    isLatest: true,
  },
  {
    id: 'gemini-3.6-flash',
    name: 'Gemini 3.6 Flash',
    series: '3.6',
    tag: '前沿高精',
    description: '新一代深度推演模型，极速量化分析与代码生成',
  },
  {
    id: 'gemini-3.5-flash',
    name: 'Gemini 3.5 Flash',
    series: '3.5',
    tag: '均衡稳健',
    description: '生产级标杆模型，逻辑严密，兼顾质量与速率',
  },
  {
    id: 'gemini-3.1-flash-lite',
    name: 'Gemini 3.1 Flash Lite',
    series: '3.1',
    tag: '轻量前沿',
    description: '毫秒级轻量模型，快速行情指标解析与工具调度',
  },
  {
    id: 'gemini-2.5-flash',
    name: 'Gemini 2.5 Flash',
    series: '2.5',
    tag: '经典基线',
    description: '成熟长上下文模型与结构化数据提取基准',
  },
]

export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high'

export interface ThinkingLevelOption {
  level: ThinkingLevel
  label: string
  badge: string
  icon: string
  description: string
}

export const THINKING_LEVEL_OPTIONS: ThinkingLevelOption[] = [
  {
    level: 'off',
    label: '极速响应',
    badge: '关闭思考',
    icon: '⚡',
    description: '直出结论与代码，毫秒级快速响应',
  },
  {
    level: 'low',
    label: '轻度推演',
    badge: 'Low',
    icon: '💡',
    description: '快速逻辑自检，适合日常行情问答与查询',
  },
  {
    level: 'medium',
    label: '均衡思考',
    badge: 'Medium',
    icon: '⚖️',
    description: '默认推荐，兼顾逻辑严密与响应速率',
  },
  {
    level: 'high',
    label: '深度严谨',
    badge: 'High',
    icon: '🧠',
    description: '多步量化逻辑建模、严格防未来函数与深度推导',
  },
]

export const useCodexWorkspaceStore = defineStore('codexWorkspace', () => {
  const projects = ref<CodexProject[]>([])

  // 从 localStorage 恢复上次打开的 project/session
  const _savedProjectId = (() => { try { return localStorage.getItem('codex_active_project_id') || 'proj_quant_system' } catch { return 'proj_quant_system' } })()
  const _savedSessionId = (() => { try { return localStorage.getItem('codex_active_session_id') || 'sess_arch_eval' } catch { return 'sess_arch_eval' } })()

  const activeProjectId = ref<string>(_savedProjectId)
  const activeSessionId = ref<string>(_savedSessionId)
  const isStreaming = ref<boolean>(false)
  const getInitialExecutionMode = (): ExecutionMode => {
    try {
      const val = localStorage.getItem('alpha_execution_mode') as ExecutionMode
      if (val && ['auto', 'confirm_sensitive', 'confirm_all'].includes(val)) {
        return val
      }
    } catch {}
    return 'auto'
  }

  const getInitialAiModel = (): string => {
    try {
      const val = localStorage.getItem('alpha_ai_model')
      if (val && AVAILABLE_MODELS.some((m) => m.id === val)) {
        return val
      }
    } catch {}
    return 'gemini-flash-lite-latest'
  }

  const getInitialThinkingLevel = (): ThinkingLevel => {
    try {
      const val = localStorage.getItem('alpha_thinking_level') as ThinkingLevel
      if (val && ['off', 'low', 'medium', 'high'].includes(val)) {
        return val
      }
    } catch {}
    return 'medium'
  }

  const executionMode = ref<ExecutionMode>(getInitialExecutionMode())
  const aiModel = ref<string>(getInitialAiModel())
  const thinkingLevel = ref<ThinkingLevel>(getInitialThinkingLevel())
  const loading = ref<boolean>(false)
  const abortController = ref<AbortController | null>(null)


  const activeProject = computed(() => {
    return projects.value.find((p) => p.id === activeProjectId.value) || projects.value[0] || null
  })

  const activeSession = computed(() => {
    if (!activeProject.value) return null
    return (
      activeProject.value.sessions.find((s) => s.id === activeSessionId.value) ||
      activeProject.value.sessions[0] ||
      null
    )
  })

  const currentMessages = computed(() => {
    return activeSession.value?.messages || []
  })

  async function fetchProjects() {
    loading.value = true
    try {
      const authStore = useAuthStore()
      const headers: Record<string, string> = {}
      if (authStore.token) {
        headers['Authorization'] = `Bearer ${authStore.token}`
      }
      const res = await fetch('/api/v1/agent/projects', { headers })
      if (res.ok) {
        const data = await res.json()
        const rawProjects: CodexProject[] = data.projects || []
        for (const p of rawProjects) {
          for (const s of p.sessions || []) {
            s.messages = (s.messages || []).map((m: any) => ({
              id: m.id || `msg_${Date.now()}`,
              role: m.role,
              content: m.content || '',
              timestamp: m.timestamp || Date.now(),
              cards: m.cards || [],
              toolCalls: m.toolCalls || (m.tool_calls || []).map((tc: any) => ({
                id: tc.id || tc.name,
                name: tc.name,
                arguments: tc.arguments,
                outputPreview: tc.output_preview || tc.outputPreview,
                status: tc.status || 'done',
                step: tc.step,
              })),
              thought: m.thought,
            }))
          }
        }
        projects.value = rawProjects
        // 恢复上次打开的 project/session；若已删除则兜底选第一个
        if (projects.value.length > 0) {
          const savedProjExists = projects.value.some((p) => p.id === activeProjectId.value)
          if (!savedProjExists) {
            // 上次的 project 已不存在，降级到第一个
            activeProjectId.value = projects.value[0].id
            const firstSess = projects.value[0].sessions?.[0]
            if (firstSess) activeSessionId.value = firstSess.id
            _persistActiveIds()
          } else {
            // project 存在，但检查 session 是否还在
            const proj = projects.value.find((p) => p.id === activeProjectId.value)!
            const savedSessExists = proj.sessions?.some((s) => s.id === activeSessionId.value)
            if (!savedSessExists && proj.sessions?.length > 0) {
              activeSessionId.value = proj.sessions[0].id
              _persistActiveIds()
            }
          }
        }
      }
    } catch (e) {
      console.error('Failed to fetch codex projects:', e)
    } finally {
      loading.value = false
    }
  }

  function _persistActiveIds() {
    try {
      localStorage.setItem('codex_active_project_id', activeProjectId.value)
      localStorage.setItem('codex_active_session_id', activeSessionId.value)
    } catch {}
  }

  function selectSession(projectId: string, sessionId: string) {
    activeProjectId.value = projectId
    activeSessionId.value = sessionId
    _persistActiveIds()
  }

  async function createProject(payload: {
    name: string
    host_type: 'local' | 'remote'
    path: string
    machine_name?: string
    machine_address?: string
    description?: string
  }): Promise<boolean> {
    try {
      const authStore = useAuthStore()
      const res = await fetch('/api/v1/agent/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        const data = await res.json()
        const newProj: CodexProject = data.project
        projects.value.unshift(newProj)
        activeProjectId.value = newProj.id
        if (newProj.sessions?.length > 0) {
          activeSessionId.value = newProj.sessions[0].id
        }
        _persistActiveIds()
        return true
      }
      return false
    } catch (e) {
      console.error('Failed to create project:', e)
      return false
    }
  }

  async function fetchFileSystem(path?: string, showHidden: boolean = false): Promise<FileSystemBrowseResult | null> {
    try {
      const authStore = useAuthStore()
      const queryParams = new URLSearchParams()
      if (path) queryParams.set('path', path)
      if (showHidden) queryParams.set('show_hidden', 'true')

      const res = await fetch(`/api/v1/agent/fs/list?${queryParams.toString()}`, {
        headers: {
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
      })
      if (res.ok) {
        const data = await res.json()
        return data.data as FileSystemBrowseResult
      }
      return null
    } catch (e) {
      console.error('Failed to fetch file system:', e)
      return null
    }
  }

  async function uploadProjectFolder(payload: {
    projectName: string
    files: File[]
    destinationDir?: string
    hostType?: string
    machineName?: string
  }): Promise<CodexProject | null> {
    try {
      const authStore = useAuthStore()
      const formData = new FormData()
      formData.append('project_name', payload.projectName)
      if (payload.destinationDir) formData.append('destination_dir', payload.destinationDir)
      formData.append('host_type', payload.hostType || 'remote')
      formData.append('machine_name', payload.machineName || '当前部署机节点 (Ubuntu/Linux)')

      const relativePaths: string[] = []
      for (const f of payload.files) {
        formData.append('files', f)
        relativePaths.push(f.webkitRelativePath || f.name)
      }
      formData.append('relative_paths', JSON.stringify(relativePaths))

      const res = await fetch('/api/v1/agent/fs/upload', {
        method: 'POST',
        headers: {
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
        body: formData,
      })

      if (res.ok) {
        const data = await res.json()
        const newProj: CodexProject = data.project
        projects.value.unshift(newProj)
        activeProjectId.value = newProj.id
        if (newProj.sessions?.length > 0) {
          activeSessionId.value = newProj.sessions[0].id
        }
        _persistActiveIds()
        return newProj
      }
      return null
    } catch (e) {
      console.error('Failed to upload project folder:', e)
      return null
    }
  }

  async function discoverSystemProjects(): Promise<DiscoveredProjectItem[]> {
    try {
      const authStore = useAuthStore()
      const res = await fetch('/api/v1/agent/fs/discover', {
        headers: {
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
      })
      if (res.ok) {
        const data = await res.json()
        return (data.projects || []) as DiscoveredProjectItem[]
      }
      return []
    } catch (e) {
      console.error('Failed to discover projects:', e)
      return []
    }
  }

  async function deleteProject(projectId: string): Promise<boolean> {
    try {
      const authStore = useAuthStore()
      const res = await fetch(`/api/v1/agent/projects/${projectId}`, {
        method: 'DELETE',
        headers: {
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
      })
      if (res.ok) {
        projects.value = projects.value.filter((p) => p.id !== projectId)
        if (activeProjectId.value === projectId && projects.value.length > 0) {
          activeProjectId.value = projects.value[0].id
          activeSessionId.value = projects.value[0].sessions[0]?.id || ''
          _persistActiveIds()
        }
        return true
      }
      return false
    } catch (e) {
      console.error('Failed to delete project:', e)
      return false
    }
  }

  async function createSession(projectId?: string, title: string = '新对话'): Promise<string | null> {
    const targetProjId = projectId || activeProjectId.value
    if (!targetProjId) return null

    try {
      const authStore = useAuthStore()
      const res = await fetch(`/api/v1/agent/projects/${targetProjId}/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
        body: JSON.stringify({ title }),
      })
      if (res.ok) {
        const data = await res.json()
        const newSess: CodexSession = data.session
        const targetProj = projects.value.find((p) => p.id === targetProjId)
        if (targetProj) {
          targetProj.sessions.unshift(newSess)
        }
        activeProjectId.value = targetProjId
        activeSessionId.value = newSess.id
        _persistActiveIds()
        return newSess.id
      }
      return null
    } catch (e) {
      console.error('Failed to create session:', e)
      return null
    }
  }

  async function deleteSession(projectId: string, sessionId: string): Promise<boolean> {
    try {
      const authStore = useAuthStore()
      const res = await fetch(`/api/v1/agent/projects/${projectId}/sessions/${sessionId}`, {
        method: 'DELETE',
        headers: {
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
      })
      if (res.ok) {
        const targetProj = projects.value.find((p) => p.id === projectId)
        if (targetProj) {
          targetProj.sessions = targetProj.sessions.filter((s) => s.id !== sessionId)
          if (activeSessionId.value === sessionId && targetProj.sessions.length > 0) {
            activeSessionId.value = targetProj.sessions[0].id
            _persistActiveIds()
          }
        }
        return true
      }
      return false
    } catch (e) {
      console.error('Failed to delete session:', e)
      return false
    }
  }

  function setExecutionMode(mode: ExecutionMode) {
    executionMode.value = mode
    try {
      localStorage.setItem('alpha_execution_mode', mode)
    } catch {}
  }

  function toggleExecutionMode() {
    if (executionMode.value === 'auto') {
      executionMode.value = 'confirm_sensitive'
    } else if (executionMode.value === 'confirm_sensitive') {
      executionMode.value = 'confirm_all'
    } else {
      executionMode.value = 'auto'
    }
    try {
      localStorage.setItem('alpha_execution_mode', executionMode.value)
    } catch {}
  }


  function stopStreaming() {
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    isStreaming.value = false
  }

  // 辅助函数：提取文本中的结构化代码块生成专用卡片
  function parseCardsFromContent(text: string): ProjectCardItem[] {
    const cards: ProjectCardItem[] = []
    const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g
    let match
    while ((match = codeBlockRegex.exec(text)) !== null) {
      cards.push({
        type: 'code',
        title: match[1] ? `${match[1].toUpperCase()} 片段` : '纯文本',
        language: match[1] || 'text',
        content: match[2].trim(),
      })
    }
    return cards
  }

  async function sendMessage(
    promptText?: string,
    approvedToolCallPayload?: ApprovedToolCallPayload | string[]
  ) {
    if (isStreaming.value) return
    const curProj = activeProject.value
    const curSess = activeSession.value
    if (!curProj || !curSess) return

    let approvedToolCallsList: string[] = []
    let approvedToolCallObj: ApprovedToolCallPayload | undefined = undefined

    if (Array.isArray(approvedToolCallPayload)) {
      approvedToolCallsList = approvedToolCallPayload
    } else if (approvedToolCallPayload && typeof approvedToolCallPayload === 'object') {
      approvedToolCallObj = approvedToolCallPayload
      approvedToolCallsList = [approvedToolCallPayload.id, approvedToolCallPayload.name]
    }

    let assistantMsg: CodexMessage

    if (promptText && promptText.trim()) {
      const userMsgId = `msg_${Date.now()}`
      const userMsg: CodexMessage = {
        id: userMsgId,
        role: 'user',
        content: promptText.trim(),
        timestamp: Date.now(),
      }
      curSess.messages.push(userMsg)

      // 同步持久化用户消息至后端会话
      try {
        const authStore = useAuthStore()
        fetch(`/api/v1/agent/projects/${curProj.id}/sessions/${curSess.id}/messages`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
          },
          body: JSON.stringify({
            id: userMsgId,
            role: 'user',
            content: userMsg.content,
          }),
        }).catch(() => {})
      } catch {}

      // 如果是新对话的首条提问，自动优化标题
      if (curSess.messages.length === 1 || curSess.title === '新对话') {
        curSess.title = promptText.trim().slice(0, 16)
      }

      const assistantMsgId = `ai_${Date.now()}`
      assistantMsg = {
        id: assistantMsgId,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        cards: [],
        toolCalls: [],
      }
      curSess.messages.push(assistantMsg)
    } else if (approvedToolCallObj || (approvedToolCallsList && approvedToolCallsList.length > 0)) {
      // 授权继续执行模式：沿用等待审批的最后一条 assistant 消息
      const lastMsg = curSess.messages[curSess.messages.length - 1]
      if (lastMsg && lastMsg.role === 'assistant') {
        assistantMsg = lastMsg
        // 清理等待授权标志
        assistantMsg.waitingApproval = undefined
      } else {
        assistantMsg = {
          id: `ai_${Date.now()}`,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          cards: [],
          toolCalls: [],
        }
        curSess.messages.push(assistantMsg)
      }
    } else {
      return
    }

    isStreaming.value = true

    try {
      const authStore = useAuthStore()
      if (abortController.value) {
        abortController.value.abort()
      }
      abortController.value = new AbortController()

      const history = curSess.messages
        .filter((m) => (m.content && m.content.trim()) || (m.toolCalls && m.toolCalls.length > 0))
        .filter((m) => m.id !== assistantMsg.id)
        .slice(-8)
        .map((m) => ({
          role: m.role,
          content: m.content || '',
        }))

      if (promptText && promptText.trim()) {
        history.push({
          role: 'user',
          content: promptText.trim(),
        })
      }

      const resp = await fetch('/api/v1/agent/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
        },
        signal: abortController.value.signal,
        body: JSON.stringify({
          messages: history,
          model: aiModel.value,
          provider: 'key',
          thinking_level: thinkingLevel.value,
          project_id: curProj.id,
          project_path: curProj.path,
          host_type: curProj.host_type,
          execution_mode: executionMode.value,
          approved_tool_calls: approvedToolCallsList,
          approved_tool_call: approvedToolCallObj,
        }),
      })

      if (!resp.ok) {
        throw new Error(`Agent error: ${resp.status} ${await resp.text()}`)
      }

      const reader = resp.body?.getReader()
      if (!reader) throw new Error('No readable stream')

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let currentEventType = 'message'
      let streamDone = false

      streamLoop: while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            currentEventType = 'message'
            continue
          }

          if (trimmed.startsWith('event:')) {
            currentEventType = trimmed.slice(6).trim()
            continue
          }

          if (trimmed.startsWith('data:')) {
            const rawData = trimmed.slice(5).trim()
            // ✅ 修复：done 事件必须跳出外层 while，否则会继续阻塞等待下一个 chunk
            if (rawData === '[DONE]' || currentEventType === 'done') {
              streamDone = true
              break streamLoop
            }

            try {
              if (currentEventType === 'thought') {
                const thoughtData = JSON.parse(rawData)
                assistantMsg.thought = thoughtData.thought || ''
              } else if (currentEventType === 'message') {
                const parsed = JSON.parse(rawData)
                if (parsed.delta) {
                  assistantMsg.content += parsed.delta
                } else if (parsed.content) {
                  assistantMsg.content = parsed.content
                }
              } else if (currentEventType === 'tool_call') {
                const call = JSON.parse(rawData)
                if (!assistantMsg.toolCalls) assistantMsg.toolCalls = []
                let t = assistantMsg.toolCalls.find((x) => x.id === call.id)
                if (!t) {
                  t = {
                    id: call.id,
                    name: call.name,
                    arguments: call.arguments,
                    status: 'calling',
                    step: call.step,
                    liveOutput: '',
                  }
                  assistantMsg.toolCalls.push(t)
                } else {
                  t.status = 'calling'
                }
              } else if (currentEventType === 'tool_progress') {
                const prog = JSON.parse(rawData)
                const t = assistantMsg.toolCalls?.find((x) => x.id === prog.id)
                if (t) {
                  t.liveOutput = (t.liveOutput || '') + (prog.delta || '')
                  t.outputPreview = t.liveOutput
                }
              } else if (currentEventType === 'requires_approval') {
                const reqApp = JSON.parse(rawData)
                if (!assistantMsg.toolCalls) assistantMsg.toolCalls = []
                let t = assistantMsg.toolCalls.find((x) => x.id === reqApp.id)
                if (!t) {
                  t = {
                    id: reqApp.id,
                    name: reqApp.name,
                    arguments: reqApp.arguments,
                    status: 'waiting_approval',
                    step: reqApp.step,
                    requiresApprovalReason: reqApp.reason,
                  }
                  assistantMsg.toolCalls.push(t)
                } else {
                  t.status = 'waiting_approval'
                  t.requiresApprovalReason = reqApp.reason
                }
                assistantMsg.waitingApproval = {
                  id: reqApp.id,
                  name: reqApp.name,
                  arguments: reqApp.arguments,
                  reason: reqApp.reason,
                  step: reqApp.step,
                }
              } else if (currentEventType === 'tool_result') {
                const res = JSON.parse(rawData)
                const t = assistantMsg.toolCalls?.find((x) => x.id === res.id)
                if (t) {
                  t.status = 'done'
                  t.outputPreview = res.output_preview || t.liveOutput
                }
              } else if (currentEventType === 'ping') {
                // 保活驻守心跳，忽略
              }
            } catch {
              if (currentEventType === 'message') {
                assistantMsg.content += rawData
              }
            }
          }
        }
      }

      // 生成结构化卡片
      assistantMsg.cards = parseCardsFromContent(assistantMsg.content)

      // 保存最新消息至后端持久化 (传递 id 避免重复新增消息)
      try {
        await fetch(`/api/v1/agent/projects/${curProj.id}/sessions/${curSess.id}/messages`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authStore.token ? { Authorization: `Bearer ${authStore.token}` } : {}),
          },
          body: JSON.stringify({
            id: assistantMsg.id,
            role: 'assistant',
            content: assistantMsg.content,
            cards: assistantMsg.cards,
            tool_calls: assistantMsg.toolCalls,
          }),
        })
      } catch (saveErr) {
        console.warn('Failed to sync message to backend:', saveErr)
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        assistantMsg.content += '\n\n*(已手动中断生成)*'
      } else {
        assistantMsg.content += `\n\n> ⚠️ **生成失败**: ${err.message || err}`
      }
    } finally {
      isStreaming.value = false
      abortController.value = null
    }
  }

  function setModel(modelId: string) {
    aiModel.value = modelId
    try {
      localStorage.setItem('alpha_ai_model', modelId)
    } catch {}
  }

  function setThinkingLevel(level: ThinkingLevel) {
    thinkingLevel.value = level
    try {
      localStorage.setItem('alpha_thinking_level', level)
    } catch {}
  }

  async function approveToolCall(msg: CodexMessage, tcId: string) {
    let targetPayload: ApprovedToolCallPayload | undefined = undefined
    if (msg.waitingApproval && msg.waitingApproval.id === tcId) {
      targetPayload = {
        id: msg.waitingApproval.id,
        name: msg.waitingApproval.name,
        arguments: msg.waitingApproval.arguments || {},
        step: msg.waitingApproval.step,
      }
      msg.waitingApproval = undefined
    }

    const tc = msg.toolCalls?.find((x) => x.id === tcId)
    if (tc) {
      tc.status = 'calling'
      if (!targetPayload) {
        targetPayload = {
          id: tc.id,
          name: tc.name,
          arguments: tc.arguments || {},
          step: tc.step,
        }
      }
    }

    // 携带明确的工具调用对象直接触发后端执行，杜绝重复向 LLM 询问导致的授权死循环
    await sendMessage(undefined, targetPayload || [tcId])
  }

  function rejectToolCall(msg: CodexMessage, tcId: string) {
    if (msg.waitingApproval?.id === tcId) {
      msg.waitingApproval = undefined
    }
    const tc = msg.toolCalls?.find((x) => x.id === tcId)
    if (tc) {
      tc.status = 'rejected'
    }
    msg.content += '\n\n> ⚠️ *(您已拒绝授权执行该指令，操作已安全取消)*'
  }

  return {
    projects,
    activeProjectId,
    activeSessionId,
    activeProject,
    activeSession,
    currentMessages,
    isStreaming,
    executionMode,
    aiModel,
    thinkingLevel,
    loading,
    fetchProjects,
    selectSession,
    createProject,
    deleteProject,
    fetchFileSystem,
    discoverSystemProjects,
    uploadProjectFolder,
    createSession,
    deleteSession,
    toggleExecutionMode,
    setExecutionMode,
    setModel,
    setThinkingLevel,
    sendMessage,
    approveToolCall,
    rejectToolCall,
    stopStreaming,
  }
})

