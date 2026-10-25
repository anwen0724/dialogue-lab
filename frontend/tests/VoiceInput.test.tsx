// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { VoiceInput } from '../src/features/voice-input/VoiceInput'
import { BrowserSocket, installBrowserAudio } from './browserAudio'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('临时文字持续更新，最终结果只形成一条用户消息', async () => {
  installBrowserAudio()
  render(<VoiceInput />)
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() => socket.deliver({ type: 'ready' }))
  expect(screen.getByRole('button', { name: '结束录音' })).toBeDefined()
  act(() => socket.deliver({ type: 'partial', segment_id: 1, text: '你好' }))
  expect(screen.getByLabelText('识别中的文字').textContent).toContain('你好')
  expect(
    within(screen.getByRole('list', { name: '用户消息' })).queryAllByRole(
      'listitem',
    ),
  ).toHaveLength(0)
  act(() =>
    socket.deliver({ type: 'partial', segment_id: 1, text: '你好世界' }),
  )
  act(() =>
    socket.deliver({ type: 'final', segment_id: 1, text: '你好，世界。' }),
  )
  act(() =>
    socket.deliver({ type: 'final', segment_id: 1, text: '你好，世界。' }),
  )
  const messages = within(
    screen.getByRole('list', { name: '用户消息' }),
  ).getAllByRole('listitem')
  expect(messages).toHaveLength(1)
  expect(messages[0].textContent).toContain('你好，世界。')
  expect(screen.getByLabelText('识别中的文字').textContent).not.toContain(
    '你好',
  )
})

test('结束时先发送剩余音频，再发送 stop，并等待尾句结果', async () => {
  const { track } = installBrowserAudio()
  render(<VoiceInput />)
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const socket = BrowserSocket.instances[0]
  act(() => socket.deliver({ type: 'ready' }))
  fireEvent.click(screen.getByRole('button', { name: '结束录音' }))
  await waitFor(() => expect(socket.sent).toHaveLength(2))
  expect(socket.sent[0]).toBeInstanceOf(ArrayBuffer)
  expect(socket.sent[1]).toBe(JSON.stringify({ type: 'stop' }))
  expect(track.stop).toHaveBeenCalled()
  expect(screen.getByRole('status').textContent).toContain('最后一句话')
  act(() =>
    socket.deliver({ type: 'final', segment_id: 1, text: '结束前的尾句' }),
  )
  act(() => socket.deliver({ type: 'stopped' }))
  expect(screen.getByRole('button', { name: '开始说话' })).toBeDefined()
  expect(screen.getByText('结束前的尾句')).toBeDefined()
  expect(socket.readyState).toBe(3)
})

test('麦克风权限拒绝时说明原因，并允许重新开始', async () => {
  const { getUserMedia } = installBrowserAudio()
  getUserMedia.mockRejectedValueOnce(
    new DOMException('denied', 'NotAllowedError'),
  )
  render(<VoiceInput />)
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() =>
    expect(screen.getByRole('alert').textContent).toContain('麦克风权限'),
  )
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
})

test('取消权限等待后，晚到的麦克风立即释放，不建立连接', async () => {
  const { getUserMedia, track } = installBrowserAudio()
  let grantPermission:
    ((stream: { getTracks: () => (typeof track)[] }) => void) | undefined
  getUserMedia.mockReturnValueOnce(
    new Promise((resolve) => {
      grantPermission = resolve
    }),
  )
  render(<VoiceInput />)
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  fireEvent.click(screen.getByRole('button', { name: '取消准备' }))
  await act(async () => {
    grantPermission?.({ getTracks: () => [track] })
  })
  expect(track.stop).toHaveBeenCalled()
  expect(BrowserSocket.instances).toHaveLength(0)
  expect(screen.getByRole('button', { name: '开始说话' })).toBeDefined()
})

test('断线后释放设备，重新开始不接受旧连接迟到的文字', async () => {
  const { track } = installBrowserAudio()
  render(<VoiceInput />)
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  const previous = BrowserSocket.instances[0]
  act(() => previous.deliver({ type: 'ready' }))
  act(() =>
    previous.deliver({ type: 'final', segment_id: 1, text: '已经确定的消息' }),
  )
  act(() => previous.onclose?.())
  expect(track.stop).toHaveBeenCalled()
  expect(screen.getByRole('alert').textContent).toContain('断开')
  fireEvent.click(screen.getByRole('button', { name: '开始说话' }))
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(2))
  act(() =>
    previous.deliver({ type: 'final', segment_id: 2, text: '旧连接的尾句' }),
  )
  const current = BrowserSocket.instances[1]
  act(() => current.deliver({ type: 'ready' }))
  act(() =>
    current.deliver({ type: 'final', segment_id: 1, text: '新连接的消息' }),
  )
  expect(screen.queryByText('旧连接的尾句')).toBeNull()
  expect(screen.getByText('已经确定的消息')).toBeDefined()
  expect(screen.getByText('新连接的消息')).toBeDefined()
})
