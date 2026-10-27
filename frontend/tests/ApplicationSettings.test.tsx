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
import { ApplicationSettingsPanel } from '../src/features/settings/ApplicationSettingsPanel'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('首页切换对话模型后明确回到模型默认，保存实际选择', async () => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
  const initial = {
    dialogue: {
      provider_id: 'deepseek',
      model_id: 'deepseek-flash',
      reasoning: 'high',
    },
    stt: { provider_id: 'bailian', model_id: 'asr' },
    tts: { provider_id: 'bailian', model_id: 'tts' },
  }
  let saved: unknown
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      let result: unknown = []
      if (url.endsWith('/settings')) {
        result = initial
        if (options?.method === 'PATCH') {
          saved = JSON.parse(String(options.body))
          result = saved
        }
      } else if (url.endsWith('/models'))
        result = [
          {
            provider_id: 'deepseek',
            model_id: 'deepseek-flash',
            name: 'Flash',
            reasoning_levels: ['high'],
            available: true,
          },
          {
            provider_id: 'deepseek',
            model_id: 'deepseek-v4-pro',
            name: 'Pro',
            reasoning_levels: ['low', 'high'],
            available: true,
          },
        ]
      else if (url.endsWith('/speech-models'))
        result = [
          {
            provider_id: 'bailian',
            model_id: 'asr',
            name: 'ASR',
            kind: 'stt',
            available: true,
          },
          {
            provider_id: 'bailian',
            model_id: 'tts',
            name: 'TTS',
            kind: 'tts',
            available: true,
          },
        ]
      return new Response(JSON.stringify(result))
    }),
  )
  render(<HomePage />)
  fireEvent.click(await screen.findByRole('button', { name: '应用设置' }))
  await screen.findByLabelText('推理强度')
  fireEvent.change(screen.getByLabelText('对话模型'), {
    target: { value: 'deepseek-v4-pro' },
  })
  expect((screen.getByLabelText('推理强度') as HTMLSelectElement).value).toBe(
    '',
  )
  await waitFor(() =>
    expect(
      (screen.getByRole('button', { name: '保存设置' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false),
  )
  fireEvent.click(screen.getByRole('button', { name: '保存设置' }))
  await waitFor(() =>
    expect(saved).toEqual({
      ...initial,
      dialogue: {
        provider_id: 'deepseek',
        model_id: 'deepseek-v4-pro',
        reasoning: null,
      },
    }),
  )
})

test('更换合成模型时在保存前列出需要重选声音的场景', async () => {
  const settings = {
    dialogue: { provider_id: 'deepseek', model_id: 'flash', reasoning: null },
    stt: { provider_id: 'bailian', model_id: 'asr' },
    tts: { provider_id: 'bailian', model_id: 'tts-a' },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      let result: unknown = []
      if (url.endsWith('/settings')) result = settings
      else if (url.endsWith('/models'))
        result = [
          {
            provider_id: 'deepseek',
            model_id: 'flash',
            name: 'Flash',
            reasoning_levels: [],
            available: true,
          },
        ]
      else if (url.endsWith('/speech-models'))
        result = [
          {
            provider_id: 'bailian',
            model_id: 'asr',
            name: 'ASR',
            kind: 'stt',
            available: true,
          },
          {
            provider_id: 'bailian',
            model_id: 'tts-a',
            name: 'A',
            kind: 'tts',
            available: true,
          },
          {
            provider_id: 'bailian',
            model_id: 'tts-b',
            name: 'B',
            kind: 'tts',
            available: true,
          },
        ]
      else if (
        url.endsWith('/settings/preview') &&
        String(options?.body).includes('tts-b')
      )
        result = [{ scene_id: '8', name: '窗边咖啡馆', tts_voice: 'old-voice' }]
      return new Response(JSON.stringify(result))
    }),
  )
  render(<ApplicationSettingsPanel onClose={() => {}} />)
  fireEvent.change(await screen.findByLabelText('语音合成模型'), {
    target: { value: 'tts-b' },
  })
  await screen.findByText('窗边咖啡馆')
  expect(screen.getByText(/保留原音色/)).toBeDefined()
})
