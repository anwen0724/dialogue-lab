import { useEffect, useState } from 'react'
import { SidePanel } from '../../shared/ui/SidePanel'
import {
  deleteCharacter,
  getCharacter,
  saveCharacter,
  uploadImage,
} from './api'
import type { Character, CharacterForm } from './api'
import { getSettings, getVoices } from '../settings/api'
import type { VoiceOption } from '../settings/api'

/** 用户编辑自己的角色；保存失败保留草稿，已创建的记录不会重复创建。 */
export function CharacterEditor({
  character,
  onClose,
  onSaved,
  onDeleted,
  onBack = onClose,
  backLabel = '返回角色列表',
}: {
  character?: Character
  onClose: () => void
  onSaved: (character: Character) => void
  onDeleted: (id: string) => void
  onBack?: () => void
  backLabel?: string
}) {
  const [form, setForm] = useState<CharacterForm>({
    name: character?.name ?? '',
    category: character?.category ?? '',
    character_name: character?.characterName ?? '',
    system_prompt: '',
    ...(character ? {} : { tts_voice: '' }),
  })
  const [savedId, setSavedId] = useState(character?.id)
  const [cover, setCover] = useState<File>()
  const [background, setBackground] = useState<File>()
  const [loading, setLoading] = useState(Boolean(character))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [voices, setVoices] = useState<VoiceOption[]>([])
  useEffect(() => {
    if (character) return
    const controller = new AbortController()
    getSettings(controller.signal)
      .then((settings) => getVoices(settings.tts, controller.signal))
      .then((choices) => {
        if (!controller.signal.aborted) setVoices(choices)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(String(err))
      })
    return () => controller.abort()
  }, [character])
  useEffect(() => {
    if (!character) return
    const controller = new AbortController()
    getCharacter(character.id, controller.signal)
      .then((detail) => {
        setForm({
          name: detail.name,
          category: detail.category,
          character_name: detail.characterName,
          system_prompt: detail.systemPrompt,
        })
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(String(err))
      })
    return () => controller.abort()
  }, [character])
  async function save(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      let result = await saveCharacter(form, savedId)
      setSavedId(result.id)
      if (cover) {
        result = await uploadImage(result.id, 'cover', cover)
        setCover(undefined)
      }
      if (background) {
        result = await uploadImage(result.id, 'background', background)
        setBackground(undefined)
      }
      onSaved(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '保存失败。')
    } finally {
      setBusy(false)
    }
  }
  async function remove() {
    if (!savedId) return
    setBusy(true)
    try {
      await deleteCharacter(savedId)
      onDeleted(savedId)
    } catch (err: unknown) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <SidePanel
      title={character ? '角色资料与身份' : '新建角色'}
      backLabel={backLabel}
      onBack={() => {
        if (!busy) onBack()
      }}
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <form className="panel-content character-form" onSubmit={save}>
        <label>
          角色名称
          <input
            required
            maxLength={200}
            value={form.name}
            disabled={loading || busy}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          分类
          <input
            required
            maxLength={60}
            value={form.category}
            disabled={loading || busy}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          />
        </label>
        <label>
          人物名字
          <input
            required
            maxLength={100}
            value={form.character_name}
            disabled={loading || busy}
            onChange={(e) =>
              setForm({ ...form, character_name: e.target.value })
            }
          />
        </label>
        <label>
          身份指令
          <textarea
            required
            maxLength={32000}
            value={form.system_prompt}
            disabled={loading || busy}
            onChange={(e) =>
              setForm({ ...form, system_prompt: e.target.value })
            }
          />
        </label>
        <label>
          封面图片
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(e) => setCover(e.target.files?.[0])}
          />
        </label>
        {!character && (
          <label>
            人物音色
            <select
              required
              value={form.tts_voice ?? ''}
              disabled={busy || !voices.length}
              onChange={(event) =>
                setForm({ ...form, tts_voice: event.target.value })
              }
            >
              <option value="" disabled>
                请选择音色
              </option>
              {voices.map((voice) => (
                <option key={voice.id} value={voice.id}>
                  {voice.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          背景图片
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(e) => setBackground(e.target.files?.[0])}
          />
        </label>
        <p className="field-note">JPG、PNG、WebP，每张最多 10 MB。</p>
        {error && (
          <p role="alert" className="error-note">
            {error}
          </p>
        )}
        <button
          className="primary-button"
          disabled={loading || busy || (!character && !form.tts_voice)}
        >
          {busy ? '正在保存…' : '保存角色'}
        </button>
        {savedId && (
          <>
            {deleting ? (
              <>
                <p>有会话的角色会归档并保留记录。没有会话的角色会删除。</p>
                <button
                  type="button"
                  className="danger-button"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  确认删除角色
                </button>
              </>
            ) : (
              <button
                type="button"
                className="danger-button"
                disabled={busy}
                onClick={() => setDeleting(true)}
              >
                删除角色
              </button>
            )}
          </>
        )}
      </form>
    </SidePanel>
  )
}
