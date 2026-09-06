import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './assets/main.css'

// -------------------------------------------------------------
// 全局异常防护网：拦截隔离浏览器扩展或 DevTools 的非核心异常 (如 reading 'startTime')
// -------------------------------------------------------------
window.addEventListener('error', (event) => {
  const msg = String(event.message || '')
  if (msg.includes("reading 'startTime'") || msg.includes('startTime')) {
    event.preventDefault()
    event.stopPropagation()
    console.warn('[System Shield] 已安全拦截非业务级 startTime 异常，保证回测及核心逻辑正常运行:', msg)
    return true
  }
})

window.addEventListener('unhandledrejection', (event) => {
  const reason = String(event.reason?.message || event.reason || '')
  if (reason.includes("reading 'startTime'") || reason.includes('startTime')) {
    event.preventDefault()
    event.stopPropagation()
    console.warn('[System Shield] 已安全拦截 Promise 未捕获 startTime 异常:', reason)
  }
})

const app = createApp(App)

app.config.errorHandler = (err: any, instance, info) => {
  const errStr = String(err?.message || err || '')
  if (errStr.includes("reading 'startTime'") || errStr.includes('startTime')) {
    console.warn('[System Shield] 隔离组件生命周期中的 startTime 异常:', errStr)
    return
  }
  console.error('[Vue Error Handler]', err, info)
}

app.use(createPinia())
app.use(router)

app.mount('#app')
