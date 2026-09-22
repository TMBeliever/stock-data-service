import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const isOnline = mode === 'online' || env.VITE_TARGET_ENV === 'online'
  const onlineHost = env.VITE_ONLINE_HOST || '43.155.186.45'

  // 统一业务网关入口 (本地开发默认端口 8001，线上环境走统一 Nginx 80 网关)
  const gatewayTarget = isOnline ? `http://${onlineHost}` : (env.VITE_GATEWAY_TARGET || 'http://localhost:8001')
  const gatewayWsTarget = isOnline ? `ws://${onlineHost}` : (env.VITE_GATEWAY_WS_TARGET || 'ws://localhost:8001')

  console.log(`\n==================================================`)
  console.log(isOnline
    ? `  🌐 Web-Admin 环境模式: 【线上部署环境】 -> 全量 API 网关直连: ${gatewayTarget}`
    : `  💻 Web-Admin 环境模式: 【统一网关接入】 -> API 统一网关中枢: ${gatewayTarget} (Port 8001)`
  )
  console.log(`==================================================\n`)

  return {
    plugins: [vue(), tailwindcss()],
    build: {
      assetsDir: 'static',
    },
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
        // 1. 全量 API 统一由 API 业务网关转发 (统一鉴权、安全清洗、动态路由)
        '/api': {
          target: gatewayTarget,
          changeOrigin: true,
        },
        // 2. 行情数据底座
        '/stock': {
          target: gatewayTarget,
          changeOrigin: true,
        },
        // 3. WebSocket 实时盘口行情通道
        '/ws': {
          target: gatewayWsTarget,
          ws: true,
          changeOrigin: true,
        },
        // 4. OpenAI / Anthropic 兼容端点直连网关
        '/v1': {
          target: gatewayTarget,
          changeOrigin: true,
        },
        '/messages': {
          target: gatewayTarget,
          changeOrigin: true,
        },
        // 5. MCP 协议端点
        '/mcp': {
          target: gatewayTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
