import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { expect, test } from 'vitest'

/** 在 Worklet 宿主边界运行真实处理器，观察对外 PCM 数据。 */
function loadProcessor() {
  const messages: unknown[] = []
  class HostProcessor {
    port = {
      onmessage: (event: { data: unknown }) => {
        void event
      },
      postMessage: (message: unknown) => messages.push(message),
    }
  }
  type Processor = HostProcessor & {
    process(inputs: Float32Array[][]): boolean
  }
  let processor: Processor | undefined
  const source = readFileSync(
    new URL('../src/features/voice-input/pcm.worklet.ts', import.meta.url),
    'utf8',
  )
  vm.runInNewContext(
    ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText,
    {
      AudioWorkletProcessor: HostProcessor,
      registerProcessor: (_name: string, constructor: new () => Processor) => {
        processor = new constructor()
      },
      ArrayBuffer,
      DataView,
    },
  )
  if (!processor) throw new Error('Worklet 未注册')
  return { processor, messages }
}

test('按 20 ms 输出小端 PCM16，并保留跨输入块的样本', () => {
  const { processor, messages } = loadProcessor()
  processor.process([[new Float32Array(128).fill(0.5)]])
  processor.process([[new Float32Array(128).fill(-1)]])
  expect(messages).toHaveLength(0)
  processor.process([[new Float32Array(128).fill(1)]])
  expect(messages).toHaveLength(1)
  expect(messages[0]).toBeInstanceOf(ArrayBuffer)
  const buffer = messages[0] as ArrayBuffer
  expect(buffer.byteLength).toBe(640)
  const pcm = new DataView(buffer)
  expect(pcm.getInt16(0, true)).toBe(16384)
  expect(pcm.getInt16(256, true)).toBe(-32768)
  expect(pcm.getInt16(512, true)).toBe(32767)
})

test('结束时先输出不足一帧的尾部音频，再确认停止', () => {
  const { processor, messages } = loadProcessor()
  processor.process([[new Float32Array([0.5, -0.5])]])
  processor.port.onmessage({ data: { type: 'stop' } })
  expect(messages).toHaveLength(2)
  expect(messages[0]).toBeInstanceOf(ArrayBuffer)
  expect((messages[0] as ArrayBuffer).byteLength).toBe(4)
  expect(messages[1]).toEqual({ type: 'stopped' })
  expect(processor.process([[new Float32Array(320)]])).toBe(false)
  expect(messages).toHaveLength(2)
})
