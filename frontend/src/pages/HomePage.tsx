import { useEffect, useRef, useState } from 'react'
import {
  listCharacters,
  getCharacter,
  copyCharacter,
} from '../features/characters/api'
import type { Character } from '../features/characters/api'
import { CharacterCard } from '../features/characters/CharacterCard'
import { ApplicationSettingsPanel } from '../features/settings/ApplicationSettingsPanel'
import { CharacterEditor } from '../features/characters/CharacterEditor'
import { DialogueRoom } from '../features/dialogue/DialogueRoom'
import {
  createSession,
  getSession,
  listSessions,
} from '../features/sessions/api'
import type { Session } from '../features/sessions/api'
import { SidePanel } from '../shared/ui/SidePanel'
import { Icon } from '../shared/ui/Icon'
import '../styles/immersive.css'

function readLocation() {
  const params = new URLSearchParams(window.location.search)
  const id = (key: string) =>
    /^\d+$/.test(params.get(key) ?? '')
      ? (params.get(key) ?? undefined)
      : undefined
  return {
    characterId: id('character') ?? id('scene'),
    sessionId: id('session'),
  }
}

/** 页面拥有首页/沉浸页导航；角色与会话的接口操作保留在各自功能中。 */
export function HomePage() {
  const [location, setLocation] = useState(readLocation)
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(
    null,
  )
  const [resolvedSession, setResolvedSession] = useState<string>()
  const [recent, setRecent] = useState<Session[]>([])
  const [category, setCategory] = useState('')
  const [editing, setEditing] = useState<Character | 'new' | null>(null)
  const [history, setHistory] = useState(false)
  const [applicationSettings, setApplicationSettings] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const navigation = useRef(0)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  useEffect(() => {
    const pop = () => {
      navigation.current++
      setLocation(readLocation())
    }
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      listCharacters(controller.signal),
      listSessions(controller.signal),
    ])
      .then(([items, sessions]) => {
        setCharacters(items)
        setRecent(sessions)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(String(err))
          setLoading(false)
        }
      })
    return () => controller.abort()
  }, [location.sessionId])
  useEffect(() => {
    const controller = new AbortController()
    const sessionId = location.sessionId
    if (sessionId) {
      // 角色归属以会话记录为准，恢复旧链接时补齐 URL，不能用 URL 改变归属。
      getSession(sessionId, controller.signal)
        .then(async (detail) => {
          const character = detail.characterId
            ? await getCharacter(detail.characterId, controller.signal)
            : null
          if (controller.signal.aborted) return
          setSelectedCharacter(character)
          const params = new URLSearchParams()
          if (character) params.set('character', character.id)
          params.set('session', sessionId)
          window.history.replaceState(null, '', `?${params}`)
          setLocation({ characterId: character?.id, sessionId })
          setResolvedSession(sessionId)
        })
        .catch((err: unknown) => {
          if (!controller.signal.aborted) setError(String(err))
        })
    }
    return () => controller.abort()
  }, [location.sessionId])
  function navigate(characterId?: string, sessionId?: string) {
    navigation.current++
    const params = new URLSearchParams()
    if (characterId) params.set('character', characterId)
    if (sessionId) params.set('session', sessionId)
    window.history.pushState(null, '', params.size ? `?${params}` : '/')
    setLocation({ characterId, sessionId })
    setHistory(false)
    setError('')
  }
  async function enter(character: Character, fresh = false) {
    if (busy) return
    setBusy(true)
    setError('')
    const ticket = ++navigation.current
    try {
      const existing = fresh ? [] : await listSessions(undefined, character.id)
      const session =
        existing[0] ?? (await createSession('新会话', character.id))
      if (ticket !== navigation.current) return
      setSelectedCharacter(character)
      navigate(character.id, session.id)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '无法打开角色。')
    } finally {
      setBusy(false)
    }
  }
  async function openSession(session: Session) {
    if (busy) return
    const ticket = ++navigation.current
    setBusy(true)
    try {
      const detail = await getSession(session.id, new AbortController().signal)
      const character = detail.characterId
        ? await getCharacter(detail.characterId)
        : null
      if (ticket !== navigation.current) return
      setSelectedCharacter(character)
      navigate(detail.characterId ?? undefined, session.id)
    } catch (err: unknown) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  function saved(character: Character) {
    setCharacters((items) =>
      [...items.filter((item) => item.id !== character.id), character]
        .filter((item) => item.status === 'active')
        .sort((a, b) => (BigInt(a.id) < BigInt(b.id) ? -1 : 1)),
    )
    if (location.characterId === character.id) setSelectedCharacter(character)
    setEditing(null)
  }
  function deleted(id: string) {
    setCharacters((items) => items.filter((character) => character.id !== id))
    setEditing(null)
    if (location.characterId === id) navigate()
  }
  async function copy(character: Character) {
    if (busy) return
    const ticket = ++navigation.current
    setBusy(true)
    setError('')
    try {
      const copied = await copyCharacter(character.id)
      if (ticket !== navigation.current) return
      saved(copied)
      setCategory('')
      setEditing(copied)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '无法复制角色。')
    } finally {
      setBusy(false)
    }
  }
  const activeCharacter =
    selectedCharacter?.id === location.characterId ? selectedCharacter : null
  const filtered = characters.filter(
    (character) => !category || character.category === category,
  )
  return (
    <>
      {location.sessionId && resolvedSession !== location.sessionId ? (
        <main className="lobby">
          <button className="quiet-button" onClick={() => navigate()}>
            返回角色选择
          </button>
          <p role={error ? 'alert' : 'status'}>{error || '正在打开会话…'}</p>
        </main>
      ) : location.sessionId ? (
        <DialogueRoom
          key={location.sessionId}
          sessionId={location.sessionId}
          character={activeCharacter}
          onBack={() => navigate()}
          onSelect={(id) => navigate(location.characterId, id)}
          onNew={() => {
            if (activeCharacter) void enter(activeCharacter, true)
          }}
          onCharacterDeleted={deleted}
          onCharacterChanged={saved}
          initialDraft={drafts[location.sessionId] ?? ''}
          onDraftChange={(value) => {
            const id = location.sessionId
            if (id) setDrafts((previous) => ({ ...previous, [id]: value }))
          }}
        />
      ) : (
        <div className="home">
          <header className="home-header">
            <a className="brand" href="/">
              {' '}
              <span className="brand-mark">
                <i />
                <i />
                <i />
                <i />
              </span>
              Dialogue<span className="brand-light">Lab</span>
            </a>
            <div className="header-actions">
              <button
                className="quiet-button"
                onClick={() => setApplicationSettings(true)}
              >
                <Icon name="settings" />
                应用设置
              </button>
              <button className="quiet-button" onClick={() => setHistory(true)}>
                <Icon name="history" />
                最近练习
              </button>
              <button
                className="quiet-button"
                onClick={() => setEditing('new')}
              >
                <Icon name="plus" />
                新建角色
              </button>
            </div>
          </header>
          <main className="lobby">
            <section className="welcome">
              <div>
                <div className="eyebrow">给自己，一段对话的时间</div>
                <h1>
                  换个地方，
                  <br className="mobile-break" />
                  开始对话。
                </h1>
                <p>
                  练习表达，也享受交流。这里的每个空间，都为你留了一个位置。
                </p>
              </div>
              <div className="welcome-note">
                <span>
                  戴上耳机
                  <br />
                  <strong>让世界安静一点</strong>
                </span>
              </div>
            </section>
            <div className="section-bar">
              <div className="filters" role="group" aria-label="角色分类">
                {[
                  '',
                  ...new Set(characters.map((character) => character.category)),
                ].map((item) => (
                  <button
                    key={item}
                    className={`filter ${category === item ? 'active' : ''}`}
                    aria-pressed={category === item}
                    onClick={() => setCategory(item)}
                  >
                    {item || '全部角色'}
                  </button>
                ))}
              </div>
            </div>
            {loading && <p role="status">正在加载角色…</p>}
            <section className="character-grid" aria-label="选择对话角色">
              {filtered.map((character, index) => (
                <CharacterCard
                  key={character.id}
                  character={character}
                  index={index}
                  count={filtered.length}
                  disabled={busy}
                  onEnter={() => void enter(character)}
                  onEdit={() => setEditing(character)}
                  onCopy={() => void copy(character)}
                />
              ))}
            </section>
            {!loading && !filtered.length && (
              <p>暂无角色，点击“新建角色”开始。</p>
            )}
            {recent[0] && (
              <section className="return-section">
                <div className="return-heading">
                  <h2>接着上次的话题</h2>
                </div>
                <button
                  className="resume-card"
                  disabled={busy}
                  onClick={() => void openSession(recent[0])}
                >
                  <span className="resume-copy">
                    <strong>{recent[0].title}</strong>
                    <small>{recent[0].latestMessage}</small>
                  </span>
                  <span className="resume-action">
                    继续对话
                    <Icon name="arrow" />
                  </span>
                </button>
              </section>
            )}
            {error && (
              <p role="alert" className="error-note">
                {error}
              </p>
            )}
          </main>
        </div>
      )}
      {history && (
        <SidePanel title="最近练习" onClose={() => setHistory(false)}>
          <div className="panel-content session-list">
            {recent.map((session) => (
              <button
                key={session.id}
                className="session-item"
                disabled={busy}
                onClick={() => void openSession(session)}
              >
                <strong>{session.title}</strong>
                <p>{session.latestMessage}</p>
              </button>
            ))}
          </div>
        </SidePanel>
      )}
      {editing && (
        <CharacterEditor
          character={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={saved}
          onDeleted={deleted}
        />
      )}
      {applicationSettings && (
        <ApplicationSettingsPanel
          onClose={() => setApplicationSettings(false)}
        />
      )}
    </>
  )
}
