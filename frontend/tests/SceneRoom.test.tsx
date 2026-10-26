// @vitest-environment jsdom
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
  fireEvent,
} from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { SceneRoom } from '../src/features/dialogue/SceneRoom'
import { BrowserSocket, installBrowserAudio } from './browserAudio'

function Dialogue({ sessionId }: { sessionId: string }) {
  return (
    <SceneRoom
      sessionId={sessionId}
      scene={null}
      initialDraft=""
      onDraftChange={() => {}}
      onBack={() => {}}
      onSelect={() => {}}
      onNew={() => {}}
      onEdit={() => {}}
      onSceneChanged={() => {}}
    />
  )
}
function revealControls() {
  const button = screen.queryByRole('button', {
    name: '展开底部操作和文字输入',
  })
  if (button) fireEvent.click(button)
}
function commands(socket: BrowserSocket) {
  return socket.sent.filter(
    (item) =>
      typeof item !== 'string' || JSON.parse(item).type !== 'set_interaction',
  )
}

const savedUser = {
  message_id: '11',
  session_id: '1',
  request_id: '11111111-1111-4111-8111-111111111111',
  message_kind: 'user_message',
  message_json: {
    display_content: [{ type: 'text', text: 'Saved greeting' }],
    source: 'text',
  },
}

function installApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/presets')
              ? ['general', 'english']
              : {
                  session_id: '1',
                  title: 'Practice',
                  status: 'active',
                  messages: [savedUser],
                },
          ),
          { status: 200 },
        ),
    ),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

test('打开会话显示保存的消息，不重新提交或自动播放', async () => {
  installApi()
  installBrowserAudio()
  render(<Dialogue sessionId="1" />)
  await screen.findByText('Saved greeting')
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  act(() =>
    BrowserSocket.instances[0].deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  expect(commands(BrowserSocket.instances[0])).toEqual([])
})

test('发送文字后显示回复增量，并由保存消息替换临时回复', async () => {
  installApi()
  installBrowserAudio()
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  revealControls()
  fireEvent.change(screen.getByRole('textbox', { name: '输入消息' }), {
    target: { value: 'Hello' },
  })
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }))
  await waitFor(() => expect(commands(socket).length).toBe(1))
  const command = JSON.parse(String(commands(socket)[0]))
  fireEvent.change(screen.getByRole('textbox', { name: '输入消息' }), {
    target: { value: '下一句草稿' },
  })
  act(() => {
    socket.deliver({
      type: 'message_saved',
      message: {
        ...savedUser,
        message_id: '12',
        request_id: command.request_id,
        message_json: {
          display_content: [{ type: 'text', text: 'Hello' }],
          source: 'text',
        },
      },
    })
    socket.deliver({ type: 'reply_started', request_id: command.request_id })
    socket.deliver({
      type: 'text_delta',
      request_id: command.request_id,
      text: 'Hello back',
    })
  })
  expect(screen.getByText('Hello back')).toBeDefined()
  await act(async () =>
    socket.deliver({
      type: 'message_saved',
      message: {
        message_id: '13',
        request_id: command.request_id,
        message_kind: 'assistant_message',
        message_json: {
          content: [{ type: 'text', text: 'Hello back' }],
          status: 'completed',
        },
      },
    }),
  )
  expect(screen.getAllByText('Hello back')).toHaveLength(1)
  expect(
    (screen.getByRole('textbox', { name: '输入消息' }) as HTMLTextAreaElement)
      .value,
  ).toBe('下一句草稿')
})

test('结束录音发送尾部 PCM 并等待确认，final 不由浏览器重复提交', async () => {
  installApi()
  installBrowserAudio()
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  fireEvent.click(
    screen.getByRole('button', { name: '展开底部操作和文字输入' }),
  )
  revealControls()
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(commands(socket).length).toBe(1))
  act(() => socket.deliver({ type: 'recording_ready' }))
  fireEvent.click(screen.getByRole('button', { name: '停止说话' }))
  await waitFor(() => expect(commands(socket).length).toBe(3))
  expect(commands(socket)[1]).toBeInstanceOf(ArrayBuffer)
  expect(JSON.parse(String(commands(socket)[2])).type).toBe('stop_recording')
  act(() => {
    socket.deliver({ type: 'final', segment_id: 1, text: 'Tail' })
    socket.deliver({ type: 'recording_stopped' })
  })
  expect(
    commands(socket)
      .filter((item) => typeof item === 'string')
      .map((item) => JSON.parse(String(item)).type),
  ).toEqual(['start_recording', 'stop_recording'])
  expect(screen.getByRole('button', { name: '开始说话' })).toBeDefined()
})

test('麦克风权限拒绝后保留会话，并允许重试录音', async () => {
  installApi()
  const { getUserMedia } = installBrowserAudio()
  getUserMedia.mockRejectedValueOnce(
    new DOMException('denied', 'NotAllowedError'),
  )
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  revealControls()
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toContain('麦克风权限'),
  )
  revealControls()
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(commands(socket)).toHaveLength(1))
})

test('取消权限等待后释放晚到设备，不启动服务端录音', async () => {
  installApi()
  const { getUserMedia, track } = installBrowserAudio()
  let grant:
    ((stream: { getTracks: () => (typeof track)[] }) => void) | undefined
  getUserMedia.mockReturnValueOnce(
    new Promise((resolve) => {
      grant = resolve
    }),
  )
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  revealControls()
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  fireEvent.click(screen.getByRole('button', { name: '停止说话' }))
  await act(async () => grant?.({ getTracks: () => [track] }))
  expect(track.stop).toHaveBeenCalled()
  expect(commands(socket)).toHaveLength(0)
})

test('切换会话后释放旧录音并忽略旧连接的迟到消息', async () => {
  installApi()
  const { track } = installBrowserAudio()
  const view = render(<Dialogue key="1" sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const old = BrowserSocket.instances[0]
  act(() =>
    old.deliver({
      type: 'connected',
      session_id: '1',
      can_control: true,
      messages: [savedUser],
    }),
  )
  revealControls()
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(commands(old)).toHaveLength(1))
  view.rerender(<Dialogue key="2" sessionId="2" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(2))
  act(() => old.deliver({ type: 'partial', text: 'Old audio' }))
  expect(track.stop).toHaveBeenCalled()
  expect(screen.queryByText('Old audio')).toBeNull()
})

test('播放设备不可用时仍提交文字，显示错误且不重复模型请求', async () => {
  installApi()
  installBrowserAudio()
  vi.stubGlobal(
    'AudioContext',
    class {
      state = 'suspended'
      async resume() {
        throw new Error('播放设备不可用')
      }
      async close() {}
    },
  )
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      can_control: true,
      messages: [savedUser],
    }),
  )
  revealControls()
  fireEvent.change(screen.getByRole('textbox', { name: '输入消息' }), {
    target: { value: 'Hello' },
  })
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }))
  await waitFor(() => expect(commands(socket)).toHaveLength(1))
  expect(screen.getByRole('alert').textContent).toContain('播放设备不可用')
  expect(JSON.parse(String(commands(socket)[0])).text).toBe('Hello')
})

test('连接确认采用服务端最新消息，补齐 HTTP 读取之后保存的回复', async () => {
  installApi()
  installBrowserAudio()
  render(<Dialogue sessionId="1" />)
  await screen.findByText('Saved greeting')
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  act(() =>
    BrowserSocket.instances[0].deliver({
      type: 'connected',
      can_control: true,
      messages: [
        savedUser,
        {
          message_id: '12',
          request_id: savedUser.request_id,
          message_kind: 'assistant_message',
          message_json: {
            content: [{ type: 'text', text: 'Saved while reconnecting' }],
            status: 'cancelled',
          },
        },
      ],
    }),
  )
  expect(screen.getByText('Saved while reconnecting')).toBeDefined()
})

test('设置面板切换打断并保存当前浏览器偏好', async () => {
  installApi()
  installBrowserAudio()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  render(<Dialogue sessionId="1" />)
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() =>
    socket.deliver({
      type: 'connected',
      can_control: true,
      messages: [savedUser],
    }),
  )
  fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
  fireEvent.click(screen.getByRole('switch', { name: '允许打断回复' }))
  expect(JSON.parse(String(socket.sent.at(-1)))).toEqual({
    type: 'set_interaction',
    allow_interrupt: false,
  })
  fireEvent.click(screen.getByRole('button', { name: '关闭面板' }))
  fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
  expect(
    screen
      .getByRole('switch', { name: '允许打断回复' })
      .getAttribute('aria-checked'),
  ).toBe('false')
})
