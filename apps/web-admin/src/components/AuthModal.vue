<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const usernameInput = ref('')
const passwordInput = ref('')
const emailInput = ref('')

// 每次打开弹窗重置表单
watch(
  () => authStore.authModalVisible,
  (visible) => {
    if (visible) {
      usernameInput.value = ''
      passwordInput.value = ''
      emailInput.value = ''
    }
  }
)

async function handleSubmit() {
  if (!usernameInput.value || !passwordInput.value) {
    authStore.authError = '请完整填写用户名与密码'
    return
  }

  if (authStore.authModalMode === 'login') {
    await authStore.login(usernameInput.value, passwordInput.value)
  } else {
    await authStore.register(usernameInput.value, passwordInput.value, emailInput.value)
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && authStore.authModalVisible) {
    authStore.closeAuthModal()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <teleport to="body">
    <transition name="modal-fade">
      <div
        v-if="authStore.authModalVisible"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md"
        @click.self="authStore.closeAuthModal"
      >
        <div
          class="relative w-full max-w-sm rounded-2xl bg-[#121216] border border-white/10 shadow-2xl p-6 overflow-hidden transform transition-all"
        >
          <!-- 顶部装饰光晕 -->
          <div class="absolute -top-20 -left-20 w-40 h-40 bg-red-500/15 rounded-full blur-3xl pointer-events-none"></div>
          <div class="absolute -bottom-20 -right-20 w-40 h-40 bg-orange-500/15 rounded-full blur-3xl pointer-events-none"></div>

          <!-- 关闭按钮 -->
          <button
            @click="authStore.closeAuthModal"
            class="absolute top-4 right-4 p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>

          <!-- 标题与 Logo -->
          <div class="flex items-center space-x-3 mb-5">
            <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-[#ff5f3d] to-[#ff2d55] flex items-center justify-center shadow-lg shadow-red-500/20">
              <span class="text-white text-base font-bold">📈</span>
            </div>
            <div>
              <h3 class="text-base font-bold text-white tracking-tight">QuantScope 投研账户</h3>
              <p class="text-xs text-zinc-400">一键接入专属量化策略与 VIP 权益</p>
            </div>
          </div>

          <!-- 登录/注册 分段标签切换器 -->
          <div class="flex p-1 bg-white/[0.04] rounded-xl border border-white/[0.06] mb-5">
            <button
              type="button"
              @click="authStore.authModalMode = 'login'; authStore.authError = null"
              :class="[
                'flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all',
                authStore.authModalMode === 'login'
                  ? 'bg-white/10 text-white shadow-sm border border-white/10'
                  : 'text-zinc-400 hover:text-zinc-200'
              ]"
            >
              密码登录
            </button>
            <button
              type="button"
              @click="authStore.authModalMode = 'register'; authStore.authError = null"
              :class="[
                'flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all',
                authStore.authModalMode === 'register'
                  ? 'bg-white/10 text-white shadow-sm border border-white/10'
                  : 'text-zinc-400 hover:text-zinc-200'
              ]"
            >
              创建新账号
            </button>
          </div>

          <!-- 错误提示 Banner -->
          <div
            v-if="authStore.authError"
            class="mb-4 p-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-center space-x-2"
          >
            <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{{ authStore.authError }}</span>
          </div>

          <!-- 表单区 -->
          <form @submit.prevent="handleSubmit" class="space-y-3.5">
            <!-- 用户名输入 -->
            <div>
              <label class="block text-[11px] font-medium text-zinc-400 mb-1">用户名</label>
              <div class="relative">
                <input
                  v-model="usernameInput"
                  type="text"
                  required
                  placeholder="请输入用户名 (3~32位)"
                  class="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] focus:border-red-500/50 focus:bg-white/[0.06] text-xs text-white placeholder-zinc-500 outline-none transition-all"
                />
              </div>
            </div>

            <!-- 邮箱输入 (仅注册模式展示) -->
            <div v-if="authStore.authModalMode === 'register'">
              <label class="block text-[11px] font-medium text-zinc-400 mb-1">邮箱 (选填)</label>
              <input
                v-model="emailInput"
                type="email"
                placeholder="your@email.com"
                class="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] focus:border-red-500/50 focus:bg-white/[0.06] text-xs text-white placeholder-zinc-500 outline-none transition-all"
              />
            </div>

            <!-- 密码输入 -->
            <div>
              <label class="block text-[11px] font-medium text-zinc-400 mb-1">密码</label>
              <input
                v-model="passwordInput"
                type="password"
                required
                placeholder="请输入密码 (至少6位)"
                class="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] focus:border-red-500/50 focus:bg-white/[0.06] text-xs text-white placeholder-zinc-500 outline-none transition-all"
              />
            </div>

            <!-- 提交按钮 -->
            <button
              type="submit"
              :disabled="authStore.loading"
              class="w-full mt-2 py-2.5 rounded-xl bg-gradient-to-r from-[#ff5f3d] to-[#ff2d55] text-white text-xs font-semibold shadow-lg shadow-red-500/25 hover:shadow-red-500/40 hover:opacity-95 active:scale-[0.99] transition-all disabled:opacity-50 cursor-pointer flex items-center justify-center space-x-2"
            >
              <svg
                v-if="authStore.loading"
                class="animate-spin w-3.5 h-3.5 text-white"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
              </svg>
              <span>{{ authStore.loading ? '正在处理...' : (authStore.authModalMode === 'login' ? '立即登录' : '立即注册') }}</span>
            </button>
          </form>

          <!-- 底部版权/提示说明 -->
          <div class="mt-4 pt-3 border-t border-white/[0.06] text-center">
            <span class="text-[10px] text-zinc-500">首位注册用户将自动激活系统 Admin 超管权限</span>
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
  transform: scale(0.96);
}
</style>
