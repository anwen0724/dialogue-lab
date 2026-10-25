import { getPresets, getSession } from '../sessions/api'
import type { Message } from '../sessions/api'
import { AudioPlayer } from '../voice-output/audioPlayer'
import { Microphone } from '../voice-input/microphone'
import { parseEvent } from './events'

type Snapshot = {
  status: 'loading' | 'connecting' | 'connected' | 'disconnected'
  canControl: boolean
  messages: Message[]
  presets: string[]
  error?: string
  draft?: { requestId: string; text: string }
  generating: boolean
  playing: boolean
  compacting: boolean
  partial: string
  recording: 'idle' | 'preparing' | 'recording' | 'finishing'
}

/** 一个会话一个连接；HTTP 恢复完成后才开放提交，不自动重发历史消息。 */
export class SessionConnection {
  private snapshot: Snapshot = {
    status: 'loading',
    canControl: false,
    messages: [],
    presets: [],
    generating: false,
    playing: false,
    compacting: false,
    partial: '',
    recording: 'idle',
  }
  private listeners = new Set<() => void>()
  private socket?: WebSocket
  private loading?: AbortController
  private generation = 0
  private activeRequest?: string
  private sampleRate?: number
  private suppressOutput = false
  private pending = new Map<
    string,
    { resolve: () => void; reject: (error: Error) => void }
  >()
  private player = this.makePlayer()
  private microphone?: Microphone
  private recordingAbort?: AbortController
  private recordingRequested = false
  constructor(private sessionId: string) {}
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  connect(): void {
    const generation = ++this.generation
    const loading = new AbortController()
    this.loading = loading
    this.player = this.makePlayer()
    void Promise.all([
      getSession(this.sessionId, loading.signal),
      getPresets(loading.signal),
    ])
      .then(([session, presets]) => {
        if (generation !== this.generation) return
        this.update({
          status: 'connecting',
          messages: session.messages,
          presets,
        })
        const url = new URL(
          `/api/sessions/${this.sessionId}/realtime`,
          window.location.href,
        )
        url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
        const socket = new WebSocket(url)
        this.socket = socket
        socket.binaryType = 'arraybuffer'
        socket.onmessage = (event) => {
          if (generation !== this.generation) return
          try {
            if (event.data instanceof ArrayBuffer) this.receiveAudio(event.data)
            else this.receive(parseEvent(JSON.parse(event.data)))
          } catch (error: unknown) {
            this.update({
              error:
                error instanceof Error ? error.message : '无法读取服务端消息。',
            })
          }
        }
        socket.onclose = () => {
          if (generation === this.generation) {
            this.generation++
            this.releaseDevices()
            this.rejectPending(new Error('连接已断开，输入尚未确认保存。'))
            this.update({
              status: 'disconnected',
              canControl: false,
              generating: false,
              playing: false,
              draft: undefined,
              partial: '',
              error: '连接已断开，请重新打开会话。',
            })
          }
        }
        socket.onerror = () => {
          if (generation === this.generation)
            this.update({ error: '无法连接会话服务。' })
        }
      })
      .catch((error: unknown) => {
        if (generation === this.generation)
          this.update({
            status: 'disconnected',
            error: error instanceof Error ? error.message : '无法读取会话。',
          })
      })
  }

  dispose(): void {
    this.generation++
    this.loading?.abort()
    this.socket?.close()
    this.releaseDevices()
    this.rejectPending(new Error('会话已关闭。'))
  }

  async submit(text: string, preset: string): Promise<void> {
    this.update({ error: undefined })
    await this.unlockPlayback()
    const requestId = crypto.randomUUID()
    return new Promise((resolve, reject) => {
      this.pending.set(requestId, { resolve, reject })
      try {
        this.send({ type: 'submit', request_id: requestId, text, preset })
      } catch (error: unknown) {
        this.pending.delete(requestId)
        reject(error instanceof Error ? error : new Error('发送失败。'))
      }
    })
  }

  stopReply(): void {
    this.suppressOutput = true
    this.player.stop()
    this.update({ playing: false, generating: false })
    try {
      this.send({ type: 'stop_reply' })
    } catch (error: unknown) {
      this.report(error)
    }
  }

  async startRecording(preset: string): Promise<void> {
    if (this.snapshot.recording !== 'idle') return
    const controller = new AbortController()
    this.recordingAbort = controller
    this.update({ recording: 'preparing', error: undefined })
    try {
      const [microphone] = await Promise.all([
        Microphone.open(
          (audio) => {
            if (
              this.socket?.readyState !== WebSocket.OPEN ||
              this.socket.bufferedAmount > 1_000_000
            ) {
              this.recordingFailure(
                new Error('音频发送不畅，录音已停止，请检查连接。'),
              )
              return
            }
            this.socket.send(audio)
          },
          (error) => this.recordingFailure(error),
          controller.signal,
        ),
        this.unlockPlayback(),
      ])
      if (controller.signal.aborted) {
        microphone.dispose()
        return
      }
      this.microphone = microphone
      this.send({ type: 'start_recording', preset })
      this.recordingRequested = true
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        this.recordingFailure(
          error instanceof DOMException && error.name === 'NotAllowedError'
            ? new Error('麦克风权限被拒绝，请在浏览器中允许访问后重试。')
            : error,
        )
      }
    }
  }

  async stopRecording(): Promise<void> {
    if (this.snapshot.recording === 'preparing') {
      this.recordingAbort?.abort()
      this.microphone?.dispose()
      if (this.recordingRequested) {
        this.update({ recording: 'finishing' })
        try {
          this.send({ type: 'stop_recording' })
        } catch (error: unknown) {
          this.report(error)
        }
      } else this.update({ recording: 'idle' })
      return
    }
    if (this.snapshot.recording !== 'recording') return
    this.update({ recording: 'finishing' })
    try {
      await this.microphone?.stop()
      this.send({ type: 'stop_recording' })
    } catch (error: unknown) {
      this.recordingFailure(error)
    }
  }

  private recordingFailure(error: unknown): void {
    this.recordingAbort?.abort()
    this.microphone?.dispose()
    if (this.recordingRequested && this.socket?.readyState === WebSocket.OPEN) {
      try {
        this.send({ type: 'stop_recording' })
      } catch {
        /* 断线状态由 socket 事件报告。 */
      }
    }
    this.recordingRequested = false
    this.update({ recording: 'idle' })
    this.report(error)
  }

  private makePlayer(): AudioPlayer {
    return new AudioPlayer((requestId) => {
      this.update({ playing: false })
      try {
        this.send({ type: 'playback_finished', request_id: requestId })
      } catch (error: unknown) {
        this.report(error)
      }
    })
  }

  private async unlockPlayback(): Promise<void> {
    // 播放失败只报告语音错误，不阻止文字或录音提交。
    try {
      await this.player.unlock()
    } catch (error: unknown) {
      this.report(error)
    }
  }

  private send(command: object): void {
    if (
      !this.snapshot.canControl ||
      this.socket?.readyState !== WebSocket.OPEN
    ) {
      throw new Error('当前连接不能提交，请重新打开会话。')
    }
    this.socket.send(JSON.stringify(command))
  }

  private receive(event: ReturnType<typeof parseEvent>): void {
    switch (event.type) {
      case 'connected':
        this.update({
          status: 'connected',
          canControl: event.canControl,
          messages: event.messages,
        })
        break
      case 'message_saved': {
        const message = event.message
        const messages = this.snapshot.messages.filter(
          (item) => item.id !== message.id,
        )
        const existingIndex = this.snapshot.messages.findIndex(
          (item) => item.id === message.id,
        )
        if (existingIndex < 0) messages.push(message)
        else messages.splice(existingIndex, 0, message)
        this.update({
          messages,
          draft:
            this.snapshot.draft?.requestId === message.requestId &&
            message.role === 'assistant'
              ? undefined
              : this.snapshot.draft,
        })
        if (message.role === 'user') {
          this.pending.get(message.requestId)?.resolve()
          this.pending.delete(message.requestId)
        }
        break
      }
      case 'reply_started':
        if (this.suppressOutput) break
        this.activeRequest = event.requestId
        this.sampleRate = undefined
        this.player.begin(event.requestId)
        this.update({
          generating: true,
          draft: { requestId: event.requestId, text: '' },
        })
        break
      case 'text_delta':
        if (!this.suppressOutput && event.requestId === this.activeRequest) {
          this.update({
            draft: {
              requestId: event.requestId,
              text: (this.snapshot.draft?.text ?? '') + event.text,
            },
          })
        }
        break
      case 'generation_finished':
        if (event.requestId === this.activeRequest)
          this.update({ generating: false })
        break
      case 'reply_stopped':
        this.suppressOutput = false
        if (
          event.requestId === this.activeRequest ||
          event.requestId === null
        ) {
          this.activeRequest = undefined
          this.player.stop()
          this.update({ generating: false, playing: false })
        }
        break
      case 'audio_format':
        if (event.requestId === this.activeRequest)
          this.sampleRate = event.sampleRate
        break
      case 'audio_finished':
        this.player.finish(event.requestId)
        break
      case 'partial':
        this.update({ partial: event.text })
        break
      case 'final':
        this.update({ partial: '' })
        break
      case 'recording_ready':
        if (this.snapshot.recording === 'preparing') {
          this.microphone?.start()
          this.update({ recording: 'recording' })
        }
        break
      case 'recording_stopped':
        this.recordingAbort?.abort()
        this.microphone?.dispose()
        this.recordingRequested = false
        this.update({ recording: 'idle', partial: '' })
        break
      case 'compaction_started':
        this.update({ compacting: true })
        break
      case 'compaction_finished':
        this.update({ compacting: false })
        break
      case 'error':
        this.update({ error: event.message })
        if (event.requestId) {
          this.pending.get(event.requestId)?.reject(new Error(event.message))
          this.pending.delete(event.requestId)
        }
        break
    }
  }

  private receiveAudio(packet: ArrayBuffer): void {
    if (packet.byteLength < 16) throw new Error('音频帧缺少回复标识。')
    const hex = Array.from(new Uint8Array(packet, 0, 16), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('')
    const requestId = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
    if (this.suppressOutput || requestId !== this.activeRequest) return
    if (!this.sampleRate) throw new Error('音频格式尚未声明。')
    this.player.append(requestId, packet.slice(16), this.sampleRate)
    this.update({ playing: true })
  }

  private releaseDevices(): void {
    this.recordingAbort?.abort()
    this.microphone?.dispose()
    this.recordingRequested = false
    this.update({ recording: 'idle' })
    void this.player.dispose().catch(() => console.warn('播放设备释放失败。'))
  }
  private rejectPending(error: Error): void {
    this.pending.forEach((pending) => pending.reject(error))
    this.pending.clear()
  }
  private report(error: unknown): void {
    this.update({
      error: error instanceof Error ? error.message : '操作失败。',
    })
  }

  private update(change: Partial<Snapshot>): void {
    this.snapshot = { ...this.snapshot, ...change }
    this.listeners.forEach((listener) => listener())
  }
}
