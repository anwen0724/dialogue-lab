import { useState } from 'react'
import type { Session } from './api'

type Props = {
  sessions: Session[]
  selected?: string
  loading: boolean
  error?: string
  onSelect: (id: string) => void
  onCreate: (title: string) => Promise<void>
}

/** 列表负责选择和创建，页面决定侧栏尺寸与滚动位置。 */
export function SessionList({
  sessions,
  selected,
  loading,
  error,
  onSelect,
  onCreate,
}: Props) {
  const [title, setTitle] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string>()
  async function create(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setSaveError(undefined)
    try {
      await onCreate(title.trim() || '新会话')
      setTitle('')
    } catch (error: unknown) {
      setSaveError(error instanceof Error ? error.message : '创建失败。')
    } finally {
      setSaving(false)
    }
  }
  return (
    <>
      <h2>会话</h2>
      <form className="session-create" onSubmit={create}>
        <label htmlFor="session-title">会话名称</label>
        <input
          id="session-title"
          value={title}
          maxLength={200}
          placeholder="例如：英语日常交流"
          onChange={(event) => setTitle(event.target.value)}
          disabled={saving}
        />
        <button type="submit" disabled={saving}>
          {saving ? '正在创建…' : '新建会话'}
        </button>
      </form>
      {(saveError || error) && <p role="alert">{saveError || error}</p>}
      {loading && <p>正在读取会话…</p>}
      <nav aria-label="会话列表">
        {sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            aria-current={selected === session.id ? 'page' : undefined}
            onClick={() => onSelect(session.id)}
          >
            {session.title}
          </button>
        ))}
      </nav>
    </>
  )
}
