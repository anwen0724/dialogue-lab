import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发服务器统一转发 API 请求，浏览器只访问前端源。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
})
