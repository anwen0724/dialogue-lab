import { afterEach, expect, test, vi } from 'vitest'
import { AudioPlayer } from '../src/features/voice-output/audioPlayer'

class AudioDevice {
  static sources: {
    start: ReturnType<typeof vi.fn>
    stop: ReturnType<typeof vi.fn>
    onended: (() => void) | null
    buffer?: { duration: number }
  }[] = []
  currentTime = 1
  state = 'running'
  destination = {}
  async resume() {}
  async close() {}
  createBuffer(_channels: number, length: number, sampleRate: number) {
    return {
      duration: length / sampleRate,
      getChannelData: () => new Float32Array(length),
    }
  }
  createBufferSource() {
    const source = {
      start: vi.fn(),
      stop: vi.fn(),
      connect() {},
      disconnect() {},
      onended: null as (() => void) | null,
    }
    AudioDevice.sources.push(source)
    return source
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  AudioDevice.sources = []
})

test('网络结束后仍等待已排队音频播放完毕', async () => {
  vi.stubGlobal('AudioContext', AudioDevice)
  const finished = vi.fn()
  const player = new AudioPlayer(finished)
  await player.unlock()
  player.begin('reply')
  player.append('reply', new ArrayBuffer(48000), 24000)
  player.append('reply', new ArrayBuffer(48000), 24000)
  player.finish('reply')
  expect(finished).not.toHaveBeenCalled()
  expect(AudioDevice.sources[1].start.mock.calls[0][0]).toBe(
    AudioDevice.sources[0].start.mock.calls[0][0] + 1,
  )
  AudioDevice.sources[0].onended?.()
  expect(finished).not.toHaveBeenCalled()
  AudioDevice.sources[1].onended?.()
  expect(finished).toHaveBeenCalledWith('reply')
})

test('停止清空排队音频，新的回复不接受旧音频', async () => {
  vi.stubGlobal('AudioContext', AudioDevice)
  const finished = vi.fn()
  const player = new AudioPlayer(finished)
  await player.unlock()
  player.begin('old')
  player.append('old', new ArrayBuffer(48000), 24000)
  player.stop()
  expect(AudioDevice.sources[0].stop).toHaveBeenCalled()
  player.begin('new')
  player.append('old', new ArrayBuffer(48000), 24000)
  player.finish('old')
  expect(AudioDevice.sources).toHaveLength(1)
  expect(finished).not.toHaveBeenCalled()
})
