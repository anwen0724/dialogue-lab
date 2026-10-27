// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { RoomSettings } from '../src/features/dialogue/RoomSettings'
import { loadPreferences } from '../src/features/dialogue/preferences'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('场景音色失配时明确提示，选取兼容音色后保存到当前场景', async () => {
  let saved: unknown
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options?: RequestInit) => {
      let result: unknown
      if (url.endsWith('/settings'))
        result = {
          dialogue: {
            provider_id: 'deepseek',
            model_id: 'deepseek-flash',
            reasoning: null,
          },
          stt: { provider_id: 'bailian', model_id: 'asr' },
          tts: { provider_id: 'bailian', model_id: 'tts' },
        }
      else if (url.includes('/voices?'))
        result = [{ id: 'Emily_v3.1', name: 'Emily' }]
      else {
        saved = JSON.parse(String(options?.body))
        result = {
          scene_id: '8',
          name: '练习',
          category: '英语',
          character_name: 'Emma',
          cover_image: null,
          background_image: null,
          status: 'active',
          tts_voice: 'Emily_v3.1',
          voice_available: true,
        }
      }
      return new Response(JSON.stringify(result))
    }),
  )
  const updated = vi.fn()
  render(
    <RoomSettings
      scene={{
        id: '8',
        name: '练习',
        category: '英语',
        characterName: 'Emma',
        cover: null,
        background: null,
        status: 'active',
        ttsVoice: 'old-voice',
        voiceAvailable: false,
      }}
      preferences={loadPreferences()}
      onPreferencesChange={() => {}}
      onSceneChanged={updated}
      onEdit={() => {}}
    />,
  )
  await screen.findByText(/需要重新选择音色/)
  fireEvent.change(screen.getByLabelText('人物音色'), {
    target: { value: 'Emily_v3.1' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存声音' }))
  await waitFor(() =>
    expect(updated).toHaveBeenCalledWith(
      expect.objectContaining({ ttsVoice: 'Emily_v3.1' }),
    ),
  )
  expect(saved).toEqual({ tts_voice: 'Emily_v3.1' })
})
