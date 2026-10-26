/** 只管理浏览器音频设备和 Worklet，不管理识别消息或页面状态。 */
import workletUrl from './pcm.worklet.ts?worker&url'

export class Microphone {
  private stream?: MediaStream
  private source?: MediaStreamAudioSourceNode
  private node?: AudioWorkletNode
  private analyser?: AnalyserNode
  private samples = new Float32Array(256)
  private disposed = false
  private stopWait?: {
    resolve: () => void
    reject: (error: Error) => void
    timer: ReturnType<typeof setTimeout>
  }

  private constructor(
    private context: AudioContext,
    private onError: (error: Error) => void,
  ) {}

  /** 在用户点击期间启动 AudioContext；允许取消尚未完成的权限申请。 */
  static async open(
    onAudio: (audio: ArrayBuffer) => void,
    onError: (error: Error) => void,
    signal: AbortSignal,
  ): Promise<Microphone> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        '浏览器无法使用麦克风，请通过 localhost 或 HTTPS 打开页面。',
      )
    }
    const microphone = new Microphone(
      new AudioContext({ sampleRate: 16000 }),
      onError,
    )
    signal.addEventListener('abort', () => microphone.dispose(), { once: true })
    try {
      // resume 在权限等待之前发起，保留用户操作带来的音频启动授权。
      const resumed = microphone.context.resume()
      const media = navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      // 设备晚到时仍交给对象释放，不让已经取消的申请留下麦克风占用。
      const streamReady = media.then((stream) => {
        microphone.stream = stream
        if (signal.aborted || microphone.disposed) {
          stream.getTracks().forEach((track) => track.stop())
          throw new DOMException('录音已取消', 'AbortError')
        }
      })
      await Promise.all([resumed, streamReady])
      if (microphone.context.sampleRate !== 16000) {
        throw new Error(
          '当前浏览器不支持所需的录音采样率，请使用新版 Chrome 或 Edge。',
        )
      }
      await microphone.context.audioWorklet.addModule(workletUrl)
      signal.throwIfAborted()
      microphone.node = new AudioWorkletNode(microphone.context, 'pcm-input', {
        channelCount: 1,
        channelCountMode: 'explicit',
      })
      microphone.node.port.onmessage = (event: MessageEvent<unknown>) => {
        if (!microphone.disposed && event.data instanceof ArrayBuffer)
          onAudio(event.data)
        if (
          typeof event.data === 'object' &&
          event.data !== null &&
          'type' in event.data &&
          event.data.type === 'stopped'
        ) {
          const wait = microphone.stopWait
          microphone.stopWait = undefined
          if (wait) {
            clearTimeout(wait.timer)
            wait.resolve()
          }
        }
      }
      microphone.node.onprocessorerror = () =>
        onError(new Error('录音处理失败，请重新开始。'))
      microphone.stream?.getTracks().forEach((track) => {
        track.addEventListener('ended', () => {
          if (!microphone.disposed)
            onError(new Error('麦克风已断开，请检查设备后重试。'))
        })
      })
      return microphone
    } catch (error) {
      microphone.dispose()
      throw error
    }
  }

  /** 后端 ready 后才接通处理图；Worklet 输出保持静音。 */
  start(): void {
    if (!this.stream || !this.node || this.disposed) return
    this.source = this.context.createMediaStreamSource(this.stream)
    this.analyser = this.context.createAnalyser()
    this.analyser.fftSize = 256
    this.source.connect(this.analyser)
    this.source.connect(this.node)
    this.node.connect(this.context.destination)
  }

  /** 麦克风已开启但没有声音时返回接近零的振幅。 */
  getAmplitude(): number {
    if (!this.analyser || this.disposed) return 0
    this.analyser.getFloatTimeDomainData(this.samples)
    return Math.sqrt(
      this.samples.reduce((sum, value) => sum + value * value, 0) /
        this.samples.length,
    )
  }

  /** 先停止采集，再等待 Worklet 发完尾部样本；由调用方随后发送 stop。 */
  async stop(): Promise<void> {
    if (this.disposed || !this.node) return
    this.stream?.getTracks().forEach((track) => track.stop())
    this.source?.disconnect()
    try {
      await new Promise<void>((resolve, reject) => {
        this.stopWait = {
          resolve,
          reject,
          timer: setTimeout(
            () => reject(new Error('录音收尾超时，最后一段可能未完成。')),
            2000,
          ),
        }
        this.node?.port.postMessage({ type: 'stop' })
      })
    } finally {
      this.dispose()
    }
  }

  /** 失败、取消或卸载时立即释放，不等待尾部识别。 */
  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    if (this.stopWait) {
      clearTimeout(this.stopWait.timer)
      this.stopWait.reject(new Error('录音已停止。'))
      this.stopWait = undefined
    }
    this.stream?.getTracks().forEach((track) => track.stop())
    this.source?.disconnect()
    this.analyser?.disconnect()
    this.node?.disconnect()
    this.node?.port.close()
    if (this.context.state !== 'closed') {
      void this.context
        .close()
        .catch(() => this.onError(new Error('音频设备未能正常关闭。')))
    }
  }
}
