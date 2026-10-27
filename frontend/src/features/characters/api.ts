import { isRecord, requestJson } from '../../shared/api/request'

export type Character = {
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
export type CharacterForm = {
  name: string
  category: string
  character_name: string
  system_prompt: string
  tts_voice?: string
}

function parseCharacter(value: unknown): Character {
  if (
    !isRecord(value) ||
    typeof value.character_id !== 'string' ||
    !/^\d+$/.test(value.character_id) ||
    typeof value.name !== 'string' ||
    typeof value.category !== 'string' ||
    typeof value.character_name !== 'string' ||
    (value.tts_voice !== null && typeof value.tts_voice !== 'string') ||
    typeof value.voice_available !== 'boolean' ||
    (value.status !== 'active' && value.status !== 'archived')
  )
    throw new Error('角色资料无效。')
  const image = (key: string) => {
    const path = value[key]
    if (path === null) return null
    if (
      typeof path !== 'string' ||
      !/^\/api\/(media|scene-assets)\/[a-zA-Z0-9.-]+$/.test(path)
    )
      throw new Error('角色图片地址无效。')
    return path
  }
  return {
    id: value.character_id,
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
export async function listCharacters(
  signal?: AbortSignal,
): Promise<Character[]> {
  const result = await requestJson('/characters', { signal })
  if (!Array.isArray(result)) throw new Error('角色列表无效。')
  return result.map(parseCharacter)
}
export async function getCharacter(id: string, signal?: AbortSignal) {
  const value = await requestJson(`/characters/${id}`, { signal })
  const character = parseCharacter(value)
  if (!isRecord(value) || typeof value.system_prompt !== 'string')
    throw new Error('身份指令无效。')
  return { ...character, systemPrompt: value.system_prompt }
}
export async function saveCharacter(form: CharacterForm, id?: string) {
  return parseCharacter(
    await requestJson(id ? `/characters/${id}` : '/characters', {
      method: id ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    }),
  )
}
export async function saveCharacterVoice(id: string, voice: string) {
  return parseCharacter(
    await requestJson(`/characters/${id}`, {
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
  return parseCharacter(
    await requestJson(`/characters/${id}/images/${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type },
      body: file,
    }),
  )
}
export async function deleteCharacter(id: string) {
  await requestJson(`/characters/${id}`, { method: 'DELETE' })
}

/** 服务端复制资料和文件；复制本身不新建会话。 */
export async function copyCharacter(id: string): Promise<Character> {
  return parseCharacter(
    await requestJson(`/characters/${id}/copy`, { method: 'POST' }),
  )
}
