/** 音频线程将 16 kHz 单声道浮点样本分帧为小端 PCM16。 */
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}

declare function registerProcessor(
  name: string,
  processor: typeof AudioWorkletProcessor,
): void

class PcmProcessor extends AudioWorkletProcessor {
  private frame = new ArrayBuffer(640)
  private view = new DataView(this.frame)
  private samples = 0
  private stopped = false

  constructor() {
    super()
    this.port.onmessage = (event: MessageEvent<unknown>) => {
      if (
        typeof event.data === 'object' &&
        event.data !== null &&
        'type' in event.data &&
        event.data.type === 'stop'
      ) {
        this.flush()
        this.stopped = true
        this.port.postMessage({ type: 'stopped' })
      }
    }
  }

  process(inputs: Float32Array[][]): boolean {
    if (this.stopped) return false
    const input = inputs[0]?.[0]
    if (!input) return true
    for (const sample of input) {
      const clamped = Math.max(-1, Math.min(1, sample))
      this.view.setInt16(
        this.samples * 2,
        Math.round(clamped * (clamped < 0 ? 32768 : 32767)),
        true,
      )
      this.samples += 1
      if (this.samples === 320) this.flush()
    }
    return true
  }

  private flush(): void {
    if (!this.samples) return
    const audio = this.frame.slice(0, this.samples * 2)
    this.port.postMessage(audio, [audio])
    this.samples = 0
  }
}

registerProcessor('pcm-input', PcmProcessor)
