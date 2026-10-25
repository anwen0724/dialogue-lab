import { useDialogue } from './useDialogue'
import { useEffect, useRef, useState } from 'react'

/** 会话区域负责展示与操作；连接和音频由对应控制对象管理。 */
export function Dialogue({ sessionId }: { sessionId: string }) {
  const { state, connection } = useDialogue(sessionId)
  const [text, setText] = useState('')
  const [preset, setPreset] = useState('general')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string>()
  const messagesElement = useRef<HTMLOListElement>(null)
  const following = useRef(true)
  useEffect(() => {
    if (following.current && messagesElement.current) {
      messagesElement.current.scrollTop = messagesElement.current.scrollHeight
    }
  }, [state.messages, state.draft])
  const selectedPreset = state.presets.includes(preset)
    ? preset
    : (state.presets[0] ?? '')
  async function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!text.trim()) return
    setSending(true)
    setError(undefined)
    try {
      await connection.submit(text, selectedPreset)
      setText('')
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : '发送失败。')
    } finally {
      setSending(false)
    }
  }
  return (
    <section className="dialogue" aria-label="会话内容">
      <ol
        aria-label="会话消息"
        ref={messagesElement}
        onScroll={(event) => {
          const list = event.currentTarget
          following.current =
            list.scrollHeight - list.scrollTop - list.clientHeight < 80
        }}
      >
        {state.messages.map((message) => (
          <li key={message.id} className={`message--${message.role}`}>
            <span>{message.role === 'user' ? '你' : 'AI'}</span>
            <p>{message.text}</p>
            {message.status !== 'completed' && (
              <small>
                {message.status === 'cancelled' ? '已停止生成' : '生成失败'}
              </small>
            )}
          </li>
        ))}
        {state.draft && (
          <li className="message--assistant">
            <span>AI · 正在回复</span>
            <p>{state.draft.text || '…'}</p>
          </li>
        )}
      </ol>
      <div className="dialogue-controls">
        <label>
          系统指令
          <select
            value={selectedPreset}
            disabled={state.recording !== 'idle'}
            onChange={(event) => setPreset(event.target.value)}
          >
            {state.presets.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <div className="voice-controls">
          {state.recording === 'idle' ? (
            <button
              type="button"
              disabled={!state.canControl || !selectedPreset}
              onClick={() => void connection.startRecording(selectedPreset)}
            >
              开始说话
            </button>
          ) : (
            <button
              type="button"
              disabled={state.recording === 'finishing'}
              onClick={() => void connection.stopRecording()}
            >
              {state.recording === 'preparing'
                ? '取消准备'
                : state.recording === 'finishing'
                  ? '正在收尾…'
                  : '结束录音'}
            </button>
          )}
          <span>
            {state.recording === 'recording'
              ? '正在听你说话'
              : state.recording === 'finishing'
                ? '正在确认最后一句话…'
                : '也可以直接打字'}
          </span>
        </div>
        {state.partial && <p aria-label="识别中的文字">{state.partial}</p>}
        <form onSubmit={submit}>
          <label htmlFor="message-input">输入消息</label>
          <textarea
            id="message-input"
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={sending}
          />
          <button
            type="submit"
            disabled={!state.canControl || sending || !text.trim()}
          >
            {sending ? '正在保存…' : '发送'}
          </button>
        </form>
        <button
          type="button"
          disabled={!state.canControl}
          onClick={() => connection.stopReply()}
        >
          停止回复
        </button>
        {!state.canControl && state.status === 'connected' && (
          <p>此会话正在另一个窗口使用，本窗口只读。</p>
        )}
        <p role="status">
          {state.compacting
            ? '正在整理上下文，新输入会等待处理。'
            : state.generating
              ? '正在生成回复…'
              : state.playing
                ? '正在播放…'
                : '可以继续交流。'}
        </p>
        {(error || state.error) && <p role="alert">{error || state.error}</p>}
      </div>
    </section>
  )
}
