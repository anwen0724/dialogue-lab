import { isRecord, requestJson } from '../../shared/api/request'

export type Scene = {
  id: string
  name: string
  category: string
  characterName: string
  cover: string | null
  background: string | null
  status: 'active' | 'archived'
  ttsVoice: string | null
  voiceAvailable: boolean
}
export type SceneForm = {
  name: string
  category: string
  character_name: string
  system_prompt: string
  tts_voice?: string
}

function parseScene(value: unknown): Scene {
  if (
    !isRecord(value) ||
    typeof value.scene_id !== 'string' ||
    !/^\d+$/.test(value.scene_id) ||
    typeof value.name !== 'string' ||
    typeof value.category !== 'string' ||
    typeof value.character_name !== 'string' ||
    (value.tts_voice !== null && typeof value.tts_voice !== 'string') ||
    typeof value.voice_available !== 'boolean' ||
    (value.status !== 'active' && value.status !== 'archived')
  )
    throw new Error('场景资料无效。')
  const image = (key: string) => {
    const path = value[key]
    if (path === null) return null
    if (
      typeof path !== 'string' ||
      !/^\/api\/(media|scene-assets)\/[a-zA-Z0-9.-]+$/.test(path)
    )
      throw new Error('场景图片地址无效。')
    return path
  }
  return {
    id: value.scene_id,
    name: value.name,
    category: value.category,
    characterName: value.character_name,
    cover: image('cover_image'),
    background: image('background_image'),
    status: value.status,
    ttsVoice: value.tts_voice,
    voiceAvailable: value.voice_available,
  }
}
export async function listScenes(signal?: AbortSignal): Promise<Scene[]> {
  const result = await requestJson('/scenes', { signal })
  if (!Array.isArray(result)) throw new Error('场景列表无效。')
  return result.map(parseScene)
}
export async function getScene(id: string, signal?: AbortSignal) {
  const value = await requestJson(`/scenes/${id}`, { signal })
  const scene = parseScene(value)
  if (!isRecord(value) || typeof value.system_prompt !== 'string')
    throw new Error('身份指令无效。')
  return { ...scene, systemPrompt: value.system_prompt }
}
export async function saveScene(form: SceneForm, id?: string) {
  return parseScene(
    await requestJson(id ? `/scenes/${id}` : '/scenes', {
      method: id ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    }),
  )
}
export async function saveSceneVoice(id: string, voice: string) {
  return parseScene(
    await requestJson(`/scenes/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tts_voice: voice }),
    }),
  )
}
export async function uploadImage(
  id: string,
  kind: 'cover' | 'background',
  file: File,
) {
  if (file.size > 10 * 1024 * 1024) throw new Error('图片不能超过 10 MB。')
  return parseScene(
    await requestJson(`/scenes/${id}/images/${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type },
      body: file,
    }),
  )
}
export async function deleteScene(id: string) {
  await requestJson(`/scenes/${id}`, { method: 'DELETE' })
}
