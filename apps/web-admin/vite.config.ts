import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      // 1. 通用业务与用户鉴权服务 (common-server: 8090)
      '/api/v1/auth': {
        target: 'http://localhost:8090',
        changeOrigin: true,
      },
      // 2. 量化业务中枢与回测服务 (quant-server: 8080)
      '/api/v1': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      // 3. 底层行情与财务服务 (stock-data-service: 8000)
      '/stock': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // 3. 通用 API 代理兜底
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
})
