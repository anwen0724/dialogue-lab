// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'
import { SessionConnection } from '../src/features/dialogue/sessionConnection'
import { BrowserSocket, installBrowserAudio } from './browserAudio'
afterEach(() => vi.unstubAllGlobals())

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
