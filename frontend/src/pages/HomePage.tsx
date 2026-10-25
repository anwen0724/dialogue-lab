import { useEffect, useState } from 'react'

import { getHealth } from '../shared/api/health'

type ConnectionState =
  | { status: 'connecting' }
  | { status: 'connected' }
  | { status: 'failed'; message: string }

/** 初始化页面通过健康接口展示真实的后端连接结果。 */
export function HomePage() {
  const [connection, setConnection] = useState<ConnectionState>({ status: 'connecting' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    // 连接检查到期即结束；卸载或重新检查时取消旧请求。
    const timeout = window.setTimeout(() => controller.abort(), 5_000)
    let disposed = false

    async function checkConnection() {
      try {
        await getHealth(controller.signal)
        if (!disposed) {
          setConnection({ status: 'connected' })
        }
      } catch (error: unknown) {
        if (!disposed) {
          setConnection({
            status: 'failed',
            message: controller.signal.aborted
              ? '连接超时，请检查后端服务是否已启动。'
              : error instanceof Error
                ? error.message
                : '无法连接后端服务。',
          })
        }
      } finally {
        window.clearTimeout(timeout)
      }
    }

    void checkConnection()

    return () => {
      disposed = true
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [attempt])

  function retryConnection() {
    setConnection({ status: 'connecting' })
    setAttempt((previous) => previous + 1)
  }

  const statusLabel = {
    connecting: '正在连接后端',
    connected: '前后端已连接',
    failed: '连接失败',
  }[connection.status]

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="/">
          Dialogue Lab
        </a>
        <span className="stage-label">开发环境</span>
      </header>

      <main className="home-page">
        <p className="eyebrow">DIALOGUE LAB</p>
        <h1>对话，从这里开始。</h1>
        <p className="intro">模拟对话应用的开发起点。</p>

        <section className="connection-card" aria-labelledby="connection-heading">
          <h2 id="connection-heading">服务连接</h2>
          <div className="connection-status" role="status" aria-live="polite">
            <span className={`status-dot status-dot--${connection.status}`} aria-hidden="true" />
            <strong>{statusLabel}</strong>
            <p>
              {connection.status === 'failed'
                ? connection.message
                : connection.status === 'connected'
                  ? '后端服务已响应，开发环境可以继续使用。'
                  : '正在检查后端服务，请稍候。'}
            </p>
          </div>
          <button
            type="button"
            disabled={connection.status === 'connecting'}
            onClick={retryConnection}
          >
            {connection.status === 'connecting' ? '检查中…' : '重新检查'}
          </button>
        </section>
      </main>

      <footer className="app-footer">Dialogue Lab · 开发起点</footer>
    </div>
  )
}
