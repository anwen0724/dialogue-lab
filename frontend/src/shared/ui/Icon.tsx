/** 页面使用同一组线性图标，图标本身不承载交互状态。 */
export function Icon({
  name,
}: {
  name:
    | 'arrow'
    | 'back'
    | 'close'
    | 'settings'
    | 'mic'
    | 'keyboard'
    | 'pause'
    | 'history'
    | 'edit'
    | 'plus'
}) {
  const paths = {
    arrow: 'M5 12h14m-6-6 6 6-6 6',
    back: 'M19 12H5m6-6-6 6 6 6',
    close: 'm6 6 12 12M6 18 18 6',
    settings: 'M4 7h16M4 17h16M9 4v6m6 4v6',
    mic: 'M9 6a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0V6M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-3 0h6',
    keyboard:
      'M3 5h18v14H3zM6 9h2m2 0h2m2 0h2m2 0h1M6 12h2m2 0h2m2 0h2m-9 3h10',
    pause: 'M9 6v12M15 6v12',
    history: 'M4 5h16v13H9l-5 3V5ZM8 9h8M8 13h5',
    edit: 'm4 16 12-12 4 4L8 20H4v-4ZM14 6l4 4',
    plus: 'M12 5v14M5 12h14',
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  )
}
