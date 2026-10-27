import { useEffect, useRef, useState } from 'react'
import type { Character } from './api'
import { Icon } from '../../shared/ui/Icon'

export function CharacterCard({
  character,
  index,
  count,
  onEnter,
  onEdit,
  onCopy,
  disabled,
}: {
  character: Character
  index: number
  count: number
  onEnter: () => void
  onEdit: () => void
  onCopy: () => void
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const actions = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !actions.current?.contains(event.target)
      )
        setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        trigger.current?.focus()
      }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [open])
  return (
    <div className="character-card-wrap">
      <button
        className="character-card"
        aria-label={`进入${character.name}`}
        onClick={onEnter}
        disabled={disabled}
      >
        {character.cover && <img src={character.cover} alt={character.name} />}
        <span className="card-top">
          <span className="glass-tag">{character.category}</span>
          <span className="character-number">
            {String(index + 1).padStart(2, '0')} /{' '}
            {String(count).padStart(2, '0')}
          </span>
        </span>
        <span className="card-bottom">
          <span className="card-title">{character.name}</span>
          <span className="card-foot">
            <span>{character.characterName}</span>
            <span className="card-enter">
              <Icon name="arrow" />
            </span>
          </span>
        </span>
      </button>
      <div className="card-actions" ref={actions}>
        <button
          ref={trigger}
          className="round-button"
          aria-label={`${character.name}的更多操作`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          disabled={disabled}
        >
          <Icon name="more" />
        </button>
        {open && (
          <div className="card-action-list">
            <button
              disabled={disabled}
              onClick={() => {
                setOpen(false)
                onEdit()
              }}
            >
              <Icon name="edit" />
              编辑角色
            </button>
            <button
              disabled={disabled}
              onClick={() => {
                setOpen(false)
                onCopy()
              }}
            >
              <Icon name="copy" />
              复制角色
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
