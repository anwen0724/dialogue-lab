import { isRecord } from '../../shared/api/request'
import { parseMessage } from '../sessions/api'
import type { TextTiming, WordTiming } from './subtitles'

function seconds(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0)
    throw new Error('字幕时间无效。')
  return value
}

function parseTiming(value: Record<string, unknown>): TextTiming {
  if (
    !Number.isInteger(value.segment_index) ||
    Number(value.segment_index) < 0 ||
    typeof value.text !== 'string'
  )
    throw new Error('字幕段落无效。')
  let words: WordTiming[] | null = null
  if (value.words !== null) {
    if (!Array.isArray(value.words)) throw new Error('字幕字词时间无效。')
    words = value.words.map((word) => {
      if (!isRecord(word) || typeof word.text !== 'string')
        throw new Error('字幕字词无效。')
      const start = seconds(word.start_seconds)
      const end = seconds(word.end_seconds)
      if (end < start) throw new Error('字幕时间范围无效。')
      return { text: word.text, start, end }
    })
  }
  const start = seconds(value.start_seconds)
  const end = value.end_seconds === null ? null : seconds(value.end_seconds)
  if (end !== null && end < start) throw new Error('字幕时间范围无效。')
  return {
    index: Number(value.segment_index),
    text: value.text,
    start,
    end,
    words,
  }
}

/** 只在网络边界解析一次，内部使用可辨识事件类型。 */
export function parseEvent(value: unknown) {
  if (!isRecord(value)) throw new Error('会话事件无效。')
  const requestId = () => {
    if (typeof value.request_id !== 'string') throw new Error('回复标识无效。')
    return value.request_id
  }
  const text = () => {
    if (typeof value.text !== 'string') throw new Error('事件正文无效。')
    return value.text
  }
  switch (value.type) {
    case 'text_timing':
      return {
        type: 'text_timing',
        requestId: requestId(),
        timing: parseTiming(value),
      } as const
    case 'connected':
      if (typeof value.can_control !== 'boolean')
        throw new Error('控制状态无效。')
      if (!Array.isArray(value.messages)) throw new Error('会话消息无效。')
      return {
        type: 'connected',
        canControl: value.can_control,
        messages: value.messages.map(parseMessage),
      } as const
    case 'message_saved':
      return {
        type: 'message_saved',
        message: parseMessage(value.message),
      } as const
    case 'text_delta':
      return {
        type: 'text_delta',
        requestId: requestId(),
        text: text(),
      } as const
    case 'partial':
    case 'final':
      return { type: value.type, text: text() } as const
    case 'reply_started':
    case 'generation_finished':
    case 'audio_finished':
    case 'input_queued':
      return { type: value.type, requestId: requestId() } as const
    case 'reply_stopped':
      return {
        type: 'reply_stopped',
        requestId: value.request_id === null ? null : requestId(),
      } as const
    case 'audio_format':
      if (
        typeof value.sample_rate !== 'number' ||
        value.sample_rate <= 0 ||
        value.channels !== 1 ||
        value.encoding !== 'pcm_s16le'
      )
        throw new Error('音频格式不受支持。')
      return {
        type: 'audio_format',
        requestId: requestId(),
        sampleRate: value.sample_rate,
      } as const
    case 'runtime_state':
      if (
        typeof value.busy !== 'boolean' ||
        typeof value.allow_interrupt !== 'boolean'
      )
        throw new Error('运行状态无效。')
      return {
        type: 'runtime_state',
        busy: value.busy,
        allowInterrupt: value.allow_interrupt,
      } as const
    case 'recording_stopped':
      return {
        type: 'recording_stopped',
        paused: value.paused === true,
      } as const
    case 'recording_ready':
    case 'compaction_started':
    case 'compaction_finished':
      return { type: value.type } as const
    case 'error':
      if (typeof value.message !== 'string' || typeof value.code !== 'string')
        throw new Error('错误事件无效。')
      return {
        type: 'error',
        code: value.code,
        message: value.message,
        requestId:
          typeof value.request_id === 'string' ? value.request_id : undefined,
      } as const
    default:
      throw new Error('未知会话事件。')
  }
}
