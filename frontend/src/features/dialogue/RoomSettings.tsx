import { useState } from 'react'
import type { ReactNode } from 'react'
import { uploadImage } from '../scenes/api'
import type { Scene } from '../scenes/api'
import type { Preferences } from './preferences'
import { Icon } from '../../shared/ui/Icon'

/** 对话偏好由浏览器保存；背景上传直接修改服务端场景。 */
export function RoomSettings({
  scene,
  preferences,
  onPreferencesChange,
  onSceneChanged,
  onEdit,
  children,
}: {
  scene: Scene | null
  preferences: Preferences
  onPreferencesChange: (value: Preferences) => void
  onSceneChanged: (scene: Scene) => void
  onEdit: () => void
  children?: ReactNode
}) {
  const { shade, subtitles, allowInterrupt, volume } = preferences
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  async function changeBackground(file?: File) {
    if (!scene || !file || uploading) return
    setUploading(true)
    setError('')
    try {
      onSceneChanged(await uploadImage(scene.id, 'background', file))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '背景上传失败。')
    } finally {
      setUploading(false)
    }
  }
  return (
    <div className="panel-content">
      {error && (
        <p role="alert" className="error-note">
          {error}
        </p>
      )}
      {scene && (
        <section className="setting-section">
          <h3>
            <button className="setting-navigation" onClick={onEdit}>
              场景资料与身份
              <Icon name="arrow" />
            </button>
          </h3>
        </section>
      )}
      <section className="setting-section">
        <h3>视觉氛围</h3>
        {scene && (
          <>
            <div className="background-preview">
              {scene.background && (
                <img src={scene.background} alt="背景预览" />
              )}
            </div>
            <label className="upload-button">
              更换场景背景
              <input
                disabled={uploading}
                hidden
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => {
                  void changeBackground(event.target.files?.[0])
                  event.target.value = ''
                }}
              />
            </label>
          </>
        )}
        <div className="slider-label">
          <label htmlFor="shade">画面暗度</label>
          <output>{shade}%</output>
        </div>
        <input
          id="shade"
          type="range"
          min="10"
          max="75"
          value={shade}
          onChange={(e) =>
            onPreferencesChange({
              ...preferences,
              shade: Number(e.target.value),
            })
          }
        />
      </section>
      <section className="setting-section">
        <h3>对话方式</h3>
        <div className="setting-row">
          <label id="interrupt-label">允许打断回复</label>
          <button
            className="switch"
            role="switch"
            aria-labelledby="interrupt-label"
            aria-checked={allowInterrupt}
            onClick={() =>
              onPreferencesChange({
                ...preferences,
                allowInterrupt: !allowInterrupt,
              })
            }
          >
            <span />
          </button>
        </div>
        <div className="slider-label">
          <label htmlFor="volume">播放音量</label>
          <output>{volume}%</output>
        </div>
        <input
          id="volume"
          type="range"
          min="0"
          max="100"
          value={volume}
          onChange={(e) =>
            onPreferencesChange({
              ...preferences,
              volume: Number(e.target.value),
            })
          }
        />
        <div className="setting-row">
          <label id="subtitle-label">显示对话字幕</label>
          <button
            className="switch"
            role="switch"
            aria-labelledby="subtitle-label"
            aria-checked={subtitles}
            onClick={() =>
              onPreferencesChange({ ...preferences, subtitles: !subtitles })
            }
          >
            <span />
          </button>
        </div>
      </section>
      {children}
    </div>
  )
}
