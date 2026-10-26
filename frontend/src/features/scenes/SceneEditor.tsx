import { useEffect, useState } from 'react'
import { SidePanel } from '../../shared/ui/SidePanel'
import { deleteScene, getScene, saveScene, uploadImage } from './api'
import type { Scene, SceneForm } from './api'

/** 用户编辑自己的场景；保存失败保留草稿，已创建的记录不会重复创建。 */
export function SceneEditor({
  scene,
  onClose,
  onSaved,
  onDeleted,
  onBack = onClose,
  backLabel = '返回场景列表',
}: {
  scene?: Scene
  onClose: () => void
  onSaved: (scene: Scene) => void
  onDeleted: (id: string) => void
  onBack?: () => void
  backLabel?: string
}) {
  const [form, setForm] = useState<SceneForm>({
    name: scene?.name ?? '',
    category: scene?.category ?? '',
    character_name: scene?.characterName ?? '',
    system_prompt: '',
  })
  const [savedId, setSavedId] = useState(scene?.id)
  const [cover, setCover] = useState<File>()
  const [background, setBackground] = useState<File>()
  const [loading, setLoading] = useState(Boolean(scene))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  useEffect(() => {
    if (!scene) return
    const controller = new AbortController()
    getScene(scene.id, controller.signal)
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
  }, [scene])
  async function save(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      let result = await saveScene(form, savedId)
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
      await deleteScene(savedId)
      onDeleted(savedId)
    } catch (err: unknown) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <SidePanel
      title={scene ? '场景资料与身份' : '新建场景'}
      backLabel={backLabel}
      onBack={() => {
        if (!busy) onBack()
      }}
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <form className="panel-content scene-form" onSubmit={save}>
        <label>
          场景名称
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
        <button className="primary-button" disabled={loading || busy}>
          {busy ? '正在保存…' : '保存场景'}
        </button>
        {savedId && (
          <>
            {deleting ? (
              <>
                <p>有会话的场景会归档并保留记录。没有会话的场景会删除。</p>
                <button
                  type="button"
                  className="danger-button"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  确认删除场景
                </button>
              </>
            ) : (
              <button
                type="button"
                className="danger-button"
                disabled={busy}
                onClick={() => setDeleting(true)}
              >
                删除场景
              </button>
            )}
          </>
        )}
      </form>
    </SidePanel>
  )
}
