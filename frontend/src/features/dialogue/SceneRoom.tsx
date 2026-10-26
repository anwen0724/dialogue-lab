import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Scene } from '../scenes/api'
import { listSessions } from '../sessions/api'
import type { Session } from '../sessions/api'
import { SidePanel } from '../../shared/ui/SidePanel'
import { Icon } from '../../shared/ui/Icon'
import { useDialogue } from './useDialogue'
import { MessageComposer } from './MessageComposer'
import { VoiceWave } from './VoiceWave'
import { RoomSettings } from './RoomSettings'
import { SceneEditor } from '../scenes/SceneEditor'
import { loadPreferences, savePreferences } from './preferences'

/** 沉浸页拥有画面布局和面板；一份连接状态驱动字幕、消息与输入。 */
export function SceneRoom({
  sessionId,
  scene,
  onBack,
  onSelect,
  onNew,
  onSceneDeleted,
  onSceneChanged,
  initialDraft,
  onDraftChange,
}: {
  sessionId: string
  scene: Scene | null
  onBack: () => void
  onSelect: (id: string) => void
  onNew: () => void
  onSceneDeleted: (id: string) => void
  onSceneChanged: (scene: Scene) => void
  initialDraft: string
  onDraftChange: (text: string) => void
}) {
  const { state, connection } = useDialogue(sessionId)
  const [panel, setPanel] = useState<
    'sessions' | 'messages' | 'settings' | 'scene' | null
  >(null)
  const [controls, setControls] = useState(false)
  const [text, setText] = useState(initialDraft)
  const latestDraft = useRef(initialDraft)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [sessions, setSessions] = useState<Session[]>([])
  const [preferences, setPreferences] = useState(loadPreferences)
  const { shade, subtitles, allowInterrupt, volume } = preferences
  const openingStarted = useRef(false)
  const blocked = state.busy && !state.allowInterrupt
  useEffect(() => savePreferences(preferences), [preferences])
  useEffect(() => {
    connection.setVolume(volume / 100)
  }, [connection, volume, state.canControl])
  useEffect(() => {
    if (state.canControl) connection.setInteraction(allowInterrupt)
  }, [connection, state.canControl, allowInterrupt])
  useEffect(() => {
    if (!state.canControl || !scene || openingStarted.current) return
    openingStarted.current = true
    if (state.messages.length === 0)
      void connection
        .startSession()
        .catch((err: unknown) => setError(String(err)))
  }, [connection, state.canControl, state.messages.length, scene])
  const [preset, setPreset] = useState('general')
  const scroll = useRef<HTMLDivElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const messages = state.messages.filter(
    (message) => message.source !== 'opening',
  )
  const latest = messages.at(-1)
  const latestText = state.draft?.text || state.partial || latest?.text || ''
  const latestAuthor = state.draft?.text
    ? (scene?.characterName ?? 'AI')
    : state.partial
      ? '你'
      : latest?.role === 'user'
        ? '你'
        : (scene?.characterName ?? 'AI')
  useEffect(() => {
    if (panel !== 'sessions') return
    const controller = new AbortController()
    listSessions(controller.signal, scene?.id)
      .then(setSessions)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setError(String(err))
      })
    return () => controller.abort()
  }, [panel, scene?.id, state.messages.length])
  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
  }, [panel, state.messages, state.draft])
  function draft(value: string) {
    latestDraft.current = value
    setText(value)
    onDraftChange(value)
  }
  async function send() {
    if (sending || blocked || !text.trim()) return
    setSending(true)
    setError('')
    try {
      await connection.submit(text, preset)
      // 回执到达前用户可能已输入下一句，只清除本次确认保存的草稿。
      if (latestDraft.current === text) {
        draft('')
        setControls(false)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '发送失败。')
    } finally {
      setSending(false)
    }
  }
  function openPanel(next: typeof panel) {
    setControls(false)
    setPanel(next)
  }
  const style = { '--shade': shade / 100 } as CSSProperties
  return (
    <main
      className={`room ${controls ? 'controls-visible typing' : ''}`}
      style={style}
      aria-label="沉浸式对话"
      onPointerDown={(event) => {
        if (
          !bottom.current?.contains(event.target as Node) &&
          !(
            event.target instanceof Element &&
            event.target.closest('.reveal-controls')
          )
        )
          setControls(false)
      }}
    >
      {scene?.background && (
        <img
          className="room-background"
          src={scene.background}
          alt="当前对话背景"
        />
      )}
      <div className="room-shade" />
      <header className="room-header">
        <div className="room-title-group">
          <button
            className="round-button"
            aria-label="返回场景选择"
            onClick={onBack}
          >
            <Icon name="back" />
          </button>
          <div>
            <span className="room-eyebrow">YOUR LITTLE SPACE</span>
            <h1>{scene?.name ?? '会话'}</h1>
          </div>
        </div>
        <div className="room-actions">
          <button
            className="glass-button"
            aria-label="打开会话列表"
            onClick={() => openPanel('sessions')}
          >
            <Icon name="history" />
            <span>会话</span>
          </button>
          <button
            className="glass-button"
            aria-label="打开当前会话消息"
            onClick={() => openPanel('messages')}
          >
            <Icon name="history" />
            <span>消息</span>
          </button>
          <button
            className="round-button"
            aria-label="打开设置"
            onClick={() => openPanel('settings')}
          >
            <Icon name="settings" />
          </button>
        </div>
      </header>
      {scene && (
        <div className="partner-label">
          <span className="partner-dot" />
          <strong>{scene.characterName}</strong>
        </div>
      )}
      <section className="subtitle-area" aria-live="polite" aria-atomic="true">
        <VoiceWave readAmplitude={connection.getAmplitude} />
        {subtitles && (
          <>
            <span className="latest-author">
              {latestText ? latestAuthor : ''}
            </span>
            <p className="subtitle latest-message-text">{latestText}</p>
          </>
        )}
      </section>
      {!controls && (
        <button
          className="reveal-controls"
          aria-label="展开底部操作和文字输入"
          onPointerEnter={(event) => {
            if (event.pointerType === 'mouse') setControls(true)
          }}
          onClick={() => setControls(true)}
          onFocus={() => setControls(true)}
        />
      )}
      <div
        className="room-bottom"
        ref={bottom}
        inert={!controls}
        onPointerLeave={() => {
          if (!text && !bottom.current?.contains(document.activeElement))
            setControls(false)
        }}
      >
        <MessageComposer
          text={text}
          onChange={draft}
          onSend={() => void send()}
          disabled={!state.canControl || sending || blocked}
        />
        <div className="control-dock">
          <button
            className="dock-side"
            onClick={() => bottom.current?.querySelector('textarea')?.focus()}
          >
            <Icon name="keyboard" />
            打字
          </button>
          <button
            className={`microphone-button ${state.recording === 'recording' ? 'listening' : ''}`}
            disabled={!state.canControl}
            onClick={() =>
              void (state.recordingWanted
                ? connection.stopRecording()
                : connection.startRecording(preset))
            }
          >
            <Icon name="mic" />
            {state.recordingWanted ? '停止说话' : '开始说话'}
          </button>
          <button
            className="dock-side"
            disabled={!state.canControl || !state.busy}
            onClick={() => connection.stopReply()}
          >
            <Icon name="pause" />
            停止回复
          </button>
        </div>
        <p className="dock-hint">
          {state.recordingWanted && blocked
            ? '回复结束后继续收音'
            : state.recording === 'preparing'
              ? '正在连接麦克风…'
              : 'Enter 发送 · Shift + Enter 换行'}
        </p>
      </div>
      {(error || state.error) && (
        <p role="alert" className="error-note">
          {error || state.error}
        </p>
      )}
      {state.status === 'connected' && !state.canControl && (
        <p className="error-note">此会话正在另一个窗口使用，本窗口只读。</p>
      )}
      {panel === 'sessions' && (
        <SidePanel title="这里的每次对话" onClose={() => setPanel(null)}>
          <div className="panel-content">
            <div className="history-intro">
              <span>{scene?.name ?? '全部会话'}</span>
              <small>{sessions.length} 个会话</small>
            </div>
            {scene?.status === 'active' && (
              <button className="new-session-button" onClick={onNew}>
                <Icon name="plus" />
                新建会话
              </button>
            )}
            <p className="list-caption">已有会话</p>
            <div className="session-list">
              {sessions.map((session) => (
                <button
                  className={`session-item ${session.id === sessionId ? 'selected' : ''}`}
                  key={session.id}
                  aria-current={session.id === sessionId}
                  onClick={() => {
                    setPanel(null)
                    onSelect(session.id)
                  }}
                >
                  <strong>{session.title}</strong>
                  <p>{session.latestMessage}</p>
                  <small>{session.messageCount} 条消息</small>
                </button>
              ))}
            </div>
          </div>
        </SidePanel>
      )}
      {panel === 'messages' && (
        <SidePanel
          title="当前会话"
          className="messages-panel"
          onClose={() => setPanel(null)}
        >
          <div className="messages-scroll" ref={scroll}>
            <div className="message-list">
              {messages.map((message) => (
                <article
                  key={message.id}
                  className={`chat-message ${message.role}`}
                >
                  <small>
                    {message.role === 'user'
                      ? '你'
                      : (scene?.characterName ?? 'AI')}
                  </small>
                  <p>{message.text}</p>
                  {message.status !== 'completed' && (
                    <small>
                      {message.status === 'cancelled' ? '已停止' : '生成失败'}
                    </small>
                  )}
                </article>
              ))}
              {state.draft && (
                <article className="chat-message assistant">
                  <small>{scene?.characterName ?? 'AI'}</small>
                  <p>{state.draft.text || '…'}</p>
                </article>
              )}
            </div>
          </div>
          <MessageComposer
            panel
            text={text}
            onChange={draft}
            onSend={() => void send()}
            disabled={!state.canControl || sending || blocked}
            busy={state.busy}
            onStop={() => connection.stopReply()}
          />
        </SidePanel>
      )}
      {panel === 'settings' && (
        <SidePanel title="你的对话空间" onClose={() => setPanel(null)}>
          <RoomSettings
            scene={scene}
            preferences={preferences}
            onPreferencesChange={setPreferences}
            onSceneChanged={onSceneChanged}
            onEdit={() => setPanel('scene')}
          >
            {!scene && (
              <label>
                系统指令
                <select
                  className="legacy-preset"
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                >
                  {state.presets.map((name) => (
                    <option key={name}>{name}</option>
                  ))}
                </select>
              </label>
            )}
          </RoomSettings>
        </SidePanel>
      )}
      {panel === 'scene' && scene && (
        <SceneEditor
          scene={scene}
          backLabel="返回设置"
          onBack={() => setPanel('settings')}
          onClose={() => setPanel(null)}
          onSaved={(updated) => {
            onSceneChanged(updated)
            setPanel('settings')
          }}
          onDeleted={onSceneDeleted}
        />
      )}
    </main>
  )
}
