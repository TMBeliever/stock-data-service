<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAgentSettingsStore, type ExecutionMode, type McpServerItem } from '@/stores/agentSettings'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const settingsStore = useAgentSettingsStore()
const authStore = useAuthStore()

const activeTab = ref<'permissions' | 'mcp' | 'runtime'>('permissions')
const showAddMcpModal = ref(false)
const toastMsg = ref('')

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

      <!-- MCP 卡片列表 -->
      <div class="grid grid-cols-1 gap-4">
        <div
          v-for="server in settingsStore.mcpServers"
          :key="server.name"
          class="p-5 rounded-2xl bg-[#141418] border border-white/[0.08] shadow-sm space-y-3.5"
        >
          <div class="flex items-start justify-between">
            <div class="space-y-1">
              <div class="flex items-center space-x-2.5">
                <span class="text-base">🚀</span>
                <span class="font-bold text-sm text-white">{{ server.name }}</span>
                <span
                  class="px-2 py-0.5 rounded text-[9px] font-mono font-bold"
                  :class="server.status === 'CONNECTED' ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' : 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30'"
                >
                  ● {{ server.status }}
                </span>
                <span class="px-1.5 py-0.5 rounded text-[9px] bg-white/[0.04] text-zinc-400 font-mono">
                  {{ server.category }}
                </span>
              </div>
              <p class="text-xs text-zinc-400">{{ server.description }}</p>
            </div>
            <div class="text-right text-[11px] font-mono text-zinc-400">
              <span>提供 <strong class="text-amber-300">{{ server.tools_count }}</strong> 个工具</span>
            </div>
          </div>

          <!-- 启动指令与环境 -->
          <div class="p-2.5 rounded-xl bg-black/40 border border-white/[0.06] text-[11px] font-mono text-zinc-300 space-y-1">
            <div class="text-zinc-500 text-[10px]">启动进程指令 (Process Command):</div>
            <div class="text-amber-200/90 truncate">
              $ {{ server.command }} {{ server.args.join(' ') }}
            </div>
            <div v-if="server.cwd" class="text-zinc-500 text-[10px] truncate pt-0.5">
              Cwd: {{ server.cwd }}
            </div>
          </div>

          <!-- 展开工具列表 -->
          <details class="group/mcp">
            <summary class="text-xs text-zinc-400 hover:text-zinc-200 cursor-pointer select-none flex items-center justify-between py-1">
              <span>查看此 MCP 提供的 {{ server.tools_count }} 个工具详情</span>
              <span class="text-[10px] group-open/mcp:rotate-180 transition-transform">▼</span>
            </summary>
            <div class="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 pt-2 border-t border-white/[0.06]">
              <div
                v-for="tool in server.tools"
                :key="tool.name"
                class="p-2 rounded-lg bg-white/[0.02] border border-white/[0.04] text-[11px] space-y-1"
              >
                <div class="font-mono font-semibold text-white flex items-center justify-between">
                  <span class="text-emerald-300">{{ tool.name }}</span>
                  <span class="text-[9px] px-1 rounded bg-white/[0.06] text-zinc-400">{{ tool.category }}</span>
                </div>
                <div class="text-[10px] text-zinc-400 truncate">{{ tool.description || '无详细说明' }}</div>
              </div>
            </div>
          </details>
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
              <option value="claude">Claude 3.7 Sonnet (深度长文本逻辑推理 · VIP)</option>
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
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs animate-fade"
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
  </div>
</template>
