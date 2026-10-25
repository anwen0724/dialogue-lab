import { useEffect, useState, useSyncExternalStore } from 'react'
import { VoiceConnection } from './voiceConnection'

/** 订阅语音状态；卸载时释放连接，兼容 StrictMode 的重复清理。 */
export function useVoiceInput() {
  const [connection] = useState(() => new VoiceConnection())
  const snapshot = useSyncExternalStore(
    connection.subscribe,
    connection.getSnapshot,
  )
  useEffect(() => () => connection.dispose(), [connection])
  return {
    ...snapshot,
    start: () => connection.start(),
    stop: () => connection.stop(),
  }
}
