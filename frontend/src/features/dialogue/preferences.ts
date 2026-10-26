/** 只保存当前浏览器的交互偏好；场景资料由服务端保存。 */
export type Preferences = {
  allowInterrupt: boolean
  subtitles: boolean
  shade: number
  volume: number
}
export const defaults: Preferences = {
  allowInterrupt: true,
  subtitles: true,
  shade: 35,
  volume: 80,
}
export function loadPreferences(): Preferences {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem('dialogue-preferences') ?? 'null',
    )
    if (!value || typeof value !== 'object') return defaults
    const item = value as Record<string, unknown>
    return {
      allowInterrupt:
        typeof item.allowInterrupt === 'boolean'
          ? item.allowInterrupt
          : defaults.allowInterrupt,
      subtitles:
        typeof item.subtitles === 'boolean'
          ? item.subtitles
          : defaults.subtitles,
      shade:
        typeof item.shade === 'number'
          ? Math.min(75, Math.max(10, item.shade))
          : defaults.shade,
      volume:
        typeof item.volume === 'number'
          ? Math.min(100, Math.max(0, item.volume))
          : defaults.volume,
    }
  } catch {
    return defaults
  }
}
export function savePreferences(value: Preferences): void {
  try {
    localStorage.setItem('dialogue-preferences', JSON.stringify(value))
  } catch {
    /* 浏览器禁止存储时，本次打开期间的设置仍然生效。 */
  }
}
