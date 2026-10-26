// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HomePage } from '../src/pages/HomePage'
import { BrowserSocket, installBrowserAudio } from './browserAudio'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
  localStorage.clear()
})

test('只有会话链接时仍恢复所属场景', async () => {
  installBrowserAudio()
  window.history.replaceState(null, '', '?session=42')
  const scene = {
    scene_id: '3',
    name: '我的空间',
    category: '英语',
    character_name: 'Emma',
    cover_image: null,
    background_image: null,
    status: 'active',
    system_prompt: 'Be Emma.',
  }
  const session = {
    session_id: '42',
    scene_id: '3',
    title: '练习',
    status: 'active',
    messages: [],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/scenes')
              ? [scene]
              : url.endsWith('/scenes/3')
                ? scene
                : url.endsWith('/presets')
                  ? ['general']
                  : url.endsWith('/sessions')
                    ? [session]
                    : session,
          ),
        ),
    ),
  )
  render(<HomePage />)
  expect(await screen.findByRole('heading', { name: '我的空间' })).toBeDefined()
  expect(window.location.search).toBe('?scene=3&session=42')
})

test('进入场景后创建并恢复会话标识，旧会话存在时直接继续', async () => {
  installBrowserAudio()
  const scene = {
    scene_id: '3',
    name: '窗边咖啡馆',
    category: '英语交流',
    character_name: 'Emma',
    cover_image: null,
    background_image: null,
    status: 'active',
    system_prompt: 'Be Emma.',
  }
  const session = {
    session_id: '42',
    scene_id: '3',
    title: '新会话',
    status: 'active',
    messages: [],
  }
  let created = false
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown = session
    if (url.endsWith('/scenes')) result = [scene]
    else if (url.endsWith('/scenes/3')) result = scene
    else if (url.endsWith('/presets')) result = ['general']
    else if (url.includes('/sessions') && !url.includes('/sessions/42')) {
      if (options?.method === 'POST') created = true
      else result = created ? [session] : []
    }
    return new Response(JSON.stringify(result), { status: 200 })
  })
  vi.stubGlobal('fetch', fetcher)
  render(<HomePage />)
  fireEvent.click(await screen.findByRole('button', { name: /进入窗边咖啡馆/ }))
  await waitFor(() =>
    expect(window.location.search).toBe('?scene=3&session=42'),
  )
  expect(
    await screen.findByRole('button', { name: '打开当前会话消息' }),
  ).toBeDefined()
  await waitFor(() => expect(BrowserSocket.instances).toHaveLength(1))
  act(() =>
    BrowserSocket.instances[0].deliver({
      type: 'connected',
      can_control: true,
      messages: [],
    }),
  )
  await waitFor(() =>
    expect(
      BrowserSocket.instances[0].sent.some(
        (item) => JSON.parse(String(item)).type === 'start_session',
      ),
    ).toBe(true),
  )
  fireEvent.click(screen.getByRole('button', { name: '返回场景选择' }))
  fireEvent.click(await screen.findByRole('button', { name: /进入窗边咖啡馆/ }))
  await waitFor(() =>
    expect(window.location.search).toBe('?scene=3&session=42'),
  )
  expect(
    fetcher.mock.calls.filter(([, options]) => options?.method === 'POST'),
  ).toHaveLength(1)
})
