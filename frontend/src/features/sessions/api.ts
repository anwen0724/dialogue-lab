import { isRecord, requestJson } from '../../shared/api/request'

export type Session = {
  id: string
  title: string
  status: 'active' | 'archived'
  sceneId: string | null
  latestMessage: string
  messageCount: number
}
export type Message = {
  id: string
  requestId: string
  role: 'user' | 'assistant'
  text: string
  status: 'completed' | 'cancelled' | 'failed'
  source?: string
}

export function parseMessage(value: unknown): Message {
  if (
    !isRecord(value) ||
    typeof value.message_id !== 'string' ||
    typeof value.request_id !== 'string' ||
    !isRecord(value.message_json)
  ) {
    throw new Error('消息格式无效。')
  }
  const payload = value.message_json
  const role =
    value.message_kind === 'user_message'
      ? 'user'
      : value.message_kind === 'assistant_message'
        ? 'assistant'
        : undefined
  const content = role === 'user' ? payload.display_content : payload.content
  if (!role || !Array.isArray(content) || !content.every(isRecord))
    throw new Error('消息内容无效。')
  const text = content
    .filter((block) => block.type === 'text')
    .map((block) => {
      if (typeof block.text !== 'string') throw new Error('消息正文无效。')
      return block.text
    })
    .join('')
  const status = role === 'user' ? 'completed' : payload.status
  if (status !== 'completed' && status !== 'cancelled' && status !== 'failed') {
    throw new Error('消息状态无效。')
  }
  return {
    id: value.message_id,
    requestId: value.request_id,
    role,
    text,
    status,
    source: typeof payload.source === 'string' ? payload.source : undefined,
  }
}

function parseSession(value: unknown): Session {
  if (
    !isRecord(value) ||
    typeof value.session_id !== 'string' ||
    !/^\d+$/.test(value.session_id) ||
    typeof value.title !== 'string' ||
    (value.status !== 'active' && value.status !== 'archived')
  )
    throw new Error('会话格式无效。')
  if (
    value.scene_id != null &&
    (typeof value.scene_id !== 'string' || !/^\d+$/.test(value.scene_id))
  )
    throw new Error('会话场景无效。')
  return {
    id: value.session_id,
    title: value.title,
    status: value.status,
    sceneId: typeof value.scene_id === 'string' ? value.scene_id : null,
    latestMessage:
      typeof value.latest_message === 'string' ? value.latest_message : '',
    messageCount:
      typeof value.message_count === 'number' ? value.message_count : 0,
  }
}

export async function getSession(id: string, signal: AbortSignal) {
  const value = await requestJson(`/sessions/${encodeURIComponent(id)}`, {
    signal,
  })
  const session = parseSession(value)
  if (!isRecord(value) || !Array.isArray(value.messages))
    throw new Error('会话消息无效。')
  return { ...session, messages: value.messages.map(parseMessage) }
}

export async function listSessions(signal?: AbortSignal, sceneId?: string) {
  const value = await requestJson(
    sceneId ? `/sessions?scene_id=${sceneId}` : '/sessions',
    { signal },
  )
  if (!Array.isArray(value)) throw new Error('会话列表无效。')
  return value.map(parseSession)
}

export async function createSession(title: string, sceneId?: string) {
  return parseSession(
    await requestJson('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, scene_id: sceneId }),
    }),
  )
}

export async function getPresets(signal: AbortSignal): Promise<string[]> {
  const value = await requestJson('/presets', { signal })
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === 'string')
  ) {
    throw new Error('系统指令列表无效。')
  }
  return value
}
