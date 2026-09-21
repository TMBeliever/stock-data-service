import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '首页' },
  },
  {
    path: '/strategy',
    name: 'StrategyStudio',
    component: () => import('@/views/StrategyStudioView.vue'),
    meta: { title: '策略投研工作台' },
  },
  {
    path: '/agent-settings',
    name: 'AgentSettings',
    component: () => import('@/views/AgentSettingsView.vue'),
    meta: { title: 'Agent 管理与配置中心' },
  },
  {
    path: '/symbol/:symbol',
    name: 'SymbolDetail',
    component: () => import('@/views/SymbolDetailView.vue'),
    meta: { title: '标的行情与K线' },
  },
  {
    path: '/assets',
    name: 'Assets',
    component: () => import('@/views/AssetsView.vue'),
    meta: { title: '全景资产看板' },
  },
  {
    path: '/portfolio',
    redirect: '/assets',
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },


]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局路由守卫：除市场看板 ('/') 外，其余所有路由均需登录，未登录则拦截并弹窗引导登录
router.beforeEach(async (to, from, next) => {
  // 1. 公开路由白名单：仅「市场看板」('/') 允许免登录进入
  if (to.path === '/') {
    return next()
  }

  // 2. 检查用户鉴权状态
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()

  // 若本地已存有 Token 凭证但用户实体尚未在内存就绪，先拉取校验当前用户信息
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }

  // 3. 已登录：正常放行进入目标页面
  if (authStore.isLoggedIn) {
    return next()
  }

  // 4. 未登录：阻断进入，唤起登录弹窗，并定位或重定向至市场看板 ('/')
  authStore.openLogin(to.fullPath)

  if (from.matched.length === 0 || from.path === '/') {
    // 首屏外部直接访问受保护 URL，强制重定向至市场看板 ('/') 并弹出登录框
    return next({ path: '/', replace: true })
  } else {
    // 站内点击跳转受保护路由，中止当前跳转保持原位
    return next(false)
  }
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'QuantScope'
  document.title = `${title} | QuantScope`
})
