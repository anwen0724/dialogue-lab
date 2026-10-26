import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { Icon } from './Icon'

/** 右侧覆盖面板拥有焦点和关闭行为，不改变页面宽度。 */
export function SidePanel({
  title,
  children,
  onClose,
  className = '',
}: {
  title: string
  children: ReactNode
  onClose: () => void
  className?: string
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])
  return (
    <dialog
      ref={dialog}
      className={`side-panel ${className}`}
      aria-label={title}
      onCancel={(event) => {
        // 文件选择框的取消事件会冒泡，只处理面板自身的取消。
        if (event.target !== event.currentTarget) return
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (
          event.target === event.currentTarget &&
          event.clientX < event.currentTarget.getBoundingClientRect().left
        )
          onClose()
      }}
    >
      <div className="panel-header">
        <h2>{title}</h2>
        <button
          className="round-button"
          aria-label="关闭面板"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  )
}
