// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { HomePage } from '../src/pages/HomePage'
import { installBrowserAudio } from './browserAudio'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

test('创建会话后打开它，并在地址中保留可恢复的会话标识', async () => {
  installBrowserAudio()
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const session = {
      session_id: '42',
      title: 'Practice',
      status: 'active',
      messages: [],
    }
    return new Response(
      JSON.stringify(
        url.endsWith('/presets')
          ? ['general']
          : url.endsWith('/sessions') && options?.method !== 'POST'
            ? []
            : session,
      ),
      { status: 200 },
    )
  })
  vi.stubGlobal('fetch', fetcher)
  render(<HomePage />)
  fireEvent.change(screen.getByRole('textbox', { name: '会话名称' }), {
    target: { value: 'Practice' },
  })
  fireEvent.click(screen.getByRole('button', { name: '新建会话' }))
  await waitFor(() => expect(window.location.search).toBe('?session=42'))
  expect(await screen.findByRole('textbox', { name: '输入消息' })).toBeDefined()
  expect(
    fetcher.mock.calls.filter(([, options]) => options?.method === 'POST'),
  ).toHaveLength(1)
})
