/** 仅替换浏览器设备和网络边界，让真实页面与控制逻辑运行。 */
import { vi } from 'vitest'

export class BrowserSocket {
  static instances: BrowserSocket[] = []
  static OPEN = 1
  static CONNECTING = 0
  readyState = 1
  bufferedAmount = 0
  sent: (string | ArrayBuffer)[] = []
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor() {
    BrowserSocket.instances.push(this)
  }
  send(message: string | ArrayBuffer) {
    this.sent.push(message)
  }
  close() {
    this.readyState = 3
  }
  deliver(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

export class BrowserWorklet {
  static instances: BrowserWorklet[] = []
  onprocessorerror: (() => void) | null = null
  port = {
    onmessage: null as ((event: { data: unknown }) => void) | null,
    close: () => {},
    postMessage: () => {
      this.port.onmessage?.({ data: new ArrayBuffer(4) })
      this.port.onmessage?.({ data: { type: 'stopped' } })
    },
  }
  constructor() {
    BrowserWorklet.instances.push(this)
  }
  connect() {}
  disconnect() {}
}

export function installBrowserAudio() {
  BrowserSocket.instances = []
  BrowserWorklet.instances = []
  const track = {
    stop: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [track] })
  vi.stubGlobal('WebSocket', BrowserSocket)
  vi.stubGlobal('AudioWorkletNode', BrowserWorklet)
  vi.stubGlobal(
    'AudioContext',
    class {
      sampleRate = 16000
      state = 'running'
      destination = {}
      audioWorklet = { addModule: async () => {} }
      resume = async () => {}
      close = async () => {
        this.state = 'closed'
      }
      createMediaStreamSource = () => ({ connect() {}, disconnect() {} })
    },
  )
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  })
  return { track, getUserMedia }
}
