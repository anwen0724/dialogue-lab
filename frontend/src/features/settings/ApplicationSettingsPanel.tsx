import { useEffect, useState } from 'react'
import { SidePanel } from '../../shared/ui/SidePanel'
import { getModels, getSettings, saveSettings, previewSettings } from './api'
import type {
  ApplicationSettings,
  ModelOption,
  ModelSelection,
  AffectedCharacter,
} from './api'

/** 首页的全局模型选择；编辑草稿不会改变正在使用的设置。 */
export function ApplicationSettingsPanel({ onClose }: { onClose: () => void }) {
  const [draft, setDraft] = useState<ApplicationSettings | null>(null)
  const [models, setModels] = useState<ModelOption[]>([])
  const [speech, setSpeech] = useState<ModelOption[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [preview, setPreview] = useState<{
    settings: ApplicationSettings
    affected: AffectedCharacter[]
  } | null>(null)
  useEffect(() => {
    if (!draft) return
    const controller = new AbortController()
    previewSettings(draft, controller.signal)
      .then((affected) => {
        if (!controller.signal.aborted)
          setPreview({ settings: draft, affected })
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : '音色检查失败。')
      })
    return () => controller.abort()
  }, [draft])
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      getSettings(controller.signal),
      getModels(false, controller.signal),
      getModels(true, controller.signal),
    ])
      .then(([settings, dialogue, voices]) => {
        if (controller.signal.aborted) return
        setDraft(settings)
        setModels(dialogue)
        setSpeech(voices)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : '读取设置失败。')
      })
    return () => controller.abort()
  }, [])
  async function save(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft || busy || preview?.settings !== draft) return
    setBusy(true)
    setError('')
    setSaved(false)
    try {
      setDraft(await saveSettings(draft))
      setSaved(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存失败。')
    } finally {
      setBusy(false)
    }
  }
  function choose(kind: 'dialogue' | 'stt' | 'tts', selection: ModelSelection) {
    if (!draft) return
    setSaved(false)
    setDraft({
      ...draft,
      [kind]:
        kind === 'dialogue' ? { ...selection, reasoning: null } : selection,
    })
  }
  const dialogue = models.find(
    (model) =>
      model.provider_id === draft?.dialogue.provider_id &&
      model.model_id === draft.dialogue.model_id,
  )
  return (
    <SidePanel
      title="应用设置"
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <form
        className="panel-content character-form model-settings"
        onSubmit={save}
      >
        {!draft && !error && <p role="status">正在读取设置…</p>}
        {draft && (
          <>
            <section className="setting-section">
              <h3>对话模型</h3>
              <ModelPicker
                label="对话"
                models={models}
                value={draft.dialogue}
                disabled={busy}
                onChange={(value) => choose('dialogue', value)}
              />
              <label>
                推理强度
                <select
                  value={draft.dialogue.reasoning ?? ''}
                  disabled={busy}
                  onChange={(event) => {
                    setSaved(false)
                    setDraft({
                      ...draft,
                      dialogue: {
                        ...draft.dialogue,
                        reasoning: event.target.value || null,
                      },
                    })
                  }}
                >
                  <option value="">模型默认</option>
                  {dialogue?.reasoning_levels.map((level) => (
                    <option key={level} value={level}>
                      {level === 'off' ? '关闭思考' : level}
                    </option>
                  ))}
                </select>
              </label>
            </section>
            <section className="setting-section">
              <h3>语音识别</h3>
              <ModelPicker
                label="语音识别"
                models={speech.filter((model) => model.kind === 'stt')}
                value={draft.stt}
                disabled={busy}
                onChange={(value) => choose('stt', value)}
              />
            </section>
            <section className="setting-section">
              <h3>语音合成</h3>
              <ModelPicker
                label="语音合成"
                models={speech.filter((model) => model.kind === 'tts')}
                value={draft.tts}
                disabled={busy}
                onChange={(value) => choose('tts', value)}
              />
              {preview?.settings === draft && preview.affected.length > 0 && (
                <div role="status">
                  <p>
                    以下角色需要重新选择音色。保存后保留原音色，暂停语音播放，文字交流仍可继续。
                  </p>
                  <ul>
                    {preview.affected.map((character) => (
                      <li key={character.id}>{character.name}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
            <button
              className="primary-button"
              disabled={busy || preview?.settings !== draft}
            >
              {busy ? '正在保存…' : '保存设置'}
            </button>
            {saved && <p role="status">已保存。下一次回复或开始录音时生效。</p>}
          </>
        )}
        {error && (
          <p role="alert" className="error-note">
            {error}
          </p>
        )}
      </form>
    </SidePanel>
  )
}

function ModelPicker({
  label,
  models,
  value,
  disabled,
  onChange,
}: {
  label: string
  models: ModelOption[]
  value: ModelSelection
  disabled: boolean
  onChange: (selection: ModelSelection) => void
}) {
  const providers = [...new Set(models.map((model) => model.provider_id))]
  return (
    <>
      <label>
        {label}供应商
        <select
          value={value.provider_id}
          disabled={disabled}
          onChange={(event) => {
            const first = models.find(
              (model) =>
                model.provider_id === event.target.value && model.available,
            )
            if (first)
              onChange({
                provider_id: first.provider_id,
                model_id: first.model_id,
              })
          }}
        >
          {providers.map((provider) => {
            const available = models.some(
              (model) => model.provider_id === provider && model.available,
            )
            return (
              <option key={provider} value={provider} disabled={!available}>
                {provider}
                {available ? '' : '（未配置密钥）'}
              </option>
            )
          })}
        </select>
      </label>
      <label>
        {label}模型
        <select
          value={value.model_id}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...value, model_id: event.target.value })
          }
        >
          {models
            .filter((model) => model.provider_id === value.provider_id)
            .map((model) => (
              <option
                key={model.model_id}
                value={model.model_id}
                disabled={!model.available}
              >
                {model.name}
              </option>
            ))}
        </select>
      </label>
    </>
  )
}
