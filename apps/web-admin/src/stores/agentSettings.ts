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

const USER_TOOL_NAMES = ['get_user_watchlists', 'get_user_strategies', 'get_user_holdings']
const LOCAL_QUANT_TOOLS = ['validate_strategy_code', 'run_backtest_fast']

const TOOL_DEFAULT_DESCRIPTIONS: Record<string, { desc: string; params: any }> = {
  get_realtime_quote: {
    desc: '获取股票或ETF实时分时行情与五档买卖盘口，含现价、涨跌幅、换手率及高低点',
    params: { properties: { symbol: { type: 'string', description: '标的代码，如 600519.SH, 000001.SZ' } }, required: ['symbol'] }
  },
  get_stock_kline: {
    desc: '获取标的多周期历史K线量价数据（日K、周K、月K、分时K）及前复权数据',
    params: { properties: { symbol: { type: 'string', description: '标的代码' }, interval: { type: 'string', description: 'K线周期 1m/5m/1d/1w' }, limit: { type: 'integer', description: '返回数据条数' } }, required: ['symbol'] }
  },
  get_stock_valuation: {
    desc: '获取股票多维估值指标，含市盈率(PE)、市净率(PB)、总市值、流通市值与估值分位数',
    params: { properties: { symbol: { type: 'string', description: '标的代码' } }, required: ['symbol'] }
  },
  get_stock_financials: {
    desc: '获取公司核心财务与业绩指标，含营收增速、净利润、毛利率及ROE净资产收益率',
    params: { properties: { symbol: { type: 'string', description: '标的代码' } }, required: ['symbol'] }
  },
  get_stock_profile: {
    desc: '获取上市公司主体基本面信息、主营业务构架及所处申万/中信行业分类',
    params: { properties: { symbol: { type: 'string', description: '标的代码' } }, required: ['symbol'] }
  },
  get_stock_shareholders: {
    desc: '查询十大流通股东名册、持股变动比例及机构重仓持股集中度指标',
    params: { properties: { symbol: { type: 'string', description: '标的代码' } }, required: ['symbol'] }
  },
  get_market_sectors: {
    desc: '获取A股行业板块与概念板块实时涨跌幅排行、资金净流入榜单与领涨龙头标的',
    params: { properties: { category: { type: 'string', description: '行业 industry 或概念 concept' } } }
  },
  get_dragon_tiger_list: {
    desc: '获取当日龙虎榜机构游资席位异动明细与主力资金买卖席位净额透视',
    params: { properties: { date: { type: 'string', description: '交易日期 YYYY-MM-DD，留空为最新' } } }
  },
  screen_stocks: {
    desc: '多因子量化选股中台引擎：根据PE区间、PB、市值、涨跌幅指标智能筛选股票标的',
    params: { properties: { pe_min: { type: 'number' }, pe_max: { type: 'number' }, limit: { type: 'integer' } } }
  },
  get_macro_treasury_yield: {
    desc: '获取宏观十年期国债收益率走势与央行货币流动性流动指标',
    params: { properties: { country: { type: 'string', description: '国家代码 CN/US' } } }
  },
  get_system_storage_status: {
    desc: '获取本地金融数据中台缓存水位、ClickHouse/Parquet 存储指标与健康度',
    params: { properties: {} }
  },
  get_user_watchlists: {
    desc: '获取当前登录用户的自选股分组、收藏标的清单与自定义研报备注',
    params: { properties: { group_id: { type: 'string', description: '自选股分组ID，留空为全部' } } }
  },
  get_user_strategies: {
    desc: '获取当前登录用户在系统中的量化策略库源码清单与历史回测基线',
    params: { properties: { status: { type: 'string', description: '策略状态' } } }
  },
  get_user_holdings: {
    desc: '获取当前用户账户组合实盘头寸、持仓数量、可用资金及当前浮动盈亏',
    params: { properties: { account_id: { type: 'string', description: '交易资金账户ID' } } }
  },
  admin_inspect_system_and_services: {
    desc: '超管专属：全景体检宿主机 OS、CPU/内存水位、Docker 容器群与全微服务健康度',
    params: { properties: {} }
  },
  admin_read_source_code: {
    desc: '超管专属：精准读取量化系统工程中任意源文件内容与上下文行号',
    params: { properties: { path: { type: 'string', description: '工程源码相对路径' } }, required: ['path'] }
  },
  admin_modify_source_code: {
    desc: '超管专属：原子化重构与修改工程源码文件，支持精确代码块替换',
    params: { properties: { path: { type: 'string' }, target_content: { type: 'string' }, replacement: { type: 'string' } }, required: ['path', 'target_content', 'replacement'] }
  },
  admin_run_tests: {
    desc: '超管专属：一键在后端沙箱触发 pytest 单元测试矩阵并收集诊断报告',
    params: { properties: { test_path: { type: 'string', description: '测试用例文件路径' } } }
  },
  admin_manage_service: {
    desc: '超管专属：对微服务集群进程执行启动、重载、健康探测与重启管控',
    params: { properties: { service_name: { type: 'string' }, action: { type: 'string' } }, required: ['service_name', 'action'] }
  },
  admin_docker_manage: {
    desc: '超管专属：治理本地与容器化 Docker Compose 服务生命周期与容器日志',
    params: { properties: { action: { type: 'string' } }, required: ['action'] }
  },
  admin_execute_shell: {
    desc: '超管专属：在宿主机受信沙箱中执行受控 Shell 命令行并捕获 stdout/stderr',
    params: { properties: { command: { type: 'string' } }, required: ['command'] }
  },
  admin_navigate_project: {
    desc: '超管专属：多项目源码工作区快速切换与上下文工作目录定位',
    params: { properties: { project_id: { type: 'string' } }, required: ['project_id'] }
  }
}

function normalizeMcpServers(servers: any[], isAdmin: boolean): McpServerItem[] {
  const result: McpServerItem[] = []
  const hasStock = servers.some((s) => s.name === 'mcp-stock' || s.group === 'stock')
  const hasUser = servers.some((s) => s.name === 'mcp-user' || s.group === 'user')

  if (hasStock || hasUser) {
    for (const s of servers) {
      if (s.name === 'stock-data-mcp') continue
      const enrichedTools = (s.tools || []).map((t: any) => {
        const meta = TOOL_DEFAULT_DESCRIPTIONS[t.name]
        return {
          name: t.name,
          description: t.description || meta?.desc || t.name,
          category: t.category || s.category,
          parameters: t.parameters || meta?.params || { properties: {} },
          enabled: t.enabled !== undefined ? t.enabled : true,
        }
      })
      result.push({
        ...s,
        tools: enrichedTools,
        tools_count: enrichedTools.length,
        active_tools_count: enrichedTools.filter((t: any) => t.enabled).length,
      })
    }
  } else {
    // 兼容线上尚未部署新服务的环境：自动从旧单体 stock-data-mcp 中分离出 stock 与 user
    const oldServer = servers.find((s) => s.name === 'stock-data-mcp')
    const allTools: any[] = oldServer?.tools || []

    const userTools = allTools
      .filter((t) => USER_TOOL_NAMES.includes(t.name))
      .map((t) => ({
        name: t.name,
        description: t.description || TOOL_DEFAULT_DESCRIPTIONS[t.name]?.desc || t.name,
        category: 'user',
        parameters: t.parameters || TOOL_DEFAULT_DESCRIPTIONS[t.name]?.params || { properties: {} },
        enabled: true,
      }))

    const stockTools = allTools
      .filter((t) => !USER_TOOL_NAMES.includes(t.name) && !LOCAL_QUANT_TOOLS.includes(t.name))
      .map((t) => ({
        name: t.name,
        description: t.description || TOOL_DEFAULT_DESCRIPTIONS[t.name]?.desc || t.name,
        category: 'stock',
        parameters: t.parameters || TOOL_DEFAULT_DESCRIPTIONS[t.name]?.params || { properties: {} },
        enabled: true,
      }))

    // 1. 金融行情 MCP
    result.push({
      name: 'mcp-stock',
      type: 'http',
      url: '/mcp/stock',
      enabled: oldServer ? oldServer.enabled : true,
      group: 'stock',
      category: 'stock',
      description: '官方金融行情与多维量化分析数据中台 (实时报价/K线/估值/财务/资金流/股东/板块)',
      status: 'CONNECTED',
      tools_count: stockTools.length,
      active_tools_count: stockTools.length,
      tools: stockTools,
      allow_user_toggle: true,
      disabled_tools: [],
    })

    // 2. 用户专属 MCP
    result.push({
      name: 'mcp-user',
      type: 'http',
      url: '/mcp/user',
      enabled: oldServer ? oldServer.enabled : true,
      group: 'user',
      category: 'user',
      description: '用户专属自选股与量化策略私有数据服务 (自选股/策略库/实盘持仓)',
      status: 'CONNECTED',
      tools_count: userTools.length,
      active_tools_count: userTools.length,
      tools: userTools,
      allow_user_toggle: true,
      disabled_tools: [],
    })

    // 其他第三方服务
    for (const s of servers) {
      if (s.name !== 'stock-data-mcp' && s.name !== 'mcp-stock' && s.name !== 'mcp-user') {
        result.push(s)
      }
    }
  }

  // 超管系统级运维治理服务
  if (isAdmin && !result.some((s) => s.name === 'admin-system-tools')) {
    const adminTools = Object.keys(TOOL_DEFAULT_DESCRIPTIONS)
      .filter((k) => k.startsWith('admin_'))
      .map((k) => ({
        name: k,
        description: TOOL_DEFAULT_DESCRIPTIONS[k].desc,
        category: 'admin_devops',
        parameters: TOOL_DEFAULT_DESCRIPTIONS[k].params,
        enabled: true,
      }))
    result.push({
      name: 'admin-system-tools',
      type: 'internal',
      enabled: true,
      group: 'admin',
      category: 'admin_devops',
      description: '超级管理员专属系统级运维管理工具 (宿主机 Shell、源码修改、Docker治理、微服务运维)',
      status: 'CONNECTED',
      tools_count: adminTools.length,
      active_tools_count: adminTools.length,
      tools: adminTools,
      allow_user_toggle: true,
      disabled_tools: [],
    })
  }

  return result
}

      // 获取已挂载 MCP 服务状态
      const mcpResp = await fetch('/api/v1/agent/mcp/servers', { headers })
      if (mcpResp.ok) {
        const mcpData = await mcpResp.json()
        if (mcpData.servers) {
          mcpServers.value = normalizeMcpServers(mcpData.servers, authStore.isAdmin)
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
