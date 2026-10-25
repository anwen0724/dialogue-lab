/** 页面内的语音输入区域；连接及音频生命周期由功能模块管理。 */
import { useVoiceInput } from './useVoiceInput'
import './voice-input.css'

export function VoiceInput() {
  const { state, partials, messages, start, stop } = useVoiceInput()
  const canStart = state.status === 'idle' || state.status === 'error'
  const statusText = {
    idle: '尚未开始',
    preparing: '正在准备麦克风与识别服务…',
    listening: '正在听，你可以自然说话',
    stopping: '正在处理最后一句话…',
    error: '录音已停止',
  }[state.status]
  return (
    <section className="voice-input" aria-labelledby="voice-heading">
      <div className="voice-controls">
        <div>
          <h2 id="voice-heading">语音输入</h2>
          <p role="status">
            <span
              className={`voice-indicator voice-indicator--${state.status}`}
              aria-hidden="true"
            />
            {statusText}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void (canStart ? start() : stop())
          }}
          disabled={state.status === 'stopping'}
        >
          {canStart
            ? '开始说话'
            : state.status === 'preparing'
              ? '取消准备'
              : state.status === 'stopping'
                ? '正在结束…'
                : '结束录音'}
        </button>
      </div>
      {state.status === 'error' && <p role="alert">{state.message}</p>}
      <div className="voice-live" aria-label="识别中的文字">
        <span className="voice-caption">实时识别</span>
        {partials.length ? (
          partials.map((partial) => (
            <p key={partial.segmentId}>{partial.text}</p>
          ))
        ) : (
          <p className="voice-placeholder">
            {state.status === 'listening'
              ? '正在听，开口说一句吧。'
              : '开始后，这里会显示你正在说的话。'}
          </p>
        )}
      </div>
      <div className="voice-messages">
        <h3>
          已识别的消息 <span>{messages.length}</span>
        </h3>
        {messages.length === 0 && (
          <p className="voice-placeholder">
            说完停顿一下，识别结果会出现在这里。
          </p>
        )}
        <ol aria-label="用户消息" aria-live="polite" aria-relevant="additions">
          {messages.map((message) => (
            <li key={message.id}>
              <span className="voice-caption">你</span>
              <p>{message.text}</p>
            </li>
          ))}
        </ol>
      </div>
      <p className="voice-note">消息仅在当前页面展示，刷新后清空。</p>
    </section>
  )
}
