// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'
import { SessionConnection } from '../src/features/dialogue/sessionConnection'
import { BrowserSocket, installBrowserAudio } from './browserAudio'
afterEach(() => vi.unstubAllGlobals())

test('已到达的字时间允许提前播放；缺失尾部时间不丢音频，实际播完才确认结束', async () => {
  const { sources } = installBrowserAudio()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general']
              : {
                  session_id: '1',
                  title: 'Test',
                  status: 'active',
                  messages: [],
                },
          ),
        ),
    ),
  )
  const connection = new SessionConnection('1')
  connection.connect()
  await vi.waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  socket.deliver({ type: 'connected', can_control: true, messages: [] })
  await connection.startSession()
  const requestId = '11111111-1111-4111-8111-111111111111'
  socket.deliver({ type: 'reply_started', request_id: requestId })
  socket.deliver({
    type: 'audio_format',
    request_id: requestId,
    sample_rate: 24000,
    channels: 1,
    encoding: 'pcm_s16le',
  })
  const packet = new ArrayBuffer(16 + 48000)
  const bytes = requestId.replaceAll('-', '').match(/../g) ?? []
  new Uint8Array(packet, 0, 16).set(bytes.map((byte) => parseInt(byte, 16)))
  const timing = {
    type: 'text_timing',
    request_id: requestId,
    segment_index: 0,
    text: '你好。',
    start_seconds: 0,
    end_seconds: null,
    words: null,
  }
  socket.deliver(timing)
  socket.onmessage?.({ data: packet })
  expect(sources).toHaveLength(0)
  socket.deliver({
    ...timing,
    words: [{ text: '你好', start_seconds: 0, end_seconds: 1 }],
  })
  expect(sources).toHaveLength(1)
  socket.onmessage?.({ data: packet })
  socket.deliver({ type: 'audio_finished', request_id: requestId })
  expect(sources).toHaveLength(2)
  const finished = () =>
    socket.sent.filter(
      (item) => JSON.parse(String(item)).type === 'playback_finished',
    )
  expect(finished()).toHaveLength(0)
  sources.forEach((source) => source.onended?.())
  expect(finished()).toHaveLength(1)
  connection.dispose()
})

test('合成时间按段更新，生成结束不结束字幕，停止后拒绝迟到字幕', async () => {
  installBrowserAudio()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general']
              : {
                  session_id: '1',
                  title: 'Test',
                  status: 'active',
                  messages: [],
                },
          ),
        ),
    ),
  )
  const connection = new SessionConnection('1')
  connection.connect()
  await vi.waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  socket.deliver({ type: 'connected', can_control: true, messages: [] })
  socket.deliver({ type: 'reply_started', request_id: 'reply' })
  const timing = {
    type: 'text_timing',
    request_id: 'reply',
    segment_index: 0,
    text: '你好。',
    start_seconds: 0,
    end_seconds: null,
    words: null,
  }
  socket.deliver(timing)
  socket.deliver({ ...timing, end_seconds: 1 })
  socket.deliver({ type: 'generation_finished', request_id: 'reply' })
  expect(connection.getSnapshot().speech?.timings).toEqual([
    { index: 0, text: '你好。', start: 0, end: 1, words: null },
  ])
  expect(connection.getSnapshot().speech?.status).not.toBe('finished')
  connection.stopReply()
  socket.deliver({ ...timing, segment_index: 1, text: '旧字幕' })
  expect(connection.getSnapshot().speech?.status).toBe('stopped')
  expect(connection.getSnapshot().speech?.timings).toHaveLength(1)
  connection.dispose()
})

test('回复期间暂停收音，结束后仅在用户仍开启麦克风时恢复', async () => {
  const { getUserMedia, track } = installBrowserAudio()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general']
              : {
                  session_id: '1',
                  title: 'Test',
                  status: 'active',
                  messages: [],
                },
          ),
        ),
    ),
  )
  const connection = new SessionConnection('1')
  connection.connect()
  await vi.waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  socket.deliver({ type: 'connected', can_control: true, messages: [] })
  await connection.startRecording('general')
  socket.deliver({ type: 'recording_ready' })
  socket.deliver({ type: 'runtime_state', busy: true, allow_interrupt: false })
  expect(track.stop).toHaveBeenCalled()
  socket.deliver({ type: 'recording_stopped', paused: true })
  expect(getUserMedia).toHaveBeenCalledTimes(1)
  socket.deliver({ type: 'runtime_state', busy: false, allow_interrupt: false })
  await vi.waitFor(() =>
    expect(
      socket.sent.filter(
        (item) => JSON.parse(String(item)).type === 'start_recording',
      ),
    ).toHaveLength(2),
  )
  socket.deliver({ type: 'recording_ready' })
  socket.deliver({ type: 'runtime_state', busy: true, allow_interrupt: false })
  await connection.stopRecording()
  socket.deliver({ type: 'recording_stopped', paused: true })
  socket.deliver({ type: 'runtime_state', busy: false, allow_interrupt: false })
  expect(connection.getSnapshot().recordingWanted).toBe(false)
  expect(getUserMedia).toHaveBeenCalledTimes(2)
  connection.dispose()
})

test('关闭打断时拒绝发送，服务端释放忙碌后重新允许发送', async () => {
  installBrowserAudio()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general']
              : {
                  session_id: '1',
                  title: 'Test',
                  status: 'active',
                  messages: [],
                },
          ),
        ),
    ),
  )
  const connection = new SessionConnection('1')
  connection.connect()
  await vi.waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  socket.deliver({ type: 'connected', can_control: true, messages: [] })
  connection.setInteraction(false)
  socket.deliver({ type: 'runtime_state', busy: true, allow_interrupt: false })
  await expect(connection.submit('Hold this', 'general')).rejects.toThrow()
  expect(socket.sent.map((item) => JSON.parse(String(item)).type)).toEqual([
    'set_interaction',
  ])
  socket.deliver({ type: 'runtime_state', busy: false, allow_interrupt: false })
  const submitted = connection.submit('Now', 'general')
  await vi.waitFor(() => expect(socket.sent).toHaveLength(2))
  const command = JSON.parse(String(socket.sent[1]))
  socket.deliver({
    type: 'message_saved',
    message: {
      message_id: '1',
      request_id: command.request_id,
      message_kind: 'user_message',
      message_json: { display_content: [{ type: 'text', text: 'Now' }] },
    },
  })
  await submitted
  connection.dispose()
})

test('语音合成失败不提前结束文字生成', async () => {
  installBrowserAudio()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general']
              : {
                  session_id: '1',
                  title: 'Test',
                  status: 'active',
                  messages: [],
                },
          ),
        ),
    ),
  )
  const connection = new SessionConnection('1')
  connection.connect()
  await vi.waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  socket.deliver({ type: 'connected', can_control: true, messages: [] })
  socket.deliver({ type: 'reply_started', request_id: 'test-reply' })
  socket.deliver({
    type: 'error',
    request_id: 'test-reply',
    code: 'TTS_FAILED',
    message: '语音合成失败',
  })
  expect(connection.getSnapshot().generating).toBe(true)
  socket.deliver({
    type: 'text_delta',
    request_id: 'test-reply',
    text: '文字仍继续',
  })
  expect(connection.getSnapshot().draft?.text).toBe('文字仍继续')
  socket.deliver({ type: 'generation_finished', request_id: 'test-reply' })
  expect(connection.getSnapshot().generating).toBe(false)
  connection.dispose()
})
