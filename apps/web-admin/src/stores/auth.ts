import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useStrategyStore } from './strategy'

export interface User {
  id: number
  username: string
  email: string | null
  role: string
  is_active: boolean
  is_vip: boolean
  vip_expire_at: string | null
  created_at: string
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const user = ref<User | null>(null)
  const loading = ref<boolean>(false)
  const authModalVisible = ref<boolean>(false)
  const authModalMode = ref<'login' | 'register'>('login')
  const authError = ref<string | null>(null)

  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const isVip = computed(() => !!user.value?.is_vip)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const username = computed(() => user.value?.username || '未登录用户')

  function openLogin() {
    authModalMode.value = 'login'
    authError.value = null
    authModalVisible.value = true
  }

  function openRegister() {
    authModalMode.value = 'register'
    authError.value = null
    authModalVisible.value = true
  }

  function closeAuthModal() {
    authModalVisible.value = false
    authError.value = null
  }

  async function fetchMe(): Promise<boolean> {
    if (!token.value) {
      user.value = null
      return false
    }
    try {
      const res = await fetch('/api/v1/auth/me', {
        headers: {
          Authorization: `Bearer ${token.value}`,
        },
      })
      if (res.ok) {
        const data = await res.json()
        user.value = data
        return true
      } else {
        // Token 过期或无效，清理登录凭证
        logout()
        return false
      }
    } catch {
      return false
    }
  }

  async function login(usernameInput: string, passwordInput: string): Promise<boolean> {
    loading.value = true
    authError.value = null
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: usernameInput.trim(),
          password: passwordInput,
        }),
      })

      let data: any = null
      try {
        data = await res.json()
      } catch {
        // 非 JSON 响应（例如 500/502 纯文本报错）
      }

      if (!res.ok) {
        authError.value = data?.detail || `登录失败 (${res.status}: ${res.statusText || '服务异常'})`
        return false
      }

      token.value = data.access_token
      user.value = data.user
      localStorage.setItem('access_token', data.access_token)
      closeAuthModal()
      try {
        const strategyStore = useStrategyStore()
        strategyStore.fetchUserWatchlists()
        strategyStore.fetchUserHoldings()
        strategyStore.fetchUserStrategies()
      } catch (e) {
        console.warn('[AuthStore] login sync failed', e)
      }
      return true
    } catch (err: any) {
      authError.value = err.message || '网络连接异常，无法连接鉴权服务'
      return false
    } finally {
      loading.value = false
    }
  }

  async function register(usernameInput: string, passwordInput: string, emailInput?: string): Promise<boolean> {
    loading.value = true
    authError.value = null
    try {
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: usernameInput.trim(),
          password: passwordInput,
          email: emailInput ? emailInput.trim() : undefined,
        }),
      })

      let data: any = null
      try {
        data = await res.json()
      } catch {
        // 非 JSON 响应（例如 500/502 纯文本报错）
      }

      if (!res.ok) {
        authError.value = data?.detail || `注册失败 (${res.status}: ${res.statusText || '服务异常'})`
        return false
      }

      // 注册成功后自动执行登录，提升用户顺畅体验
      return await login(usernameInput, passwordInput)
    } catch (err: any) {
      authError.value = err.message || '网络连接异常，无法连接鉴权服务'
      return false
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('access_token')
    try {
      const strategyStore = useStrategyStore()
      strategyStore.fetchUserWatchlists()
    } catch {}
  }

  async function grantVip(days: number = 30): Promise<boolean> {
    if (!user.value) return false
    loading.value = true
    try {
      const res = await fetch('/api/v1/auth/grant-vip', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: token.value ? `Bearer ${token.value}` : '',
        },
        body: JSON.stringify({
          username: user.value.username,
          days,
        }),
      })
      if (res.ok) {
        await fetchMe()
        return true
      }
      return false
    } catch {
      return false
    } finally {
      loading.value = false
    }
  }

  // 页面挂载初始化：自动复原会话并刷新用户云端数据
  async function initAuth() {
    if (token.value) {
      const ok = await fetchMe()
      if (ok) {
        try {
          const strategyStore = useStrategyStore()
          strategyStore.fetchUserWatchlists()
          strategyStore.fetchUserHoldings()
          strategyStore.fetchUserStrategies()
        } catch (e) {
          console.warn('[AuthStore] initAuth sync failed', e)
        }
      }
    }
  }

  return {
    token,
    user,
    loading,
    authModalVisible,
    authModalMode,
    authError,
    isLoggedIn,
    isVip,
    isAdmin,
    username,
    openLogin,
    openRegister,
    closeAuthModal,
    login,
    register,
    logout,
    grantVip,
    initAuth,
    fetchMe,
  }
})
