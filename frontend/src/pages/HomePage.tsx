import { useEffect, useRef, useState } from 'react'
import { listScenes, getScene } from '../features/scenes/api'
import type { Scene } from '../features/scenes/api'
import { SceneCard } from '../features/scenes/SceneCard'
import { SceneEditor } from '../features/scenes/SceneEditor'
import { SceneRoom } from '../features/dialogue/SceneRoom'
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
  return { sceneId: id('scene'), sessionId: id('session') }
}

/** 页面拥有首页/沉浸页导航；场景与会话的接口操作保留在各自功能中。 */
export function HomePage() {
  const [location, setLocation] = useState(readLocation)
  const [scenes, setScenes] = useState<Scene[]>([])
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [resolvedSession, setResolvedSession] = useState<string>()
  const [recent, setRecent] = useState<Session[]>([])
  const [category, setCategory] = useState('')
  const [editing, setEditing] = useState<Scene | 'new' | null>(null)
  const [history, setHistory] = useState(false)
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
      listScenes(controller.signal),
      listSessions(controller.signal),
    ])
      .then(([items, sessions]) => {
        setScenes(items)
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
      // 场景归属以会话记录为准，恢复旧链接时补齐 URL，不能用 URL 改变归属。
      getSession(sessionId, controller.signal)
        .then(async (detail) => {
          const scene = detail.sceneId
            ? await getScene(detail.sceneId, controller.signal)
            : null
          if (controller.signal.aborted) return
          setSelectedScene(scene)
          const params = new URLSearchParams()
          if (scene) params.set('scene', scene.id)
          params.set('session', sessionId)
          window.history.replaceState(null, '', `?${params}`)
          setLocation({ sceneId: scene?.id, sessionId })
          setResolvedSession(sessionId)
        })
        .catch((err: unknown) => {
          if (!controller.signal.aborted) setError(String(err))
        })
    }
    return () => controller.abort()
  }, [location.sessionId])
  function navigate(sceneId?: string, sessionId?: string) {
    navigation.current++
    const params = new URLSearchParams()
    if (sceneId) params.set('scene', sceneId)
    if (sessionId) params.set('session', sessionId)
    window.history.pushState(null, '', params.size ? `?${params}` : '/')
    setLocation({ sceneId, sessionId })
    setHistory(false)
    setError('')
  }
  async function enter(scene: Scene, fresh = false) {
    if (busy) return
    setBusy(true)
    setError('')
    const ticket = ++navigation.current
    try {
      const existing = fresh ? [] : await listSessions(undefined, scene.id)
      const session = existing[0] ?? (await createSession('新会话', scene.id))
      if (ticket !== navigation.current) return
      setSelectedScene(scene)
      navigate(scene.id, session.id)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '无法打开场景。')
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
      const scene = detail.sceneId ? await getScene(detail.sceneId) : null
      if (ticket !== navigation.current) return
      setSelectedScene(scene)
      navigate(detail.sceneId ?? undefined, session.id)
    } catch (err: unknown) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }
  function saved(scene: Scene) {
    setScenes((items) =>
      [...items.filter((item) => item.id !== scene.id), scene]
        .filter((item) => item.status === 'active')
        .sort((a, b) => (BigInt(a.id) < BigInt(b.id) ? -1 : 1)),
    )
    if (location.sceneId === scene.id) setSelectedScene(scene)
    setEditing(null)
  }
  function deleted(id: string) {
    setScenes((items) => items.filter((scene) => scene.id !== id))
    setEditing(null)
    if (location.sceneId === id) navigate()
  }
  const activeScene =
    selectedScene?.id === location.sceneId ? selectedScene : null
  const filtered = scenes.filter(
    (scene) => !category || scene.category === category,
  )
  return (
    <>
      {location.sessionId && resolvedSession !== location.sessionId ? (
        <main className="lobby">
          <button className="quiet-button" onClick={() => navigate()}>
            返回场景选择
          </button>
          <p role={error ? 'alert' : 'status'}>{error || '正在打开会话…'}</p>
        </main>
      ) : location.sessionId ? (
        <SceneRoom
          key={location.sessionId}
          sessionId={location.sessionId}
          scene={activeScene}
          onBack={() => navigate()}
          onSelect={(id) => navigate(location.sceneId, id)}
          onNew={() => {
            if (activeScene) void enter(activeScene, true)
          }}
          onSceneDeleted={deleted}
          onSceneChanged={saved}
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
              <button className="quiet-button" onClick={() => setHistory(true)}>
                <Icon name="history" />
                最近练习
              </button>
              <button
                className="quiet-button"
                onClick={() => setEditing('new')}
              >
                <Icon name="plus" />
                新建场景
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
              <div className="filters" role="group" aria-label="场景分类">
                {['', ...new Set(scenes.map((scene) => scene.category))].map(
                  (item) => (
                    <button
                      key={item}
                      className={`filter ${category === item ? 'active' : ''}`}
                      aria-pressed={category === item}
                      onClick={() => setCategory(item)}
                    >
                      {item || '全部场景'}
                    </button>
                  ),
                )}
              </div>
            </div>
            {loading && <p role="status">正在加载场景…</p>}
            <section className="scene-grid" aria-label="选择对话场景">
              {filtered.map((scene, index) => (
                <SceneCard
                  key={scene.id}
                  scene={scene}
                  index={index}
                  count={filtered.length}
                  disabled={busy}
                  onEnter={() => void enter(scene)}
                  onEdit={() => setEditing(scene)}
                />
              ))}
            </section>
            {!loading && !filtered.length && (
              <p>暂无场景，点击“新建场景”开始。</p>
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
        <SceneEditor
          scene={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={saved}
          onDeleted={deleted}
        />
      )}
    </>
  )
}
