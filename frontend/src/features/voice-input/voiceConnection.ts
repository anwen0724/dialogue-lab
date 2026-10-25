/** 管理一次网页语音输入及其消息；设备与网络对象不放入 React 状态。 */
import { Microphone } from './microphone'

export type UserMessage = { id: string; role: 'user'; text: string }
type PartialText = { segmentId: number; text: string }
type InputState =
  | { status: 'idle' | 'preparing' | 'listening' | 'stopping' }
  | { status: 'error'; message: string }

export type VoiceSnapshot = {
  state: InputState
  partials: PartialText[]
  messages: UserMessage[]
}

type ServerEvent =
  | { type: 'ready' | 'stopped' }
  | { type: 'partial' | 'final'; segment_id: number; text: string }
  | { type: 'error'; code: string; message: string }

type InputRun = {
  id: number
  abort: AbortController
  microphone?: Microphone
  socket?: WebSocket
  timer?: ReturnType<typeof setTimeout>
  finalized: Set<number>
}

export class VoiceConnection {
  private snapshot: VoiceSnapshot = {
    state: { status: 'idle' },
    partials: [],
    messages: [],
  }
  private listeners = new Set<() => void>()
  private active?: InputRun
  private nextRun = 0

  getSnapshot = (): VoiceSnapshot => this.snapshot
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** 开始新输入；旧连接迟到的事件不能写入新输入。 */
  async start(): Promise<void> {
    if (this.active) return
    const run: InputRun = {
      id: ++this.nextRun,
      abort: new AbortController(),
      finalized: new Set(),
    }
    this.active = run
    this.update({ state: { status: 'preparing' }, partials: [] })
    try {
      run.microphone = await Microphone.open(
        (audio) => this.sendAudio(run, audio),
        (error) => this.fail(run, error.message),
        run.abort.signal,
      )
      if (this.active !== run) return
      const url = new URL('/api/voice/input', window.location.href)
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      run.socket = new WebSocket(url)
      run.socket.onmessage = (event: MessageEvent<unknown>) => {
        if (this.active !== run) return
        try {
          this.receive(run, parseEvent(event.data))
        } catch {
          this.fail(run, '收到无法识别的服务响应，请重新开始。')
        }
      }
      run.socket.onerror = () =>
        this.fail(run, '无法连接语音服务，请检查后端是否启动。')
      run.socket.onclose = () => this.fail(run, '语音连接已断开，请重新开始。')
      run.timer = setTimeout(
        () => this.fail(run, '语音服务准备超时，请检查后端后重试。'),
        15000,
      )
    } catch (error) {
      const message =
        error instanceof DOMException && error.name === 'NotAllowedError'
          ? '麦克风权限未开启，请允许浏览器使用麦克风后重试。'
          : error instanceof Error
            ? error.message
            : '无法启动麦克风，请检查设备。'
      this.fail(run, message)
    }
  }

  private sendAudio(run: InputRun, audio: ArrayBuffer): void {
    if (this.active !== run || run.socket?.readyState !== WebSocket.OPEN) return
    if (run.socket.bufferedAmount > 64000) {
      this.fail(run, '音频上传积压，请检查网络后重新开始。')
      return
    }
    run.socket.send(audio)
  }

  /** 正常结束保持连接，直到服务端交付尾句并确认资源关闭。 */
  async stop(): Promise<void> {
    const run = this.active
    if (!run || this.snapshot.state.status === 'stopping') return
    if (this.snapshot.state.status === 'preparing') {
      this.dispose()
      this.update({ state: { status: 'idle' }, partials: [] })
      return
    }
    this.update({ state: { status: 'stopping' } })
    try {
      await run.microphone?.stop()
      if (this.active !== run) return
      if (run.socket?.readyState !== WebSocket.OPEN)
        throw new Error('语音连接已断开。')
      run.socket.send(JSON.stringify({ type: 'stop' }))
      run.timer = setTimeout(
        () => this.fail(run, '等待识别结束超时，最后一段可能未完成。'),
        40000,
      )
    } catch (error) {
      this.fail(run, error instanceof Error ? error.message : '无法结束录音。')
    }
  }

  private receive(run: InputRun, event: ServerEvent): void {
    if (event.type === 'ready') {
      if (this.snapshot.state.status !== 'preparing') return
      clearTimeout(run.timer)
      run.microphone?.start()
      this.update({ state: { status: 'listening' } })
    } else if (event.type === 'error') {
      this.fail(run, event.message)
    } else if (event.type === 'stopped') {
      this.dispose()
      this.update({ state: { status: 'idle' }, partials: [] })
    } else if ('segment_id' in event && !run.finalized.has(event.segment_id)) {
      const partials = this.snapshot.partials.filter(
        (item) => item.segmentId !== event.segment_id,
      )
      if (event.type === 'partial') {
        this.update({
          partials: [
            ...partials,
            { segmentId: event.segment_id, text: event.text },
          ],
        })
      } else {
        run.finalized.add(event.segment_id)
        const text = event.text.trim()
        this.update({
          partials,
          messages: text
            ? [
                ...this.snapshot.messages,
                {
                  id: `${run.id}:${event.segment_id}`,
                  role: 'user',
                  text,
                },
              ]
            : this.snapshot.messages,
        })
      }
    }
  }

  private fail(run: InputRun, message: string): void {
    if (this.active !== run) return
    this.dispose()
    this.update({ state: { status: 'error', message }, partials: [] })
  }

  /** 页面卸载或异常退出；立即关闭设备和连接，不删除已确定消息。 */
  dispose = (): void => {
    const run = this.active
    if (!run) return
    this.active = undefined
    clearTimeout(run.timer)
    run.abort.abort()
    run.microphone?.dispose()
    run.socket?.close()
  }

  private update(change: Partial<VoiceSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...change }
    this.listeners.forEach((listener) => listener())
  }
}

/** 网络输入只在此处校验，内部使用可信事件类型。 */
function parseEvent(raw: unknown): ServerEvent {
  if (typeof raw !== 'string') throw new Error('事件必须是 JSON 文本')
  const event: unknown = JSON.parse(raw)
  if (typeof event !== 'object' || event === null || !('type' in event))
    throw new Error('事件无效')
  if (event.type === 'ready' || event.type === 'stopped')
    return { type: event.type }
  if (
    event.type === 'error' &&
    'code' in event &&
    typeof event.code === 'string' &&
    'message' in event &&
    typeof event.message === 'string'
  ) {
    return { type: event.type, code: event.code, message: event.message }
  }
  if (
    (event.type === 'partial' || event.type === 'final') &&
    'segment_id' in event &&
    typeof event.segment_id === 'number' &&
    Number.isSafeInteger(event.segment_id) &&
    'text' in event &&
    typeof event.text === 'string'
  ) {
    return { type: event.type, segment_id: event.segment_id, text: event.text }
  }
  throw new Error('未知事件')
}
