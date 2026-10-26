import type { Scene } from './api'
import { Icon } from '../../shared/ui/Icon'

export function SceneCard({
  scene,
  index,
  count,
  onEnter,
  onEdit,
  disabled,
}: {
  scene: Scene
  index: number
  count: number
  onEnter: () => void
  onEdit: () => void
  disabled: boolean
}) {
  return (
    <div className="scene-card-wrap">
      <button
        className="scene-card"
        aria-label={`进入${scene.name}`}
        onClick={onEnter}
        disabled={disabled}
      >
        {scene.cover && <img src={scene.cover} alt={scene.name} />}
        <span className="card-top">
          <span className="glass-tag">{scene.category}</span>
          <span className="scene-number">
            {String(index + 1).padStart(2, '0')} /{' '}
            {String(count).padStart(2, '0')}
          </span>
        </span>
        <span className="card-bottom">
          <span className="card-title">{scene.name}</span>
          <span className="card-foot">
            <span>{scene.characterName}</span>
            <span className="card-enter">
              <Icon name="arrow" />
            </span>
          </span>
        </span>
      </button>
      <button
        className="card-edit round-button"
        aria-label={`编辑${scene.name}`}
        onClick={onEdit}
      >
        <Icon name="edit" />
      </button>
    </div>
  )
}
