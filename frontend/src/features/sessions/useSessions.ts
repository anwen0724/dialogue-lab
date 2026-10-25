import { useEffect, useState } from 'react'
import { createSession, listSessions } from './api'
import type { Session } from './api'

function selectedFromUrl() {
  const id = new URLSearchParams(window.location.search).get('session')
  return id && /^\d+$/.test(id) ? id : undefined
}

/** 会话列表与 URL 选择在此协调，创建只由用户操作触发。 */
export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selected, setSelected] = useState(selectedFromUrl)
  const [error, setError] = useState<string>()
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    void listSessions(controller.signal)
      .then((items) => {
        if (!controller.signal.aborted)
          setSessions((previous) => {
            const created = previous.filter(
              (item) => !items.some((saved) => saved.id === item.id),
            )
            return [...created, ...items]
          })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : '无法读取会话。')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    const onPopState = () => setSelected(selectedFromUrl())
    window.addEventListener('popstate', onPopState)
    return () => {
      controller.abort()
      window.removeEventListener('popstate', onPopState)
    }
  }, [])

  function select(id: string) {
    const url = new URL(window.location.href)
    url.searchParams.set('session', id)
    window.history.pushState(null, '', url)
    setSelected(id)
  }
  async function create(title: string) {
    const session = await createSession(title)
    setSessions((previous) => [session, ...previous])
    select(session.id)
  }
  return { sessions, selected, loading, error, select, create }
}
