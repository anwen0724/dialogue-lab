import { Icon } from '../../shared/ui/Icon'

/** 两个入口复用同一草稿与发送操作，回车选词期间不提交。 */
export function MessageComposer({
  text,
  onChange,
  onSend,
  disabled,
  panel = false,
  onStop,
  busy = false,
}: {
  text: string
  onChange: (value: string) => void
  onSend: () => void
  disabled: boolean
  panel?: boolean
  onStop?: () => void
  busy?: boolean
}) {
  return (
    <form
      className={panel ? 'panel-composer' : 'composer'}
      onSubmit={(event) => {
        event.preventDefault()
        if (!disabled && text.trim()) onSend()
      }}
    >
      <label
        htmlFor={panel ? 'panel-message-input' : 'message-input'}
        className="sr-only"
      >
        输入消息
      </label>
      <textarea
        id={panel ? 'panel-message-input' : 'message-input'}
        rows={panel ? 3 : 1}
        value={text}
        maxLength={32000}
        placeholder="想到什么，就写下来…"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (
            event.key === 'Enter' &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault()
            if (!disabled && text.trim()) onSend()
          }
        }}
      />
      {panel ? (
        <div className="panel-composer-actions">
          <small>Enter 发送 · Shift + Enter 换行</small>
          {busy && (
            <button type="button" className="panel-stop" onClick={onStop}>
              停止回复
            </button>
          )}
          <button
            className="send-button"
            disabled={disabled || !text.trim()}
            aria-label="发送消息"
          >
            <Icon name="arrow" />
          </button>
        </div>
      ) : (
        <button
          className="send-button"
          disabled={disabled || !text.trim()}
          aria-label="发送消息"
        >
          <Icon name="arrow" />
        </button>
      )}
    </form>
  )
}
