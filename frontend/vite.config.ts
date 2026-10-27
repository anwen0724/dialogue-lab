import { existsSync, readFileSync } from 'node:fs'
import { parseEnv } from 'node:util'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 与后端读取同一个根目录 .env，系统环境变量优先；这些配置不注入浏览器。
const envFile = new URL('../.env', import.meta.url)
const fileEnv = existsSync(envFile) ? parseEnv(readFileSync(envFile, 'utf8')) : {}

function readPort(name: string, fallback: number): number {
  const port = Number(process.env[name] ?? fileEnv[name] ?? fallback)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} 必须是 1 到 65535 之间的整数。`)
  }
  return port
}

const backendPort = readPort('DIALOGUE_LAB_BACKEND_PORT', 8000)
const frontendPort = readPort('DIALOGUE_LAB_FRONTEND_PORT', 5173)

// 开发服务器统一转发 API 请求，浏览器只访问前端源。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${backendPort}`, ws: true },
    },
  },
})
