/** 管理回复 PCM 的顺序播放和取消，不管理模型生成状态。 */
export class AudioPlayer {
  private context?: AudioContext
  private requestId?: string
  private sources = new Set<AudioBufferSourceNode>()
  private nextTime = 0
  private inputFinished = false
  constructor(private onFinished: (requestId: string) => void) {}

  /** 在点击发送或开始录音时调用，取得浏览器播放许可。 */
  async unlock(): Promise<void> {
    this.context ??= new AudioContext()
    await this.context.resume()
  }
  begin(requestId: string): void {
    this.stop()
    this.requestId = requestId
  }
  append(requestId: string, pcm: ArrayBuffer, sampleRate: number): void {
    if (requestId !== this.requestId) return
    if (!this.context || this.context.state !== 'running') {
      throw new Error('浏览器尚未允许播放，请点击发送或开始说话。')
    }
    if (pcm.byteLength % 2 !== 0 || sampleRate <= 0)
      throw new Error('音频格式错误。')
    if (pcm.byteLength === 0) return
    const buffer = this.context.createBuffer(1, pcm.byteLength / 2, sampleRate)
    const channel = buffer.getChannelData(0)
    const samples = new DataView(pcm)
    for (let i = 0; i < channel.length; i++)
      channel[i] = samples.getInt16(i * 2, true) / 32768
    const source = this.context.createBufferSource()
    source.buffer = buffer
    source.connect(this.context.destination)
    this.sources.add(source)
    source.onended = () => {
      this.sources.delete(source)
      source.disconnect()
      this.notifyFinished()
    }
    const start = Math.max(this.nextTime, this.context.currentTime + 0.02)
    source.start(start)
    this.nextTime = start + buffer.duration
  }
  finish(requestId: string): void {
    if (requestId !== this.requestId) return
    this.inputFinished = true
    this.notifyFinished()
  }
  stop(): void {
    this.requestId = undefined
    this.inputFinished = false
    for (const source of this.sources) {
      source.onended = null
      source.stop()
      source.disconnect()
    }
    this.sources.clear()
    this.nextTime = 0
  }
  async dispose(): Promise<void> {
    this.stop()
    await this.context?.close()
  }
  private notifyFinished(): void {
    if (!this.inputFinished || this.sources.size || !this.requestId) return
    const requestId = this.requestId
    this.requestId = undefined
    this.onFinished(requestId)
  }
}
