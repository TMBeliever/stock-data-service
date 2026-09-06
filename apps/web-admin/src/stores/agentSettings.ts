import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export type ExecutionMode = 'auto' | 'confirm_sensitive' | 'confirm_all'

export interface McpToolItem {
  name: string
  description: string
  category: string
  parameters?: any
  enabled: boolean
}

export interface McpServerItem {
  name: string
  type: string
  url?: string
  command?: string
  args?: string[]
  cwd?: string
  enabled: boolean
  group: string
  category: string
  description: string
  status: 'CONNECTED' | 'CONFIGURED' | 'ERROR' | 'DISABLED' | 'DISCONNECTED'
  tools_count: number
  active_tools_count?: number
  tools: McpToolItem[]
  allow_user_toggle?: boolean
  disabled_tools?: string[]
}

export interface ModelRuntimeConfig {
  default_model: string
  temperature: number
  max_steps: number
  max_observation_chars: number
}

export const useAgentSettingsStore = defineStore('agentSettings', () => {
  const authStore = useAuthStore()

  // 1. 核心状态
  const executionMode = ref<ExecutionMode>(
    (localStorage.getItem('agent_execution_mode') as ExecutionMode) || 'confirm_sensitive'
  )

  const sensitiveTools = ref<string[]>([
    'admin_modify_source_code',
    'admin_execute_shell',
    'admin_docker_manage',
    'admin_manage_service',
    'write_file',
    'run_command',
    'run_backtest_fast',
  ])

  const mcpServers = ref<McpServerItem[]>([])
  const modelConfig = ref<ModelRuntimeConfig>({
    default_model: 'minimax/minimax-m3:free',
    temperature: 0.2,
    max_steps: 0,
    max_observation_chars: 3500,
  })

  const loading = ref(false)
  const saving = ref(false)

  // 2. 检查工具是否需要人工确认授权
  function requiresApproval(toolName: string): boolean {
    if (executionMode.value === 'auto') return false
    if (executionMode.value === 'confirm_all') return true
    // confirm_sensitive 模式
    return sensitiveTools.value.includes(toolName) || toolName.startsWith('admin_modify') || toolName.startsWith('admin_execute')
  }

  // 3. 从后端同步配置
  async function fetchSettings() {
    loading.value = true
    try {
      const headers: Record<string, string> = {}
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      // 获取全局运行配置
      const cfgResp = await fetch('/api/v1/agent/config', { headers })
      if (cfgResp.ok) {
        const data = await cfgResp.json()
        const cfg = data.config
        if (cfg) {
          executionMode.value = cfg.execution_mode || executionMode.value
          localStorage.setItem('agent_execution_mode', executionMode.value)
          if (cfg.sensitive_tools) sensitiveTools.value = cfg.sensitive_tools
          modelConfig.value = {
            default_model: cfg.default_model || 'minimax/minimax-m3:free',
            temperature: cfg.temperature ?? 0.2,
            max_steps: cfg.max_steps ?? 0,
            max_observation_chars: cfg.max_observation_chars ?? 3500,
          }
        }
      }

function normalizeMcpServers(servers: any[]): McpServerItem[] {
  return (servers || []).map((s) => {
    const tools: McpToolItem[] = (s.tools || []).map((t: any) => ({
      name: t.name,
      description: t.description || t.name,
      category: t.category || s.category,
      parameters: t.parameters || { properties: {} },
      enabled: t.enabled !== undefined ? t.enabled : true,
    }))
    return {
      ...s,
      tools,
      tools_count: s.tools_count ?? tools.length,
      active_tools_count: s.active_tools_count ?? tools.filter((t) => t.enabled).length,
    }
  })
}

      // 获取已挂载 MCP 服务状态
      const mcpResp = await fetch('/api/v1/agent/mcp/servers', { headers })
      if (mcpResp.ok) {
        const mcpData = await mcpResp.json()
        if (mcpData.servers) {
          mcpServers.value = normalizeMcpServers(mcpData.servers)
        }
      }
    } catch (e) {
      console.error('Failed to fetch agent settings:', e)
    } finally {
      loading.value = false
    }
  }

  // 4. 更新执行模式
  async function setExecutionMode(mode: ExecutionMode): Promise<boolean> {
    executionMode.value = mode
    localStorage.setItem('agent_execution_mode', mode)

    saving.value = true
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      const res = await fetch('/api/v1/agent/config', {
        method: 'POST',
        headers,
        body: JSON.stringify({ execution_mode: mode }),
      })
      return res.ok
    } catch {
      return false
    } finally {
      saving.value = false
    }
  }

  // 5. 更新模型与运行时配置
  async function updateModelConfig(newConfig: Partial<ModelRuntimeConfig>): Promise<boolean> {
    modelConfig.value = { ...modelConfig.value, ...newConfig }
    saving.value = true
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      const res = await fetch('/api/v1/agent/config', {
        method: 'POST',
        headers,
        body: JSON.stringify(newConfig),
      })
      return res.ok
    } catch {
      return false
    } finally {
      saving.value = false
    }
  }

  // 6. 添加或修改 MCP Server
  async function saveMcpServer(server: Partial<McpServerItem>): Promise<boolean> {
    saving.value = true
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      const res = await fetch('/api/v1/agent/mcp/servers', {
        method: 'POST',
        headers,
        body: JSON.stringify(server),
      })
      if (res.ok) {
        await fetchSettings()
        return true
      }
      return false
    } catch {
      return false
    } finally {
      saving.value = false
    }
  }

  // 7. 开关切换 MCP 服务器
  async function toggleMcpServer(serverName: string, enabled: boolean): Promise<boolean> {
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      const res = await fetch(`/api/v1/agent/mcp/servers/${serverName}/toggle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ enabled }),
      })
      if (res.ok) {
        const s = mcpServers.value.find((item) => item.name === serverName)
        if (s) {
          s.enabled = enabled
          s.status = enabled ? 'CONNECTED' : 'DISABLED'
          if (s.tools) {
            s.tools.forEach((t) => {
              t.enabled = enabled && !(s.disabled_tools || []).includes(t.name)
            })
            s.active_tools_count = s.tools.filter((t) => t.enabled).length
          }
        }
        return true
      }
      return false
    } catch {
      return false
    }
  }

  // 8. 精细化独立开关单个工具
  async function toggleTool(serverName: string, toolName: string, enabled: boolean): Promise<boolean> {
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`

      const res = await fetch(`/api/v1/agent/mcp/servers/${serverName}/tools/${toolName}/toggle`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ enabled, server_name: serverName }),
      })
      if (res.ok) {
        const s = mcpServers.value.find((item) => item.name === serverName)
        if (s && s.tools) {
          const t = s.tools.find((item) => item.name === toolName)
          if (t) {
            t.enabled = enabled
          }
          if (!s.disabled_tools) s.disabled_tools = []
          if (!enabled && !s.disabled_tools.includes(toolName)) {
            s.disabled_tools.push(toolName)
          } else if (enabled) {
            s.disabled_tools = s.disabled_tools.filter((n) => n !== toolName)
          }
          s.active_tools_count = s.tools.filter((item) => item.enabled).length
        }
        return true
      }
      return false
    } catch {
      return false
    }
  }

  return {
    executionMode,
    sensitiveTools,
    mcpServers,
    modelConfig,
    loading,
    saving,
    requiresApproval,
    fetchSettings,
    setExecutionMode,
    updateModelConfig,
    saveMcpServer,
    toggleMcpServer,
    toggleTool,
  }
})
