import { useEffect, useState, useSyncExternalStore } from 'react'
import { SessionConnection } from './sessionConnection'

/** SceneRoom 按 sessionId 设置 key；StrictMode 的重连忽略旧读取和旧 socket。 */
export function useDialogue(sessionId: string) {
  const [connection] = useState(() => new SessionConnection(sessionId))
  const state = useSyncExternalStore(
    connection.subscribe,
    connection.getSnapshot,
  )
  useEffect(() => {
    connection.connect()
    return () => connection.dispose()
  }, [connection])
  return { state, connection }
}
