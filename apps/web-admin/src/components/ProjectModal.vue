<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import {
  useCodexWorkspaceStore,
  type DiscoveredProjectItem,
  type FileSystemBrowseResult,
  type FileSystemItem,
} from '@/stores/codexWorkspace'
import { useModalLayer } from '@/stores/modalManager'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  (e: 'update:show', value: boolean): void
  (e: 'close'): void
  (e: 'mounted', project: any): void
}>()

const codexStore = useCodexWorkspaceStore()

// 接入统一弹窗层级治理，保证后弹出的弹窗层级在最顶层
const { zIndex, focusModal } = useModalLayer(
  'project-modal',
  () => props.show,
  () => close()
)

function close() {
  emit('update:show', false)
  emit('close')
}

// 提示气泡
const toastMsg = ref('')
let toastTimer: any = null
function showToast(msg: string) {
  toastMsg.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toastMsg.value = ''
  }, 2500)
}

// 模态框内部状态
const projectModalTab = ref<'server' | 'upload'>('server')
const serverSubTab = ref<'auto' | 'tree'>('auto')

// Tab 1: 服务端工程状态 (方案 A: 部署机智能探测 + 目录树挂载)
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

// 监听弹窗打开状态，自动探测工程
watch(
  () => props.show,
  (val) => {
    if (val) {
      loadDiscoveredProjects()
      if (!fsResult.value) {
        loadServerFs()
      }
    }
  }
)

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
    emit('mounted', proj)
    close()
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
    emit('mounted', { name, path })
    close()
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
      emit('mounted', proj)
      close()
      uploadFiles.value = []
      uploadZipFile.value = null
    } else {
      showToast('❌ 上传部署失败，请重试')
    }
  } catch (err) {
    showToast('❌ 上传异常')
  } finally {
    isUploading.value = false
  }
}
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div
        v-if="show"
        :style="{ zIndex }"
        class="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center p-4 sm:p-6 select-none animate-fadeIn"
        @click.self="close"
        @mousedown="focusModal"
      >
        <!-- 模态框主体卡片 -->
        <div
          class="relative w-full max-w-4xl max-h-[88vh] h-[720px] rounded-2xl bg-[#0f1118] border border-white/[0.12] shadow-2xl shadow-purple-950/40 flex flex-col overflow-hidden text-zinc-100 transform transition-all"
        >
          <!-- 提示 Toast -->
          <div
            v-if="toastMsg"
            class="absolute top-14 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-purple-600/90 text-white font-medium text-xs shadow-xl backdrop-blur-md animate-bounce"
          >
            {{ toastMsg }}
          </div>

          <!-- 1. 模态框顶栏 -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-white/[0.08] shrink-0 bg-white/[0.02]">
            <div class="flex items-center space-x-3">
              <div class="w-9 h-9 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center text-lg shadow-sm text-purple-300">
                📁
              </div>
              <div>
                <h3 class="text-sm font-bold text-white flex items-center space-x-2">
                  <span>挂载与导入量化工程项目</span>
                  <span class="text-[10px] font-normal px-2 py-0.5 rounded-full bg-white/[0.06] text-zinc-400 border border-white/[0.08]">
                    {{ fsResult?.system_info?.os === 'Linux' ? '🐧 Ubuntu 部署机节点' : '💻 当前服务节点' }}
                  </span>
                </h3>
                <p class="text-[11px] text-zinc-400">统一工程治理中心 · 支持部署机智能探测一键挂载 · 目录树浏览 · 访问机客户端上传</p>
              </div>
            </div>

            <button
              @click="close"
              class="w-8 h-8 rounded-lg hover:bg-white/[0.08] text-zinc-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              title="关闭 (Esc)"
            >
              ✕
            </button>
          </div>

          <!-- 2. 双 Tab 切换栏 -->
          <div class="flex items-center space-x-2 px-6 pt-3 pb-2.5 shrink-0 border-b border-white/[0.06] bg-black/20">
            <button
              @click="projectModalTab = 'server'"
              :class="[
                'flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all border',
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
                'flex items-center space-x-1.5 px-3.5 py-1.5 rounded-xl text-xs font-semibold cursor-pointer transition-all border',
                projectModalTab === 'upload'
                  ? 'bg-purple-500/20 text-purple-200 border-purple-500/40 shadow-xs'
                  : 'bg-white/[0.03] text-zinc-400 border-transparent hover:text-zinc-200 hover:bg-white/[0.06]'
              ]"
            >
              <span>💻</span>
              <span>访问机本地上传 (从当前电脑打包上传至部署机)</span>
            </button>
          </div>

          <!-- 3. Tab 1 内容：部署机工程管理 (智能探测 / 目录树) -->
          <div v-if="projectModalTab === 'server'" class="flex-1 flex flex-col min-h-0 px-6 py-4 space-y-3">
            <!-- 模式切换：智能探测工程 vs 目录树自定义浏览 -->
            <div class="flex items-center justify-between pb-1 shrink-0">
              <div class="flex items-center space-x-1 bg-black/40 p-1 rounded-xl border border-white/[0.08]">
                <button
                  @click="serverSubTab = 'auto'"
                  :class="[
                    'px-3.5 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all flex items-center space-x-1.5',
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
                    'px-3.5 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all flex items-center space-x-1.5',
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
                  class="px-3 py-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-zinc-300 hover:text-white text-xs cursor-pointer transition-colors flex items-center space-x-1.5 border border-white/[0.08]"
                  title="重新扫描部署机工程"
                >
                  <span :class="{'animate-spin': loadingDiscovered}">🔄</span>
                  <span>{{ loadingDiscovered ? '扫描中...' : '重新扫描' }}</span>
                </button>
              </div>
            </div>

            <!-- 子视图 1: 智能探测工程列表 (推荐 · 零路径手输) -->
            <div v-if="serverSubTab === 'auto'" class="flex-1 flex flex-col min-h-0 space-y-2.5">
              <div class="text-[11px] text-zinc-400 flex items-center justify-between shrink-0 px-1">
                <span>系统已自动为您扫描部署机常用目录下的量化与工程代码：</span>
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
                  系统已检查当前工作区根目录及其上层兄弟目录。如果您将代码放置在特殊路径，可切换至「目录树浏览」选取，或通过「访问机本地上传」上传本地工程。
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
              <div class="pt-2.5 border-t border-white/[0.04] flex items-center justify-between text-[11px] text-zinc-500">
                <span>💡 提示：点击「一键挂载」即可立即将该工程接入 Alpha Copilot，无需手动输入路径。</span>
                <button
                  @click="close"
                  class="px-3 py-1 rounded-lg bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
                >
                  关闭
                </button>
              </div>
            </div>

            <!-- 子视图 2: 目录树浏览 (自定义路径) -->
            <div v-else class="flex-1 flex flex-col min-h-0 space-y-3">
              <!-- 快捷入口与地址栏 -->
              <div class="space-y-2 shrink-0">
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
                  <div
                    v-if="fsResult?.parent_path"
                    @click="loadServerFs(fsResult.parent_path)"
                    class="flex items-center space-x-2 px-2.5 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-white hover:bg-white/[0.06] cursor-pointer transition-colors"
                  >
                    <span class="text-sm">↩️</span>
                    <span class="font-mono text-[11px]">.. (返回上一层目录)</span>
                  </div>

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
              <div class="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.06] space-y-2.5 shrink-0">
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
                      @click="close"
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

          <!-- 4. Tab 2 内容：从当前访问机客户端上传工程至部署机 -->
          <div v-else class="flex-1 flex flex-col min-h-0 px-6 py-4 space-y-3">
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
              class="flex-1 min-h-[180px] border-2 border-dashed border-white/[0.15] hover:border-purple-500/50 rounded-2xl bg-white/[0.02] hover:bg-purple-500/[0.03] transition-all flex flex-col items-center justify-center p-6 space-y-3 cursor-pointer group"
            >
              <div class="w-14 h-14 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-3xl group-hover:scale-110 transition-transform">
                🚀
              </div>
              <div class="text-center space-y-1">
                <div class="text-sm font-bold text-zinc-200 group-hover:text-purple-300 transition-colors">
                  点击选择访问机上的本地工程文件夹 (自动递归打包并上传)
                </div>
                <div class="text-[11px] text-zinc-500">
                  支持选择本地文件夹直接上传，或上传包含源码策略的 .zip 压缩包至远端部署机
                </div>
              </div>

              <div class="flex items-center space-x-3 pt-1">
                <button
                  type="button"
                  @click.stop="triggerUploadFolderPicker"
                  class="px-4 py-2 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 border border-purple-500/40 text-xs font-medium cursor-pointer transition-colors flex items-center space-x-1.5"
                >
                  <span>📁</span>
                  <span>选择本地文件夹</span>
                </button>
                <button
                  type="button"
                  @click.stop="triggerUploadZipPicker"
                  class="px-4 py-2 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 border border-white/[0.1] text-xs font-medium cursor-pointer transition-colors flex items-center space-x-1.5"
                >
                  <span>📦</span>
                  <span>上传 .zip 压缩包</span>
                </button>
              </div>
            </div>

            <!-- 已选择的待上传清单卡片 -->
            <div v-if="uploadFiles.length > 0 || uploadZipFile" class="p-3.5 rounded-xl bg-white/[0.03] border border-white/[0.08] space-y-2.5">
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
            <div class="flex items-center justify-end space-x-2 pt-1 border-t border-white/[0.04]">
              <button
                @click="close"
                class="px-3.5 py-1.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] text-zinc-300 text-xs cursor-pointer transition-colors"
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
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
  transform: scale(0.97);
}
</style>
