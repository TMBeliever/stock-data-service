<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAgentSettingsStore, type ExecutionMode, type McpServerItem } from '@/stores/agentSettings'
import { useAuthStore } from '@/stores/auth'

import { useModalLayer } from '@/stores/modalManager'

const router = useRouter()
const settingsStore = useAgentSettingsStore()
const authStore = useAuthStore()

const activeTab = ref<'permissions' | 'mcp' | 'runtime'>('permissions')
const showAddMcpModal = ref(false)
const toastMsg = ref('')

// 统一弹窗层级管理
const { zIndex: addMcpZIndex } = useModalLayer('add-custom-mcp-modal', showAddMcpModal, () => {
  showAddMcpModal.value = false
})

// 分层解耦服务器引用
const stockServer = computed(() =>
  settingsStore.mcpServers.find(
    (s) => s.name === 'mcp-stock' || s.group === 'stock' || s.group === 'system'
  )
)
const userServer = computed(() =>
  settingsStore.mcpServers.find((s) => s.name === 'mcp-user' || s.group === 'user')
)
const customServers = computed(() =>
  settingsStore.mcpServers.filter(
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
  settingsStore.mcpServers.find((s) => s.name === 'admin-system-tools' || s.group === 'admin')
)

// MCP 完整能力详情弹窗
const detailModalServer = ref<any>(null)
const isDetailOpen = computed(() => !!detailModalServer.value)
const { zIndex: detailModalZIndex } = useModalLayer('mcp-capability-detail-modal', isDetailOpen, () => {
  detailModalServer.value = null
})

function openDetailModal(server: any) {
  detailModalServer.value = server
}
function closeDetailModal() {
  detailModalServer.value = null
}

// 提取工具参数 Schema
function getToolParams(parameters: any) {
  if (!parameters || !parameters.properties) return []
  const requiredList = parameters.required || []
  return Object.entries(parameters.properties).map(([name, prop]: [string, any]) => ({
    name,
    type: prop.type || 'string',
    description: prop.description || '',
    required: requiredList.includes(name),
    default: prop.default !== undefined ? String(prop.default) : undefined,
  }))
}

// 开关整套 MCP 服务
async function handleToggleMcp(server: any) {
  const newStatus = !server.enabled
  const ok = await settingsStore.toggleMcpServer(server.name, newStatus)
  if (ok) {
    showToast(newStatus ? `✓ 已启用: ${server.name}` : `⏹ 已停用: ${server.name}`)
  } else {
    showToast('❌ 状态切换失败')
  }
}

// 精细化独立开关单个工具
async function handleToggleTool(server: any, tool: any) {
  const newStatus = !tool.enabled
  const ok = await settingsStore.toggleTool(server.name, tool.name, newStatus)
  if (ok) {
    showToast(newStatus ? `✓ 工具 [${tool.name}] 已启用` : `⏹ 工具 [${tool.name}] 已停用`)
  } else {
    showToast(`❌ 工具 [${tool.name}] 切换失败`)
  }
}

const newMcp = ref({
  name: '',
  command: 'uv',
  argsText: 'run python custom_mcp.py',
  cwd: '',
  category: 'custom',
  description: '',
})

function showToast(msg: string) {
  toastMsg.value = msg
  setTimeout(() => {
    toastMsg.value = ''
  }, 2500)
}

async function handleSelectMode(mode: ExecutionMode) {
  if (!authStore.isAdmin) {
    showToast('⚠️ 权限不足：修改执行安全模式需要超级管理员权限，请先登录')
    authStore.openLogin()
    return
  }
  const ok = await settingsStore.setExecutionMode(mode)
  if (ok) {
    showToast(`✓ 执行安全模式已切换为：${mode === 'auto' ? '全自动自主执行' : mode === 'confirm_sensitive' ? '敏感写操作人工确认 (推荐)' : '全量工具人工审批'}`)
  }
}

async function handleSaveRuntime() {
  if (!authStore.isAdmin) {
    showToast('⚠️ 权限不足：修改基座模型与运行时需要超级管理员权限，请先登录')
    authStore.openLogin()
    return
  }
  const ok = await settingsStore.updateModelConfig(settingsStore.modelConfig)
  if (ok) {
    showToast('✓ 模型与运行时配置已保存并实时生效')
  } else {
    showToast('❌ 保存失败，请检查服务状态')
  }
}

async function handleCreateMcp() {
  if (!authStore.isAdmin) {
    alert('权限不足：添加 MCP 服务需要超级管理员权限，请先登录')
    authStore.openLogin()
    return
  }
  if (!newMcp.value.name.trim() || !newMcp.value.command.trim()) {
    alert('请填写完整的 MCP 服务器名称与可执行命令')
    return
  }

  const args = newMcp.value.argsText.trim().split(/\s+/).filter(Boolean)
  const ok = await settingsStore.saveMcpServer({
    name: newMcp.value.name.trim(),
    command: newMcp.value.command.trim(),
    args,
    cwd: newMcp.value.cwd.trim() || undefined,
    category: newMcp.value.category || 'custom',
    description: newMcp.value.description.trim() || '自定义 MCP 服务',
    enabled: true,
  })

  if (ok) {
    showAddMcpModal.value = false
    newMcp.value = { name: '', command: 'uv', argsText: '', cwd: '', category: 'custom', description: '' }
    showToast('✓ 自定义 MCP 服务添加成功')
  } else {
    alert('添加失败，请检查参数')
  }
}

onMounted(() => {
  settingsStore.fetchSettings()
})
</script>

<template>
  <div class="max-w-5xl mx-auto space-y-6 pb-16">
    <!-- 提示气泡 Toast -->
    <div
      v-if="toastMsg"
      class="fixed top-20 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-emerald-500/90 text-white font-medium text-xs shadow-xl backdrop-blur-md animate-bounce"
    >
      {{ toastMsg }}
    </div>

    <!-- 顶部导航标题区 -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
      <div class="space-y-1">
        <div class="flex items-center space-x-2">
          <button
            @click="router.back()"
            class="p-1.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] text-zinc-400 hover:text-white transition-colors cursor-pointer text-xs"
            title="返回上一页"
          >
            ← 返回
          </button>
          <h1 class="text-xl font-bold text-white tracking-tight flex items-center space-x-2">
            <span>⚙️</span>
            <span>Agent 治理与配置中心</span>
          </h1>
          <span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-purple-500/15 text-purple-300 border border-purple-500/25">
            PRO Control
          </span>
        </div>
        <p class="text-xs text-zinc-400">
          管理 QuantScope 智能体的执行权限守护、MCP (Model Context Protocol) 扩展矩阵与大模型推理参数
        </p>
      </div>

      <!-- 快捷标签切换 (Tabs) -->
      <div class="flex items-center space-x-1 p-1 rounded-xl bg-white/[0.04] border border-white/[0.08] shrink-0">
        <button
          @click="activeTab = 'permissions'"
          :class="activeTab === 'permissions' ? 'bg-white/10 text-white font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1.5 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>🛡️</span>
          <span>执行安全与确认</span>
        </button>
        <button
          @click="activeTab = 'mcp'"
          :class="activeTab === 'mcp' ? 'bg-white/10 text-white font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1.5 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>🔌</span>
          <span>MCP 服务器矩阵</span>
        </button>
        <button
          @click="activeTab = 'runtime'"
          :class="activeTab === 'runtime' ? 'bg-white/10 text-white font-semibold shadow-sm' : 'text-zinc-400 hover:text-zinc-200'"
          class="px-3 py-1.5 rounded-lg text-xs transition-all flex items-center space-x-1.5 cursor-pointer"
        >
          <span>⚡</span>
          <span>模型与运行调优</span>
        </button>
      </div>
    </div>

    <!-- 非管理员身份警告横幅 -->
    <div
      v-if="!authStore.isAdmin"
      class="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-between text-xs text-amber-200 shadow-sm"
    >
      <div class="flex items-center space-x-2.5">
        <span class="text-base">🔒</span>
        <span>
          <strong>访客/只读预览模式</strong>：当前未登录超级管理员账号，配置仅供查阅。保存与热插拔等管控操作已被系统锁定。
        </span>
      </div>
      <button
        @click="authStore.openLogin()"
        class="px-3 py-1 rounded-lg bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs transition-colors shrink-0 ml-3 cursor-pointer"
      >
        登录管理员
      </button>
    </div>

    <!-- ============================================================== -->
    <!-- Tab 1: 执行安全与授权确认模式 (Human-in-the-Loop) -->
    <!-- ============================================================== -->
    <div v-show="activeTab === 'permissions'" class="space-y-6">
      <div class="p-5 rounded-2xl bg-[#141418] border border-white/[0.08] shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-sm font-bold text-white flex items-center space-x-2">
              <span>🛡️</span>
              <span>执行权限策略 (Execution Permission Mode)</span>
            </h2>
            <p class="text-xs text-zinc-400 mt-0.5">
              控制 Agent 在调用写操作、系统 Shell 与服务器微服务重载时的介入级别
            </p>
          </div>
          <span class="text-[11px] text-zinc-500 font-mono">
            当前生效: <span class="text-amber-300 font-bold">{{ settingsStore.executionMode }}</span>
          </span>
        </div>

        <!-- 三档模式选择卡片 -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          <!-- 1. 全自动执行模式 -->
          <div
            @click="handleSelectMode('auto')"
            :class="settingsStore.executionMode === 'auto' ? 'border-amber-500/60 bg-amber-500/5 ring-1 ring-amber-500/30' : 'border-white/[0.08] bg-black/30 hover:border-white/[0.16]'"
            class="p-4 rounded-xl border transition-all cursor-pointer relative flex flex-col justify-between space-y-3 group"
          >
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-lg">⚡</span>
                <span
                  v-if="settingsStore.executionMode === 'auto'"
                  class="px-2 py-0.5 rounded text-[9px] font-bold bg-amber-500/20 text-amber-300 font-mono"
                >
                  已激活
                </span>
              </div>
              <div class="font-bold text-xs text-white group-hover:text-amber-300 transition-colors">
                全自动自主执行 (Auto)
              </div>
              <p class="text-[11px] text-zinc-400 leading-relaxed">
                Agent 拥有全速自主权，连续推演并自动执行所有工具，适合高频金融量化查询与快速自动化分析。
              </p>
            </div>
            <div class="text-[10px] text-zinc-500 font-mono pt-2 border-t border-white/[0.06]">
              • 速度最快 · 无需人工点击
            </div>
          </div>

          <!-- 2. 敏感写操作人工确认 (推荐) -->
          <div
            @click="handleSelectMode('confirm_sensitive')"
            :class="settingsStore.executionMode === 'confirm_sensitive' ? 'border-emerald-500/60 bg-emerald-500/5 ring-1 ring-emerald-500/30' : 'border-white/[0.08] bg-black/30 hover:border-white/[0.16]'"
            class="p-4 rounded-xl border transition-all cursor-pointer relative flex flex-col justify-between space-y-3 group"
          >
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-lg">🛡️</span>
                <span
                  class="px-2 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 font-mono"
                >
                  {{ settingsStore.executionMode === 'confirm_sensitive' ? '已激活 (推荐)' : '推荐生产使用' }}
                </span>
              </div>
              <div class="font-bold text-xs text-white group-hover:text-emerald-300 transition-colors">
                敏感写操作确认 (Confirm Sensitive)
              </div>
              <p class="text-[11px] text-zinc-400 leading-relaxed">
                行情与数据读取<span class="text-emerald-300">自动放行</span>；涉及修改源代码、执行 Shell 终端指令、Docker 容器治理等危险操作时，在对话卡片中弹出<span class="text-amber-300">人工授权审批卡片</span>。
              </p>
            </div>
            <div class="text-[10px] text-emerald-400/80 font-mono pt-2 border-t border-white/[0.06]">
              • 工业级安全平衡 · 杜绝误操作
            </div>
          </div>

          <!-- 3. 全量工具强制审批 -->
          <div
            @click="handleSelectMode('confirm_all')"
            :class="settingsStore.executionMode === 'confirm_all' ? 'border-purple-500/60 bg-purple-500/5 ring-1 ring-purple-500/30' : 'border-white/[0.08] bg-black/30 hover:border-white/[0.16]'"
            class="p-4 rounded-xl border transition-all cursor-pointer relative flex flex-col justify-between space-y-3 group"
          >
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-lg">🔒</span>
                <span
                  v-if="settingsStore.executionMode === 'confirm_all'"
                  class="px-2 py-0.5 rounded text-[9px] font-bold bg-purple-500/20 text-purple-300 font-mono"
                >
                  已激活
                </span>
              </div>
              <div class="font-bold text-xs text-white group-hover:text-purple-300 transition-colors">
                全量工具强制审批 (Confirm All)
              </div>
              <p class="text-[11px] text-zinc-400 leading-relaxed">
                极致透明与审查。Agent 的每一次工具调用（包括只读股票走势）均暂停并等待您手动点击「批准」，适合高安全审计与教学调试环境。
              </p>
            </div>
            <div class="text-[10px] text-zinc-500 font-mono pt-2 border-t border-white/[0.06]">
              • 100% 人工掌控 · 完全无隐形动作
            </div>
          </div>
        </div>

        <!-- 敏感工具守护受控清单 -->
        <div class="pt-4 border-t border-white/[0.06] space-y-2.5">
          <div class="text-xs font-semibold text-zinc-300 flex items-center space-x-1.5">
            <span>📋</span>
            <span>受控敏感工具清单 (在敏感确认模式下强制提示授权)</span>
          </div>
          <div class="flex flex-wrap gap-2">
            <div
              v-for="tool in settingsStore.sensitiveTools"
              :key="tool"
              class="px-2.5 py-1 rounded-lg bg-black/40 border border-white/[0.08] text-[11px] text-zinc-300 flex items-center space-x-1.5 font-mono"
            >
              <span class="text-amber-400 text-xs">⚠️</span>
              <span>{{ tool }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- Tab 2: MCP (Model Context Protocol) 服务器矩阵 -->
    <!-- ============================================================== -->
    <div v-show="activeTab === 'mcp'" class="space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-sm font-bold text-white flex items-center space-x-2">
            <span>🔌</span>
            <span>已注册 MCP 服务器集群 (MCP Registry)</span>
          </h2>
          <p class="text-xs text-zinc-400 mt-0.5">
            遵循行业开放标准 MCP 协议，可动态挂载标准金融行情中台与第三方外部数据源
          </p>
        </div>
        <button
          @click="showAddMcpModal = true"
          class="px-3 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-semibold text-xs flex items-center space-x-1.5 transition-all shadow-md cursor-pointer"
        >
          <span>＋</span>
          <span>添加自定义 MCP</span>
        </button>
      </div>

      <!-- MCP 分层卡片列表 (4 大治理分区：行情中台、用户专属数据、扩展第三方、超管系统级运维) -->
      <div class="space-y-8">
        <!-- ======================================================= -->
        <!-- 1. 金融行情数据中台 MCP 服务 (mcp-stock) -->
        <!-- ======================================================= -->
        <div class="space-y-3.5">
          <div class="flex items-center justify-between px-1">
            <h3 class="text-sm font-bold text-sky-400 flex items-center space-x-2">
              <span>📈</span>
              <span>金融行情数据 MCP 服务 (mcp-stock)</span>
            </h3>
            <div class="flex items-center space-x-2">
              <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20">
                系统全局标准中台 · 高性能高并发缓存
              </span>
            </div>
          </div>

          <div
            v-if="stockServer"
            class="p-5 rounded-2xl bg-[#141418] border border-sky-500/20 shadow-sm space-y-4"
          >
            <!-- 服务基本信息与总控开关 -->
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
              <div class="space-y-1">
                <div class="flex items-center space-x-2.5">
                  <span class="text-base">🚀</span>
                  <span class="font-bold text-sm text-white">{{ stockServer.name }}</span>
                  <span
                    class="px-2 py-0.5 rounded text-[10px] font-mono font-bold"
                    :class="stockServer.status === 'CONNECTED' ? 'bg-sky-500/15 text-sky-300 border border-sky-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                  >
                    ● {{ stockServer.status }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-sky-500/10 text-sky-300 border border-sky-500/20 font-mono">
                    金融行情中台
                  </span>
                </div>
                <p class="text-xs text-zinc-400 leading-relaxed">{{ stockServer.description }}</p>
                <div class="text-[11px] font-mono text-zinc-500 flex items-center space-x-3 pt-0.5">
                  <span>服务端点: <strong class="text-sky-300">{{ stockServer.url || 'http://localhost:8050/mcp/stock' }}</strong></span>
                  <span>·</span>
                  <span>已激活工具: <strong class="text-sky-300">{{ stockServer.active_tools_count ?? stockServer.tools_count }}</strong> / {{ stockServer.tools_count }}</span>
                </div>
              </div>

              <!-- 右侧控制区 -->
              <div class="flex items-center space-x-3 shrink-0">
                <button
                  @click="openDetailModal(stockServer)"
                  class="px-2.5 py-1 rounded-xl bg-sky-500/10 hover:bg-sky-500/20 text-sky-300 border border-sky-500/30 text-xs font-medium cursor-pointer transition-colors"
                >
                  📖 查看服务能力架构
                </button>
                <button
                  @click="handleToggleMcp(stockServer)"
                  :class="[
                    'w-11 h-6 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                    stockServer.enabled ? 'bg-sky-500' : 'bg-zinc-700',
                  ]"
                  :title="stockServer.enabled ? '点击挂起/断开该服务' : '点击挂载/启用该服务'"
                >
                  <div
                    :class="[
                      'bg-white w-5 h-5 rounded-full shadow-md transform transition-transform duration-200',
                      stockServer.enabled ? 'translate-x-5' : 'translate-x-0',
                    ]"
                  ></div>
                </button>
              </div>
            </div>

            <!-- 工具与能力精细化矩阵 (每个工具独立开关与参数列表) -->
            <div class="space-y-2">
              <div class="flex items-center justify-between text-xs text-zinc-400 font-semibold px-1">
                <span>包含的 {{ stockServer.tools_count }} 项金融行情工具与参数定义 (支持逐一精细化控制):</span>
                <span class="text-[10px] text-zinc-500 font-normal">点击开关可精准停用/激活对应能力</span>
              </div>

              <div class="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
                <div
                  v-for="tool in stockServer.tools"
                  :key="tool.name"
                  :class="[
                    'p-3 rounded-xl border transition-all space-y-2',
                    tool.enabled && stockServer.enabled
                      ? 'bg-white/[0.02] border-sky-500/20 hover:border-sky-500/40'
                      : 'bg-black/30 border-white/[0.04] opacity-60'
                  ]"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-mono text-xs font-bold" :class="tool.enabled && stockServer.enabled ? 'text-sky-300' : 'text-zinc-400'">
                        {{ tool.name }}
                      </span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium" :class="tool.enabled && stockServer.enabled ? 'bg-sky-500/15 text-sky-300' : 'bg-zinc-700 text-zinc-400'">
                        {{ tool.enabled && stockServer.enabled ? '● 已激活' : '⏹ 已停用' }}
                      </span>
                    </div>

                    <!-- 单个工具独立开关 -->
                    <button
                      @click.stop="handleToggleTool(stockServer, tool)"
                      :class="[
                        'w-8 h-4.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        tool.enabled ? 'bg-sky-500' : 'bg-zinc-700'
                      ]"
                      :title="tool.enabled ? '点击禁用该工具' : '点击启用该工具'"
                    >
                      <div
                        :class="[
                          'bg-white w-3.5 h-3.5 rounded-full shadow-sm transform transition-transform duration-200',
                          tool.enabled ? 'translate-x-3.5' : 'translate-x-0'
                        ]"
                      ></div>
                    </button>
                  </div>

                  <p class="text-[11px] text-zinc-300 leading-relaxed">{{ tool.description || '无详细功能描述' }}</p>

                  <!-- 工具入参列表 -->
                  <div v-if="getToolParams(tool.parameters).length > 0" class="pt-1.5 border-t border-white/[0.04] space-y-1">
                    <div class="text-[10px] text-zinc-500 font-medium">支持入参:</div>
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="param in getToolParams(tool.parameters)"
                        :key="param.name"
                        class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-black/40 border border-white/[0.06] text-zinc-300 flex items-center space-x-1"
                        :title="`${param.name} (${param.type}): ${param.description || '无说明'}`"
                      >
                        <strong :class="param.required ? 'text-amber-300' : 'text-zinc-400'">{{ param.name }}</strong>
                        <span class="text-zinc-500 text-[9px]">({{ param.type }}{{ param.required ? ', 必选' : '' }})</span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ======================================================= -->
        <!-- 2. 用户专属数据 MCP 服务 (mcp-user) -->
        <!-- ======================================================= -->
        <div class="space-y-3.5">
          <div class="flex items-center justify-between px-1">
            <h3 class="text-sm font-bold text-violet-400 flex items-center space-x-2">
              <span>👤</span>
              <span>用户专属数据 MCP 服务 (mcp-user)</span>
            </h3>
            <div class="flex items-center space-x-2">
              <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20">
                JWT Token 身份隔离 · 用户自主启停控制
              </span>
            </div>
          </div>

          <div
            v-if="userServer"
            class="p-5 rounded-2xl bg-[#141418] border border-violet-500/20 shadow-sm space-y-4"
          >
            <!-- 服务基本信息与总控开关 -->
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
              <div class="space-y-1">
                <div class="flex items-center space-x-2.5">
                  <span class="text-base">🚀</span>
                  <span class="font-bold text-sm text-white">{{ userServer.name }}</span>
                  <span
                    class="px-2 py-0.5 rounded text-[10px] font-mono font-bold"
                    :class="userServer.status === 'CONNECTED' ? 'bg-violet-500/15 text-violet-300 border border-violet-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                  >
                    ● {{ userServer.status }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-violet-500/10 text-violet-300 border border-violet-500/20 font-mono">
                    私有数据隔离
                  </span>
                </div>
                <p class="text-xs text-zinc-400 leading-relaxed">{{ userServer.description }}</p>
                <div class="text-[11px] font-mono text-zinc-500 flex items-center space-x-3 pt-0.5">
                  <span>服务端点: <strong class="text-violet-300">{{ userServer.url || 'http://localhost:8050/mcp/user' }}</strong></span>
                  <span>·</span>
                  <span>已激活工具: <strong class="text-violet-300">{{ userServer.active_tools_count ?? userServer.tools_count }}</strong> / {{ userServer.tools_count }}</span>
                </div>
              </div>

              <!-- 右侧控制区 -->
              <div class="flex items-center space-x-3 shrink-0">
                <button
                  @click="openDetailModal(userServer)"
                  class="px-2.5 py-1 rounded-xl bg-violet-500/10 hover:bg-violet-500/20 text-violet-300 border border-violet-500/30 text-xs font-medium cursor-pointer transition-colors"
                >
                  📖 查看服务能力架构
                </button>
                <button
                  @click="handleToggleMcp(userServer)"
                  :class="[
                    'w-11 h-6 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                    userServer.enabled ? 'bg-violet-500' : 'bg-zinc-700',
                  ]"
                  :title="userServer.enabled ? '点击断开个人私有数据访问' : '点击授权开启个人数据访问'"
                >
                  <div
                    :class="[
                      'bg-white w-5 h-5 rounded-full shadow-md transform transition-transform duration-200',
                      userServer.enabled ? 'translate-x-5' : 'translate-x-0',
                    ]"
                  ></div>
                </button>
              </div>
            </div>

            <!-- 工具与能力精细化矩阵 -->
            <div class="space-y-2">
              <div class="flex items-center justify-between text-xs text-zinc-400 font-semibold px-1">
                <span>包含的 {{ userServer.tools_count }} 项用户专属数据工具 (支持自主启停与参数透视):</span>
                <span class="text-[10px] text-zinc-500 font-normal">支持普通量化用户自主自由开关</span>
              </div>

              <div class="grid grid-cols-1 lg:grid-cols-3 gap-2.5">
                <div
                  v-for="tool in userServer.tools"
                  :key="tool.name"
                  :class="[
                    'p-3 rounded-xl border transition-all space-y-2',
                    tool.enabled && userServer.enabled
                      ? 'bg-white/[0.02] border-violet-500/20 hover:border-violet-500/40'
                      : 'bg-black/30 border-white/[0.04] opacity-60'
                  ]"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-mono text-xs font-bold" :class="tool.enabled && userServer.enabled ? 'text-violet-300' : 'text-zinc-400'">
                        {{ tool.name }}
                      </span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium" :class="tool.enabled && userServer.enabled ? 'bg-violet-500/15 text-violet-300' : 'bg-zinc-700 text-zinc-400'">
                        {{ tool.enabled && userServer.enabled ? '● 已激活' : '⏹ 已停用' }}
                      </span>
                    </div>

                    <!-- 单个工具独立开关 -->
                    <button
                      @click.stop="handleToggleTool(userServer, tool)"
                      :class="[
                        'w-8 h-4.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        tool.enabled ? 'bg-violet-500' : 'bg-zinc-700'
                      ]"
                      :title="tool.enabled ? '点击禁用该工具' : '点击启用该工具'"
                    >
                      <div
                        :class="[
                          'bg-white w-3.5 h-3.5 rounded-full shadow-sm transform transition-transform duration-200',
                          tool.enabled ? 'translate-x-3.5' : 'translate-x-0'
                        ]"
                      ></div>
                    </button>
                  </div>

                  <p class="text-[11px] text-zinc-300 leading-relaxed">{{ tool.description || '无详细功能描述' }}</p>

                  <!-- 工具入参列表 -->
                  <div v-if="getToolParams(tool.parameters).length > 0" class="pt-1.5 border-t border-white/[0.04] space-y-1">
                    <div class="text-[10px] text-zinc-500 font-medium">支持入参:</div>
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="param in getToolParams(tool.parameters)"
                        :key="param.name"
                        class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-black/40 border border-white/[0.06] text-zinc-300 flex items-center space-x-1"
                      >
                        <strong :class="param.required ? 'text-amber-300' : 'text-zinc-400'">{{ param.name }}</strong>
                        <span class="text-zinc-500 text-[9px]">({{ param.type }})</span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ======================================================= -->
        <!-- 3. 超级管理员系统级运维工具调用 (admin) -->
        <!-- ======================================================= -->
        <div v-if="authStore.isAdmin" class="space-y-3.5">
          <div class="flex items-center justify-between px-1">
            <h3 class="text-sm font-bold text-rose-400 flex items-center space-x-2">
              <span>🛠️</span>
              <span>超级管理员系统级运维工具调用 (admin)</span>
            </h3>
            <span class="text-[11px] font-mono text-rose-400 bg-rose-500/10 px-2.5 py-0.5 rounded border border-rose-500/20 font-bold">
              超管专属治理矩阵 · 严格沙箱鉴权
            </span>
          </div>

          <div
            v-if="adminServer"
            class="p-5 rounded-2xl bg-[#141418] border border-rose-500/25 shadow-sm space-y-4"
          >
            <!-- 基本信息与超管总开关 -->
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
              <div class="space-y-1">
                <div class="flex items-center space-x-2.5">
                  <span class="text-base">⚡</span>
                  <span class="font-bold text-sm text-rose-200">{{ adminServer.name }}</span>
                  <span
                    class="px-2 py-0.5 rounded text-[10px] font-mono font-bold"
                    :class="adminServer.status === 'CONNECTED' ? 'bg-rose-500/15 text-rose-300 border border-rose-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                  >
                    ● {{ adminServer.status }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-rose-500/10 text-rose-300 border border-rose-500/20 font-mono">
                    系统级运维治理
                  </span>
                </div>
                <p class="text-xs text-zinc-400 leading-relaxed">{{ adminServer.description }}</p>
                <div class="text-[11px] font-mono text-zinc-500 flex items-center space-x-3 pt-0.5">
                  <span>管控范围: <strong class="text-rose-300">宿主机 Shell 终端 · 源码读写 · Docker 容器治理 · 服务运维</strong></span>
                  <span>·</span>
                  <span>已激活工具: <strong class="text-rose-300">{{ adminServer.active_tools_count ?? adminServer.tools_count }}</strong> / {{ adminServer.tools_count }}</span>
                </div>
              </div>

              <!-- 超管总开关 -->
              <div class="flex items-center space-x-3 shrink-0">
                <button
                  @click="openDetailModal(adminServer)"
                  class="px-2.5 py-1 rounded-xl bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-medium cursor-pointer transition-colors"
                >
                  📖 查看运维能力
                </button>
                <button
                  @click="handleToggleMcp(adminServer)"
                  :class="[
                    'w-11 h-6 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                    adminServer.enabled ? 'bg-rose-500' : 'bg-zinc-700',
                  ]"
                  :title="adminServer.enabled ? '点击禁用系统级运维工具' : '点击启用系统级运维工具'"
                >
                  <div
                    :class="[
                      'bg-white w-5 h-5 rounded-full shadow-md transform transition-transform duration-200',
                      adminServer.enabled ? 'translate-x-5' : 'translate-x-0',
                    ]"
                  ></div>
                </button>
              </div>
            </div>

            <!-- 8 项运维工具精细化矩阵 -->
            <div class="space-y-2">
              <div class="flex items-center justify-between text-xs text-zinc-400 font-semibold px-1">
                <span>包含的 {{ adminServer.tools_count }} 项系统级运维治理工具 (每个工具均支持独立开关停用):</span>
                <span class="text-[10px] text-zinc-500 font-normal">支持超管精确控制 Shell 或源码修改权限</span>
              </div>

              <div class="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
                <div
                  v-for="tool in adminServer.tools"
                  :key="tool.name"
                  :class="[
                    'p-3 rounded-xl border transition-all space-y-2',
                    tool.enabled && adminServer.enabled
                      ? 'bg-white/[0.02] border-rose-500/20 hover:border-rose-500/40'
                      : 'bg-black/30 border-white/[0.04] opacity-60'
                  ]"
                >
                  <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                      <span class="font-mono text-xs font-bold" :class="tool.enabled && adminServer.enabled ? 'text-rose-300' : 'text-zinc-400'">
                        {{ tool.name }}
                      </span>
                      <span class="px-1.5 py-0.2 rounded text-[9px] font-medium" :class="tool.enabled && adminServer.enabled ? 'bg-rose-500/15 text-rose-300' : 'bg-zinc-700 text-zinc-400'">
                        {{ tool.enabled && adminServer.enabled ? '● 已激活' : '⏹ 已停用' }}
                      </span>
                    </div>

                    <!-- 单个工具独立开关 -->
                    <button
                      @click.stop="handleToggleTool(adminServer, tool)"
                      :class="[
                        'w-8 h-4.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        tool.enabled ? 'bg-rose-500' : 'bg-zinc-700'
                      ]"
                      :title="tool.enabled ? '点击停用该运维工具' : '点击启用该运维工具'"
                    >
                      <div
                        :class="[
                          'bg-white w-3.5 h-3.5 rounded-full shadow-sm transform transition-transform duration-200',
                          tool.enabled ? 'translate-x-3.5' : 'translate-x-0'
                        ]"
                      ></div>
                    </button>
                  </div>

                  <p class="text-[11px] text-zinc-300 leading-relaxed">{{ tool.description || '无详细功能描述' }}</p>

                  <!-- 工具入参列表 -->
                  <div v-if="getToolParams(tool.parameters).length > 0" class="pt-1.5 border-t border-white/[0.04] space-y-1">
                    <div class="text-[10px] text-zinc-500 font-medium">支持入参:</div>
                    <div class="flex flex-wrap gap-1">
                      <span
                        v-for="param in getToolParams(tool.parameters)"
                        :key="param.name"
                        class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-black/40 border border-white/[0.06] text-zinc-300 flex items-center space-x-1"
                      >
                        <strong :class="param.required ? 'text-rose-300' : 'text-zinc-400'">{{ param.name }}</strong>
                        <span class="text-zinc-500 text-[9px]">({{ param.type }})</span>
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ======================================================= -->
        <!-- 4. 扩展与第三方 MCP 服务 (other / 之后加载的，排在最后) -->
        <!-- ======================================================= -->
        <div class="space-y-3.5">
          <div class="flex items-center justify-between px-1">
            <h3 class="text-sm font-bold text-amber-400 flex items-center space-x-2">
              <span>🧩</span>
              <span>扩展与第三方 MCP 服务 (other)</span>
            </h3>
            <span class="text-[11px] font-mono text-zinc-500">{{ customServers.length }} 个外部扩展服务</span>
          </div>

          <div v-if="customServers.length > 0" class="space-y-3">
            <div
              v-for="server in customServers"
              :key="server.name"
              class="p-5 rounded-2xl bg-[#141418] border border-amber-500/20 shadow-sm space-y-4"
            >
              <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
                <div class="space-y-1">
                  <div class="flex items-center space-x-2.5">
                    <span class="text-base">🚀</span>
                    <span class="font-bold text-sm text-white">{{ server.name }}</span>
                    <span
                      class="px-2 py-0.5 rounded text-[10px] font-mono font-bold"
                      :class="server.status === 'CONNECTED' ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                    >
                      ● {{ server.status }}
                    </span>
                    <span class="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-300 border border-amber-500/20 font-mono">
                      {{ server.type === 'http' ? '远程 HTTP' : '本地命令行 (Stdio)' }}
                    </span>
                  </div>
                  <p class="text-xs text-zinc-400">{{ server.description || '自定义扩展 MCP' }}</p>
                  <div class="text-[11px] font-mono text-zinc-500">
                    端点/命令: {{ server.url || (server.command + ' ' + (server.args || []).join(' ')) }}
                  </div>
                </div>

                <div class="flex items-center space-x-3 shrink-0">
                  <button
                    @click="openDetailModal(server)"
                    class="px-2.5 py-1 rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-medium cursor-pointer transition-colors"
                  >
                    📖 查看能力
                  </button>
                  <button
                    @click="handleToggleMcp(server)"
                    :class="[
                      'w-11 h-6 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                      server.enabled ? 'bg-amber-500' : 'bg-zinc-700',
                    ]"
                  >
                    <div
                      :class="[
                        'bg-white w-5 h-5 rounded-full shadow-md transform transition-transform duration-200',
                        server.enabled ? 'translate-x-5' : 'translate-x-0',
                      ]"
                    ></div>
                  </button>
                </div>
              </div>

              <!-- 工具列表 -->
              <div v-if="server.tools && server.tools.length > 0" class="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
                <div
                  v-for="tool in server.tools"
                  :key="tool.name"
                  class="p-3 rounded-xl bg-white/[0.02] border border-amber-500/20 space-y-2"
                >
                  <div class="flex items-center justify-between">
                    <span class="font-mono text-xs text-amber-300 font-bold">{{ tool.name }}</span>
                    <button
                      @click.stop="handleToggleTool(server, tool)"
                      :class="[
                        'w-8 h-4.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                        tool.enabled ? 'bg-amber-500' : 'bg-zinc-700'
                      ]"
                    >
                      <div
                        :class="[
                          'bg-white w-3.5 h-3.5 rounded-full shadow-sm transform transition-transform duration-200',
                          tool.enabled ? 'translate-x-3.5' : 'translate-x-0'
                        ]"
                      ></div>
                    </button>
                  </div>
                  <p class="text-[11px] text-zinc-300">{{ tool.description }}</p>
                </div>
              </div>
            </div>
          </div>
          <div
            v-else
            class="p-6 rounded-2xl bg-[#141418] border border-dashed border-white/[0.08] text-center text-xs text-zinc-500 space-y-1.5"
          >
            <div class="text-sm">暂无第三方扩展 MCP 服务</div>
            <div class="text-[11px] text-zinc-500">点击右上角「＋ 添加自定义 MCP」可接入外部天气、研报、知识库或自建脚本服务</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============================================================== -->
    <!-- Tab 3: 大模型与运行时参数调优 (Runtime Tuning) -->
    <!-- ============================================================== -->
    <div v-show="activeTab === 'runtime'" class="space-y-6">
      <div class="p-5 rounded-2xl bg-[#141418] border border-white/[0.08] shadow-sm space-y-5">
        <div>
          <h2 class="text-sm font-bold text-white flex items-center space-x-2">
            <span>⚡</span>
            <span>大模型驱动与推理参数 (Model & Agent Tuning)</span>
          </h2>
          <p class="text-xs text-zinc-400 mt-0.5">
            调节 ReAct 思考循环步数、采样随机度与工具观察截断 Token 水位
          </p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          <!-- 默认基座模型 -->
          <div class="space-y-1.5">
            <label class="text-xs font-semibold text-zinc-300">默认主控模型 (Default Model):</label>
            <select
              v-model="settingsStore.modelConfig.default_model"
              class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500/50"
            >
              <option value="minimax/minimax-m3:free">MiniMax M3 (Free 官方渠道 · 推荐)</option>
              <option value="gemini-flash-lite-latest">Gemini 2.0 Flash Lite (极速低时延)</option>
              <option value="claude">Claude Sonnet 4.6 (深度长文本逻辑推理 · VIP)</option>
              <option value="deepseek">DeepSeek V3 / R1 本机蒸馏</option>
            </select>
          </div>

          <!-- 采样温度 Temperature -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="text-xs font-semibold text-zinc-300">采样温度 (Temperature):</label>
              <span class="text-xs font-mono text-amber-300">{{ settingsStore.modelConfig.temperature }}</span>
            </div>
            <input
              type="range"
              min="0.0"
              max="1.0"
              step="0.05"
              v-model.number="settingsStore.modelConfig.temperature"
              class="w-full accent-amber-400"
            />
            <div class="flex items-center justify-between text-[10px] text-zinc-500">
              <span>0.0 (极客严谨精准)</span>
              <span>1.0 (高创意探索)</span>
            </div>
          </div>

          <!-- 最大思考推演轮数 (Max Steps) -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="text-xs font-semibold text-zinc-300">推演步数上限 (Max Agent Steps):</label>
              <span class="text-xs font-mono" :class="settingsStore.modelConfig.max_steps === 0 ? 'text-emerald-400 font-bold' : 'text-amber-300'">
                {{ settingsStore.modelConfig.max_steps === 0 ? '无限制 · 自然终结 (对标 DSH)' : `${settingsStore.modelConfig.max_steps} 步` }}
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="50"
              step="5"
              v-model.number="settingsStore.modelConfig.max_steps"
              class="w-full accent-emerald-400"
            />
            <div class="flex items-center justify-between text-[10px] text-zinc-500">
              <span class="text-emerald-400 font-medium">0 步 (无限制 · 推荐)</span>
              <span>25 步</span>
              <span>50 步 (高位预算)</span>
            </div>
            <p class="text-[10px] text-zinc-400 leading-relaxed">
              💡 设为 0 表示解除人为硬性限制（对标 DSH 架构），由模型自主推演至完成并输出回复时自然结束；由内置的 RepeatToolGuard 守卫和上下文剪枝机制兜底。
            </p>
          </div>

          <!-- TokenGovernor 截断字符上限 -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="text-xs font-semibold text-zinc-300">工具观察截断预算 (Max Observation Chars):</label>
              <span class="text-xs font-mono text-amber-300">{{ settingsStore.modelConfig.max_observation_chars }} 字符</span>
            </div>
            <input
              type="range"
              min="1500"
              max="8000"
              step="500"
              v-model.number="settingsStore.modelConfig.max_observation_chars"
              class="w-full accent-amber-400"
            />
            <div class="flex items-center justify-between text-[10px] text-zinc-500">
              <span>1500 (极致省 Token)</span>
              <span>8000 (超大财报上下文)</span>
            </div>
          </div>
        </div>

        <div class="pt-3 border-t border-white/[0.06] flex items-center justify-end">
          <button
            @click="handleSaveRuntime"
            :disabled="settingsStore.saving"
            class="px-4 py-2 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 hover:from-red-600 hover:to-amber-600 text-white font-semibold text-xs flex items-center space-x-1.5 transition-all shadow-md cursor-pointer disabled:opacity-40"
          >
            <span>💾</span>
            <span>{{ settingsStore.saving ? '保存中...' : '保存模型与运行调优参数' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 添加自定义 MCP 模态窗 -->
    <div
      v-if="showAddMcpModal"
      class="fixed inset-0 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-fade"
      :style="{ zIndex: addMcpZIndex }"
    >
      <div class="w-full max-w-md rounded-2xl bg-[#141418] border border-white/[0.12] shadow-2xl p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-bold text-white flex items-center space-x-2">
            <span>＋</span>
            <span>添加自定义 MCP 服务器 (Stdio)</span>
          </h3>
          <button @click="showAddMcpModal = false" class="text-zinc-500 hover:text-white text-xs cursor-pointer">
            ✕
          </button>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <label class="block text-zinc-300 font-medium mb-1">服务标识名 (Server Name):</label>
            <input
              v-model="newMcp.name"
              placeholder="例如: custom-tools-mcp"
              class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-1.5 text-white"
            />
          </div>

          <div class="grid grid-cols-3 gap-2">
            <div>
              <label class="block text-zinc-300 font-medium mb-1">可执行程序:</label>
              <input
                v-model="newMcp.command"
                placeholder="uv / node"
                class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-1.5 text-white font-mono"
              />
            </div>
            <div class="col-span-2">
              <label class="block text-zinc-300 font-medium mb-1">运行参数 (空格分隔):</label>
              <input
                v-model="newMcp.argsText"
                placeholder="run python server.py"
                class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-1.5 text-white font-mono"
              />
            </div>
          </div>

          <div>
            <label class="block text-zinc-300 font-medium mb-1">工作目录 Cwd (可选):</label>
            <input
              v-model="newMcp.cwd"
              placeholder="留空默认项目工作区"
              class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-1.5 text-white font-mono"
            />
          </div>

          <div>
            <label class="block text-zinc-300 font-medium mb-1">描述信息:</label>
            <input
              v-model="newMcp.description"
              placeholder="自定义数据源或通用工具"
              class="w-full bg-black/40 border border-white/[0.1] rounded-xl px-3 py-1.5 text-white"
            />
          </div>
        </div>

        <div class="flex items-center justify-end space-x-2 pt-2 border-t border-white/[0.06]">
          <button
            @click="showAddMcpModal = false"
            class="px-3 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer"
          >
            取消
          </button>
          <button
            @click="handleCreateMcp"
            class="px-4 py-1.5 rounded-xl bg-gradient-to-r from-red-500 to-amber-500 text-white font-semibold text-xs cursor-pointer"
          >
            确认添加
          </button>
        </div>
      </div>
    </div>

    <!-- 模态框: MCP 服务详细能力架构与白皮书 (detailModalServer) -->
    <div
      v-if="detailModalServer"
      class="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4"
      :style="{ zIndex: detailModalZIndex }"
    >
      <div class="bg-[#181924] border border-white/[0.12] rounded-3xl w-full max-w-3xl max-h-[88vh] overflow-hidden flex flex-col shadow-2xl">
        <!-- 头部 -->
        <div class="px-6 py-4 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
          <div class="flex items-center space-x-3">
            <span class="text-xl">📖</span>
            <div>
              <div class="flex items-center space-x-2">
                <h3 class="text-sm font-bold text-white">{{ detailModalServer.name }}</h3>
                <span
                  class="px-2 py-0.5 rounded text-[10px] font-mono font-bold"
                  :class="detailModalServer.status === 'CONNECTED' ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                >
                  ● {{ detailModalServer.status }}
                </span>
                <span class="px-2 py-0.5 rounded text-[10px] bg-white/[0.06] text-zinc-300 font-mono">
                  {{ detailModalServer.type === 'http' ? 'Streamable HTTP' : (detailModalServer.type === 'internal' ? '系统内部工具' : 'Stdio 管道') }}
                </span>
              </div>
              <p class="text-[11px] text-zinc-400 mt-0.5">{{ detailModalServer.description }}</p>
            </div>
          </div>
          <button
            @click="closeDetailModal"
            class="text-zinc-400 hover:text-white p-1.5 rounded-lg hover:bg-white/[0.08] text-sm cursor-pointer transition-colors"
          >
            ✕
          </button>
        </div>

        <!-- 架构与端点详情 -->
        <div class="p-6 space-y-5 overflow-y-auto flex-1">
          <!-- 协议架构元信息 -->
          <div class="grid grid-cols-2 md:grid-cols-4 gap-2.5 text-xs">
            <div class="p-3 rounded-xl bg-black/40 border border-white/[0.06] space-y-1">
              <div class="text-[10px] text-zinc-500">传输传输层:</div>
              <div class="font-mono text-zinc-200 font-semibold">{{ detailModalServer.type === 'http' ? 'Streamable HTTP' : '系统内置/管道' }}</div>
            </div>
            <div class="p-3 rounded-xl bg-black/40 border border-white/[0.06] space-y-1">
              <div class="text-[10px] text-zinc-500">挂载端点:</div>
              <div class="font-mono text-sky-300 font-semibold truncate">{{ detailModalServer.url || '宿主机内核' }}</div>
            </div>
            <div class="p-3 rounded-xl bg-black/40 border border-white/[0.06] space-y-1">
              <div class="text-[10px] text-zinc-500">隔离模型:</div>
              <div class="font-mono text-violet-300 font-semibold">{{ detailModalServer.name === 'mcp-user' ? 'JWT Token 独立会话' : (detailModalServer.name === 'admin-system-tools' ? '超管沙箱' : '全局共享') }}</div>
            </div>
            <div class="p-3 rounded-xl bg-black/40 border border-white/[0.06] space-y-1">
              <div class="text-[10px] text-zinc-500">工具就绪度:</div>
              <div class="font-mono text-emerald-300 font-semibold">
                {{ detailModalServer.active_tools_count ?? detailModalServer.tools_count }} / {{ detailModalServer.tools_count }} 工具已激活
              </div>
            </div>
          </div>

          <!-- 工具清单与参数白皮书 -->
          <div class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-xs font-bold text-white flex items-center space-x-1.5">
                <span>⚡</span>
                <span>支持的能力清单与参数 Schema 白皮书 (共 {{ detailModalServer.tools_count }} 项能力)</span>
              </h4>
              <span class="text-[10px] text-zinc-500">可直接在此弹窗中开启/关闭工具</span>
            </div>

            <div class="space-y-2.5">
              <div
                v-for="tool in detailModalServer.tools"
                :key="tool.name"
                class="p-3.5 rounded-2xl bg-white/[0.02] border border-white/[0.08] hover:border-white/[0.15] transition-all space-y-2.5"
              >
                <div class="flex items-center justify-between">
                  <div class="flex items-center space-x-2.5">
                    <span class="font-mono text-xs font-bold text-white">{{ tool.name }}</span>
                    <span class="px-2 py-0.2 rounded text-[9px] font-mono bg-white/[0.06] text-zinc-300">
                      {{ tool.category }}
                    </span>
                    <span
                      class="px-2 py-0.2 rounded text-[9px] font-mono font-medium"
                      :class="tool.enabled && detailModalServer.enabled ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-700 text-zinc-400'"
                    >
                      {{ tool.enabled && detailModalServer.enabled ? '● 运行中' : '⏹ 已停用' }}
                    </span>
                  </div>

                  <!-- 独立开关 -->
                  <button
                    @click="handleToggleTool(detailModalServer, tool)"
                    :class="[
                      'w-9 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-200',
                      tool.enabled ? 'bg-emerald-500' : 'bg-zinc-700',
                    ]"
                  >
                    <div
                      :class="[
                        'bg-white w-4 h-4 rounded-full shadow-md transform transition-transform duration-200',
                        tool.enabled ? 'translate-x-4' : 'translate-x-0',
                      ]"
                    ></div>
                  </button>
                </div>

                <p class="text-xs text-zinc-300 leading-relaxed">{{ tool.description || '无功能描述' }}</p>

                <!-- 参数规范表格 -->
                <div v-if="getToolParams(tool.parameters).length > 0" class="p-2.5 rounded-xl bg-black/40 border border-white/[0.04] space-y-1.5">
                  <div class="text-[10px] text-zinc-400 font-semibold">入参规范 (Input Schema):</div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-1.5">
                    <div
                      v-for="p in getToolParams(tool.parameters)"
                      :key="p.name"
                      class="text-[10px] font-mono p-1.5 rounded bg-white/[0.02] border border-white/[0.03] flex items-start space-x-1.5"
                    >
                      <strong :class="p.required ? 'text-amber-300' : 'text-zinc-300'">{{ p.name }}</strong>
                      <span class="text-zinc-500">({{ p.type }}{{ p.required ? ', 必填' : ', 可选' }}):</span>
                      <span class="text-zinc-400 flex-1 truncate">{{ p.description || '无参数说明' }}</span>
                    </div>
                  </div>
                </div>
                <div v-else class="text-[10px] text-zinc-500 italic">无额外必填参数 (无需入参直接执行)</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部 -->
        <div class="px-6 py-3 border-t border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
          <span class="text-xs text-zinc-400">所有工具开关即时保存至云端运行时并立即生效</span>
          <button
            @click="closeDetailModal"
            class="px-4 py-1.5 rounded-xl bg-white/[0.08] hover:bg-white/[0.14] text-white text-xs font-semibold cursor-pointer transition-colors"
          >
            完成并关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
