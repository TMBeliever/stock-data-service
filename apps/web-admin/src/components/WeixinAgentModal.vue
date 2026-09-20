<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useModalLayer } from '@/stores/modalManager'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const authStore = useAuthStore()

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const { zIndex } = useModalLayer('weixin-agent-modal', isOpen, () => {
  closeModal()
})

const loading = ref(false)
const botInfo = ref<{
  online: boolean
  accountId?: string | null
  userId?: string | null
  boundUser?: { userId: string; username: string; boundAt: number } | null
} | null>(null)

const qrData = ref<{
  qrcode: string
  qrcodeImgContent: string
  qrDataUrl: string
} | null>(null)

const scanStatus = ref<'idle' | 'wait' | 'scaned' | 'confirmed' | 'expired'>('idle')
const statusTip = ref('请使用手机微信扫描二维码')
let pollTimer: any = null

function closeModal() {
  stopPolling()
  isOpen.value = false
}

// 轮询扫码状态
async function startPolling(qrcode: string) {
  stopPolling()
  scanStatus.value = 'wait'
  statusTip.value = '等待微信扫码授权...'

  const poll = async () => {
    if (!isOpen.value || scanStatus.value === 'confirmed') return

    try {
      const res = await fetch(`/api/v1/weixin/status?qrcode=${encodeURIComponent(qrcode)}`)
      if (!res.ok) return
      const json = await res.json()

      if (json.status === 'success' && json.data) {
        const s = json.data.status
        if (s === 'scaned') {
          scanStatus.value = 'scaned'
          statusTip.value = '📱 已扫描，请在手机微信上点击【确认登录】...'
        } else if (s === 'confirmed') {
          scanStatus.value = 'confirmed'
          statusTip.value = '🎉 授权成功！正在同步配置...'
          stopPolling()
          await fetchBotInfo()
          return
        } else if (s === 'expired') {
          scanStatus.value = 'expired'
          statusTip.value = '⏳ 二维码已过期，请点击重新刷新'
          stopPolling()
          return
        }
      }
    } catch (e) {
      // 轮询异常忽略
    }

    if (isOpen.value && scanStatus.value !== 'confirmed' && scanStatus.value !== 'expired') {
      pollTimer = setTimeout(poll, 2000)
    }
  }

  poll()
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

// 获取微信机器人状态
async function fetchBotInfo() {
  try {
    const res = await fetch('/api/v1/weixin/bot-info')
    if (res.ok) {
      const json = await res.json()
      if (json.status === 'success') {
        botInfo.value = json.data
      }
    }
  } catch (e) {
    // 忽略异常
  }
}

// 获取登录二维码
async function loadQRCode() {
  loading.value = true
  qrData.value = null
  scanStatus.value = 'idle'
  stopPolling()

  try {
    const headers: Record<string, string> = {}
    if (authStore.token) {
      headers['Authorization'] = `Bearer ${authStore.token}`
    }

    const res = await fetch('/api/v1/weixin/qrcode', { headers })
    if (res.ok) {
      const json = await res.json()
      if (json.status === 'success' && json.data) {
        if (json.data.alreadyOnline) {
          botInfo.value = json.data.botInfo
        } else {
          qrData.value = json.data
          startPolling(json.data.qrcode)
        }
      }
    }
  } catch (e) {
    statusTip.value = '加载二维码失败，请检查 weixin-bot 服务是否启动'
  } finally {
    loading.value = false
  }
}

// 重置会话上下文
const resetting = ref(false)
const resetToast = ref('')
async function handleResetSession() {
  resetting.value = true
  resetToast.value = ''
  try {
    const res = await fetch('/api/v1/weixin/reset-session', { method: 'POST' })
    if (res.ok) {
      resetToast.value = '✨ 当前微信会话上下文已重置！'
      setTimeout(() => {
        resetToast.value = ''
      }, 3000)
    }
  } catch (e) {
    resetToast.value = '重置失败，请稍后重试'
  } finally {
    resetting.value = false
  }
}

// 注销微信
const loggingOut = ref(false)
async function handleLogout() {
  loggingOut.value = true
  try {
    await fetch('/api/v1/weixin/logout', { method: 'POST' })
    botInfo.value = null
    await loadQRCode()
  } catch (e) {
    // 忽略
  } finally {
    loggingOut.value = false
  }
}

watch(
  () => props.modelValue,
  async (val) => {
    if (val) {
      await fetchBotInfo()
      if (!botInfo.value?.online) {
        await loadQRCode()
      }
    } else {
      stopPolling()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <transition name="modal-fade">
    <div
      v-if="isOpen"
      class="fixed inset-0 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md"
      :style="{ zIndex }"
      @click.self="closeModal"
    >
      <div
        class="relative w-full max-w-lg rounded-3xl bg-[#121216] border border-white/[0.12] shadow-2xl overflow-hidden p-6 sm:p-7 text-white animate-scale-up"
      >
        <!-- 背景流光装饰 -->
        <div class="absolute -top-24 -right-24 w-60 h-60 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="absolute -bottom-24 -left-24 w-60 h-60 bg-red-500/10 rounded-full blur-3xl pointer-events-none"></div>

        <!-- 顶部标题与关闭 -->
        <div class="flex items-center justify-between pb-4 border-b border-white/[0.08] relative z-10">
          <div class="flex items-center space-x-3">
            <div class="w-10 h-10 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20 text-xl">
              💬
            </div>
            <div>
              <div class="flex items-center space-x-2">
                <h3 class="text-base font-bold tracking-tight text-white">微信量化智能助理</h3>
                <span
                  v-if="botInfo?.online"
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                >
                  <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse mr-1"></span>
                  在线就绪
                </span>
                <span
                  v-else
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-zinc-500/15 text-zinc-400 border border-zinc-500/30"
                >
                  未连接
                </span>
              </div>
              <p class="text-xs text-zinc-400 mt-0.5">扫码直连，随时随地在手机微信进行量化投研</p>
            </div>
          </div>

          <button
            @click="closeModal"
            class="w-8 h-8 rounded-full bg-white/[0.06] hover:bg-white/[0.12] flex items-center justify-center text-zinc-400 hover:text-white transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        <!-- 状态 1: 微信已在线运行 -->
        <div v-if="botInfo?.online" class="py-6 space-y-5 relative z-10">
          <div class="p-4 rounded-2xl bg-white/[0.03] border border-white/[0.08] flex items-center justify-between">
            <div class="flex items-center space-x-3.5">
              <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-emerald-500/30 flex items-center justify-center text-2xl">
                🤖
              </div>
              <div>
                <div class="text-xs text-zinc-400">已绑定的微信账号</div>
                <div class="text-sm font-bold text-white font-mono mt-0.5">
                  {{ botInfo.accountId || '已授权机器人' }}
                </div>
                <div class="text-[11px] text-zinc-500 mt-0.5">
                  平台账号: <span class="text-zinc-300 font-semibold">{{ botInfo.boundUser?.username || authStore.username || '当前用户' }}</span>
                  <span class="text-emerald-400/80 ml-1.5">● 数据隔离生效中</span>
                </div>
              </div>
            </div>

            <button
              @click="handleLogout"
              :disabled="loggingOut"
              class="px-3 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 border border-red-500/25 text-xs font-medium transition-all cursor-pointer disabled:opacity-50"
            >
              {{ loggingOut ? '断开中...' : '注销 / 换号' }}
            </button>
          </div>

          <!-- 使用提示卡片 -->
          <div class="p-4 rounded-2xl bg-gradient-to-br from-emerald-950/20 to-teal-950/20 border border-emerald-500/20 space-y-2">
            <div class="flex items-center space-x-2 text-xs font-bold text-emerald-400">
              <span>💡</span>
              <span>如何在微信中使用：</span>
            </div>
            <ul class="text-xs text-zinc-300 space-y-1.5 pl-5 list-disc">
              <li>在微信直接发送 <span class="text-white font-mono bg-white/10 px-1 py-0.5 rounded">比亚迪最新估值与均线趋势</span></li>
              <li>在微信直接发送 <span class="text-white font-mono bg-white/10 px-1 py-0.5 rounded">查一下我的自选股今天表现</span>（仅读取您自己的私有数据）</li>
              <li>发送 <span class="text-white font-mono bg-white/10 px-1 py-0.5 rounded">/new</span> 或 <span class="text-white font-mono bg-white/10 px-1 py-0.5 rounded">新会话</span> 清除上一轮记忆</li>
            </ul>
          </div>

          <!-- 快捷操作区 -->
          <div class="flex items-center space-x-3 pt-2">
            <button
              @click="handleResetSession"
              :disabled="resetting"
              class="flex-1 py-2.5 rounded-xl bg-white/[0.08] hover:bg-white/[0.14] border border-white/[0.12] text-xs font-semibold text-white transition-all flex items-center justify-center space-x-2 cursor-pointer disabled:opacity-50"
            >
              <span>🔄</span>
              <span>{{ resetting ? '重置中...' : 'Web 端一键开启新会话' }}</span>
            </button>
          </div>
          <p v-if="resetToast" class="text-xs text-center text-emerald-400 font-medium animate-fade-in">
            {{ resetToast }}
          </p>
        </div>

        <!-- 状态 2: 未在线，展示二维码扫码 -->
        <div v-else class="py-6 flex flex-col items-center justify-center relative z-10 space-y-5">
          <div class="relative group">
            <!-- 二维码外发光框 -->
            <div class="p-3 rounded-2xl bg-white p-3.5 shadow-xl shadow-black/40 border-2 border-white/20 relative">
              <div v-if="loading" class="w-[240px] h-[240px] flex flex-col items-center justify-center bg-zinc-100 rounded-xl">
                <div class="w-8 h-8 border-3 border-emerald-500 border-t-transparent rounded-full animate-spin"></div>
                <span class="text-xs text-zinc-600 font-medium mt-3">生成专属微信授权码...</span>
              </div>

              <div v-else-if="qrData?.qrDataUrl" class="relative">
                <img
                  :src="qrData.qrDataUrl"
                  alt="微信扫码登录"
                  class="w-[240px] h-[240px] object-contain rounded-lg"
                />

                <!-- 扫码成功或过期遮罩 -->
                <div
                  v-if="scanStatus === 'scaned'"
                  class="absolute inset-0 bg-emerald-950/85 backdrop-blur-xs flex flex-col items-center justify-center text-center p-4 rounded-lg"
                >
                  <span class="text-4xl animate-bounce">📱</span>
                  <div class="text-xs font-bold text-white mt-2">已成功扫描</div>
                  <div class="text-[11px] text-emerald-200 mt-1">请在手机微信上点击【确认授权】</div>
                </div>

                <div
                  v-if="scanStatus === 'expired'"
                  class="absolute inset-0 bg-black/85 backdrop-blur-xs flex flex-col items-center justify-center text-center p-4 rounded-lg"
                >
                  <span class="text-3xl text-zinc-400">⏳</span>
                  <div class="text-xs font-bold text-zinc-300 mt-2">二维码已过期</div>
                  <button
                    @click="loadQRCode"
                    class="mt-3 px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-bold hover:bg-emerald-600 transition-colors cursor-pointer"
                  >
                    重新生成
                  </button>
                </div>
              </div>

              <div v-else class="w-[240px] h-[240px] flex flex-col items-center justify-center bg-zinc-900 rounded-xl text-center p-4">
                <span class="text-2xl text-red-400">⚠️</span>
                <span class="text-xs text-zinc-400 mt-2">{{ statusTip }}</span>
                <button
                  @click="loadQRCode"
                  class="mt-3 px-3 py-1 rounded bg-white/10 text-white text-xs hover:bg-white/20 transition-all cursor-pointer"
                >
                  重试加载
                </button>
              </div>
            </div>
          </div>

          <!-- 状态文字与动态指示 -->
          <div class="text-center space-y-1">
            <div class="flex items-center justify-center space-x-1.5 text-xs font-medium text-emerald-400">
              <span v-if="scanStatus === 'wait'" class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              <span>{{ statusTip }}</span>
            </div>
            <p class="text-[11px] text-zinc-500">
              扫码后自动绑定当前账号（{{ authStore.username || '当前用户' }}），无需输入任何繁琐口令
            </p>
          </div>
        </div>

        <!-- 底部说明与支持 -->
        <div class="pt-4 border-t border-white/[0.06] flex items-center justify-between text-[11px] text-zinc-500">
          <span>腾讯 iLink 官方安全协议直连</span>
          <span>独立容器隔离 · 凭据持久化</span>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease;
}
.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}
@keyframes scaleUp {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
.animate-scale-up {
  animation: scaleUp 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
</style>
