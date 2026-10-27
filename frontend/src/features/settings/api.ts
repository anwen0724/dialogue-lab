/** 应用设置的网络边界，校验公开数据，不接收供应商凭据。 */
import { isRecord, requestJson } from '../../shared/api/request'

export type ModelSelection = { provider_id: string; model_id: string }
export type ApplicationSettings = {
  dialogue: ModelSelection & { reasoning: string | null }
  stt: ModelSelection
  tts: ModelSelection
}
export type ModelOption = ModelSelection & {
  name: string
  available: boolean
  reasoning_levels: string[]
  kind?: 'stt' | 'tts'
}
export type VoiceOption = { id: string; name: string }
export type AffectedScene = { id: string; name: string }

export async function previewSettings(
  settings: ApplicationSettings,
  signal: AbortSignal,
): Promise<AffectedScene[]> {
  const result = await requestJson('/settings/preview', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!Array.isArray(result)) throw new Error('无法检查场景音色。')
  return result.map((value: unknown) => {
    if (
      !isRecord(value) ||
      typeof value.scene_id !== 'string' ||
      typeof value.name !== 'string'
    )
      throw new Error('场景音色检查结果无效。')
    return { id: value.scene_id, name: value.name }
  })
}

function parseSelection(value: unknown): ModelSelection {
  if (
    !isRecord(value) ||
    typeof value.provider_id !== 'string' ||
    typeof value.model_id !== 'string'
  )
    throw new Error('模型选择无效。')
  return { provider_id: value.provider_id, model_id: value.model_id }
}
function parseSettings(value: unknown): ApplicationSettings {
  if (
    !isRecord(value) ||
    !isRecord(value.dialogue) ||
    (value.dialogue.reasoning !== null &&
      typeof value.dialogue.reasoning !== 'string')
  )
    throw new Error('应用设置无效。')
  return {
    dialogue: {
      ...parseSelection(value.dialogue),
      reasoning: value.dialogue.reasoning,
    },
    stt: parseSelection(value.stt),
    tts: parseSelection(value.tts),
  }
}
export async function getSettings(signal?: AbortSignal) {
  return parseSettings(await requestJson('/settings', { signal }))
}
export async function saveSettings(settings: ApplicationSettings) {
  return parseSettings(
    await requestJson('/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }),
  )
}
export async function getModels(
  speech = false,
  signal?: AbortSignal,
): Promise<ModelOption[]> {
  const result = await requestJson(speech ? '/speech-models' : '/models', {
    signal,
  })
  if (!Array.isArray(result)) throw new Error('模型目录无效。')
  return result.map((value: unknown) => {
    if (
      !isRecord(value) ||
      typeof value.name !== 'string' ||
      typeof value.available !== 'boolean'
    )
      throw new Error('模型信息无效。')
    const levels: unknown = speech ? [] : value.reasoning_levels
    if (
      !Array.isArray(levels) ||
      !levels.every((item): item is string => typeof item === 'string')
    )
      throw new Error('推理档位无效。')
    if (speech && value.kind !== 'stt' && value.kind !== 'tts')
      throw new Error('语音模型类型无效。')
    return {
      ...parseSelection(value),
      name: value.name,
      available: value.available,
      reasoning_levels: levels,
      kind:
        value.kind === 'stt' || value.kind === 'tts' ? value.kind : undefined,
    }
  })
}
export async function getVoices(
  model: ModelSelection,
  signal?: AbortSignal,
): Promise<VoiceOption[]> {
  const result = await requestJson(`/voices?${new URLSearchParams(model)}`, {
    signal,
  })
  if (!Array.isArray(result)) throw new Error('音色列表无效。')
  return result.map((value: unknown) => {
    if (
      !isRecord(value) ||
      typeof value.id !== 'string' ||
      typeof value.name !== 'string'
    )
      throw new Error('音色信息无效。')
    return { id: value.id, name: value.name }
  })
}
