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

test('复制角色后打开独立副本编辑，关闭面板仍保留副本且不创建会话', async () => {
  installBrowserAudio()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  const original = {
    character_id: '1',
    name: 'Emma',
    category: '英语',
    character_name: 'Emma',
    tts_voice: 'Emily_v3.1',
    voice_available: true,
    cover_image: null,
    background_image: null,
    status: 'active',
    system_prompt: 'Be Emma.',
  }
  const copied = { ...original, character_id: '2', name: 'Emma（副本）' }
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/characters/1/copy') && options?.method === 'POST')
      return Response.json(copied, { status: 201 })
    if (url.endsWith('/characters/2')) return Response.json(copied)
    if (url.endsWith('/characters')) return Response.json([original])
    if (url.endsWith('/sessions')) return Response.json([])
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  render(<HomePage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Emma的更多操作' }))
  fireEvent.click(screen.getByRole('button', { name: '复制角色' }))
  await screen.findByDisplayValue('Emma（副本）')
  expect(await screen.findByDisplayValue('Be Emma.')).toBeDefined()
  fireEvent.click(screen.getByRole('button', { name: '返回角色列表' }))
  expect(
    screen.getByRole('button', { name: '进入Emma', exact: true }),
  ).toBeDefined()
  expect(
    screen.getByRole('button', { name: '进入Emma（副本）', exact: true }),
  ).toBeDefined()
  expect(
    fetcher.mock.calls.filter(
      ([url, options]) =>
        url.endsWith('/sessions') && options?.method === 'POST',
    ),
  ).toHaveLength(0)
})

test('角色编辑可返回设置，保存后返回设置并更新人物名字', async () => {
  installBrowserAudio()
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  window.history.replaceState(null, '', '?session=42')
  let character = {
    character_id: '3',
    name: '窗边咖啡馆',
    category: '英语交流',
    character_name: 'Emma',
    tts_voice: 'longanhuan_v3.1',
    voice_available: true,
    cover_image: null,
    background_image: null,
    status: 'active',
    system_prompt: 'You are {{character_name}}.',
  }
  const session = {
    session_id: '42',
    character_id: '3',
    title: '练习',
    status: 'active',
    messages: [],
  }
  let saves = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/characters/3') && options?.method === 'PATCH') {
        saves++
        character = { ...character, ...JSON.parse(String(options.body)) }
      }
      return new Response(
        JSON.stringify(
          url.endsWith('/characters')
            ? [character]
            : url.endsWith('/characters/3')
              ? character
              : url.endsWith('/presets')
                ? ['general']
                : url.endsWith('/sessions')
                  ? [session]
                  : session,
        ),
      )
    }),
  )
  render(<HomePage />)
  await screen.findByRole('heading', { name: '窗边咖啡馆' })
  fireEvent.click(screen.getByRole('button', { name: '打开设置' }))
  fireEvent.click(screen.getByRole('button', { name: '角色资料与身份' }))
  await screen.findByDisplayValue('Emma')
  fireEvent.change(screen.getByLabelText('人物名字'), {
    target: { value: '未保存' },
  })
  fireEvent.click(screen.getByRole('button', { name: '返回设置' }))
  expect(screen.getByRole('heading', { name: '视觉氛围' })).toBeDefined()
  expect(saves).toBe(0)
  fireEvent.click(screen.getByRole('button', { name: '角色资料与身份' }))
  await screen.findByDisplayValue('Emma')
  fireEvent.change(screen.getByLabelText('人物名字'), {
    target: { value: 'Alice' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存角色' }))
  await screen.findByRole('heading', { name: '视觉氛围' })
  expect(saves).toBe(1)
  fireEvent.click(screen.getByRole('button', { name: '角色资料与身份' }))
  await screen.findByDisplayValue('Alice')
  fireEvent.click(screen.getByRole('button', { name: '关闭面板' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

test.each(['?session=42', '?scene=3&session=42'])(
  '恢复会话链接 %s 时保留所属角色',
  async (url) => {
    installBrowserAudio()
    window.history.replaceState(null, '', url)
    const character = {
      character_id: '3',
      name: '我的空间',
      category: '英语',
      character_name: 'Emma',
      tts_voice: 'longanhuan_v3.1',
      voice_available: true,
      cover_image: null,
      background_image: null,
      status: 'active',
      system_prompt: 'Be Emma.',
    }
    const session = {
      session_id: '42',
      character_id: '3',
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
              url.endsWith('/characters')
                ? [character]
                : url.endsWith('/characters/3')
                  ? character
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
    expect(
      await screen.findByRole('heading', { name: '我的空间' }),
    ).toBeDefined()
    expect(window.location.search).toBe('?character=3&session=42')
  },
)

test('进入角色后创建并恢复会话标识，旧会话存在时直接继续', async () => {
  installBrowserAudio()
  const character = {
    character_id: '3',
    name: '窗边咖啡馆',
    category: '英语交流',
    character_name: 'Emma',
    tts_voice: 'longanhuan_v3.1',
    voice_available: true,
    cover_image: null,
    background_image: null,
    status: 'active',
    system_prompt: 'Be Emma.',
  }
  const session = {
    session_id: '42',
    character_id: '3',
    title: '新会话',
    status: 'active',
    messages: [],
  }
  let created = false
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown = session
    if (url.endsWith('/characters')) result = [character]
    else if (url.endsWith('/characters/3')) result = character
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
    expect(window.location.search).toBe('?character=3&session=42'),
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
  fireEvent.click(screen.getByRole('button', { name: '返回角色选择' }))
  fireEvent.click(await screen.findByRole('button', { name: /进入窗边咖啡馆/ }))
  await waitFor(() =>
    expect(window.location.search).toBe('?character=3&session=42'),
  )
  expect(
    fetcher.mock.calls.filter(([, options]) => options?.method === 'POST'),
  ).toHaveLength(1)
})
