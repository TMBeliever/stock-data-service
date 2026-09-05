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
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },


]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'QuantScope'
  document.title = `${title} | QuantScope`
})
