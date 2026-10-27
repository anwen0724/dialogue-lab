import { useEffect, useState } from 'react'
import { getSettings, getVoices } from '../settings/api'
import type { ModelSelection, VoiceOption } from '../settings/api'
import { saveCharacterVoice } from './api'
import type { Character } from './api'

/** 角色仅选择音色，合成模型来自应用设置。 */
export function VoiceSettings({
  character,
  onSaved,
}: {
  character: Character
  onSaved: (character: Character) => void
}) {
  const [model, setModel] = useState<ModelSelection | null>(null)
  const [voices, setVoices] = useState<VoiceOption[]>([])
  const [selected, setSelected] = useState(character.ttsVoice ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    getSettings(controller.signal)
      .then(async (settings) => {
        const choices = await getVoices(settings.tts, controller.signal)
        if (controller.signal.aborted) return
        setModel(settings.tts)
        setVoices(choices)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : '音色读取失败。')
      })
    return () => controller.abort()
  }, [])
  async function save() {
    setBusy(true)
    setError('')
    try {
      onSaved(await saveCharacterVoice(character.id, selected))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存声音失败。')
    } finally {
      setBusy(false)
    }
  }
  const compatible = voices.some((voice) => voice.id === character.ttsVoice)
  return (
    <section className="setting-section character-form">
      <h3>人物声音</h3>
      {model && (
        <p className="model-name">
          {model.provider_id} / {model.model_id}
        </p>
      )}
      {model && !compatible && (
        <p role="alert" className="error-note">
          需要重新选择音色。语音播放已暂停，文字交流仍可继续。
        </p>
      )}
      <label>
        人物音色
        <select
          value={selected}
          disabled={!model || busy}
          onChange={(event) => setSelected(event.target.value)}
        >
          {!voices.some((voice) => voice.id === selected) && (
            <option value={selected} disabled>
              {selected ? `${selected}（不可用）` : '请选择音色'}
            </option>
          )}
          {voices.map((voice) => (
            <option key={voice.id} value={voice.id}>
              {voice.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="primary-button"
        disabled={
          busy ||
          !voices.some((voice) => voice.id === selected) ||
          selected === character.ttsVoice
        }
        onClick={() => void save()}
      >
        {busy ? '正在保存…' : '保存声音'}
      </button>
      {error && (
        <p role="alert" className="error-note">
          {error}
        </p>
      )}
    </section>
  )
}
