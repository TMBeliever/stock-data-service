import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const isOnline = mode === 'online' || env.VITE_TARGET_ENV === 'online'
  const onlineHost = env.VITE_ONLINE_HOST || '43.155.186.45'

  // 线上环境统一经由腾讯云 Nginx 80 网关代理，不可直连未对外开放的内部端口 (8000/8080/8090)
  const stockTarget = isOnline ? `http://${onlineHost}` : 'http://localhost:8000'
  const quantTarget = isOnline && env.VITE_ONLINE_QUANT === 'true' ? `http://${onlineHost}` : 'http://localhost:8080'
  const authTarget = isOnline && env.VITE_ONLINE_AUTH === 'true' ? `http://${onlineHost}` : 'http://localhost:8090'
  const aiTarget = isOnline && env.VITE_ONLINE_AI === 'true' ? `http://${onlineHost}` : (env.VITE_AI_TARGET || 'http://localhost:8070')
  const agentTarget = isOnline && env.VITE_ONLINE_AGENT === 'true' ? `http://${onlineHost}` : (env.VITE_AGENT_TARGET || 'http://localhost:8060')

  console.log(`\n==================================================`)
  console.log(isOnline
    ? `  🌐 Web-Admin 环境模式: 【线上部署环境】 -> 数据中台: http://${onlineHost}/stock | 业务中台: ${quantTarget}`
    : `  💻 Web-Admin 环境模式: 【本地全闭环环境】 -> 基础服务: http://localhost:8000/8080/8090/8070/8060`
  )
  console.log(`==================================================\n`)

  return {
    plugins: [vue(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
      dedupe: [
        'vue',
        '@codemirror/state',
        '@codemirror/view',
        '@codemirror/language',
        '@codemirror/commands',
        '@codemirror/autocomplete',
        'codemirror',
        'vue-codemirror',
      ],
    },
    optimizeDeps: {
      include: [
        '@codemirror/state',
        '@codemirror/view',
        '@codemirror/language',
        '@codemirror/commands',
        '@codemirror/autocomplete',
        '@codemirror/lang-python',
        '@codemirror/theme-one-dark',
        'codemirror',
        'vue-codemirror',
      ],
    },
    server: {
      port: 5174,
      proxy: {
        // 0. AI 大模型协同与流式中枢
        '/api/v1/ai': {
          target: aiTarget,
          changeOrigin: true,
        },
        // 0.1 Quant Agent 智能投研与多端工具中枢 (quant-agent :8060)
        '/api/v1/agent': {
          target: agentTarget,
          changeOrigin: true,
        },
        // 1. 通用业务与用户鉴权服务 (common-server :8090)
        '/api/v1/auth': {
          target: authTarget,
          changeOrigin: true,
        },
        // 2. 用户个人策略库与历史回测归档服务 (common-server :8090)
        '/api/v1/user': {
          target: authTarget,
          changeOrigin: true,
        },
        // 2. 量化业务中枢与回测服务
        '/api/v1': {
          target: quantTarget,
          changeOrigin: true,
        },
        // 3. 行情数据中台 (支持本地 8000 或线上 43.155.186.45/stock)
        '/stock': {
          target: stockTarget,
          changeOrigin: true,
          rewrite: isOnline ? undefined : (p) => p.replace(/^\/stock/, ''),
        },
        // 3.1 WebSocket 实时行情与广播通道
        '/ws': {
          target: isOnline ? `ws://${onlineHost}` : 'ws://localhost:8000',
          ws: true,
          changeOrigin: true,
        },
        // 4. 通用 API 代理兜底
        '/api': {
          target: quantTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
