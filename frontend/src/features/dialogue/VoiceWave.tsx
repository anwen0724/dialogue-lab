import { useEffect, useRef } from 'react'

/** 从播放或麦克风的实际采样读取音量；静音时不模拟声音。 */
export function VoiceWave({ readAmplitude }: { readAmplitude: () => number }) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let frame = 0
    let level = 0
    let previousTime = 0
    const paths = root.current?.querySelectorAll('path')
    function draw(time: number) {
      const elapsed = previousTime ? Math.min(time - previousTime, 100) : 16
      previousTime = time
      const target = Math.min(1, readAmplitude() * 5)
      // 按经过时间平滑音量，不让高刷新率屏幕改变起伏速度。
      level += (target - level) * (1 - Math.exp(-elapsed / 100))
      root.current?.classList.toggle('animated', level > 0.01)
      paths?.forEach((path, layer) => {
        const phase = time / 650
        const amplitude = level * (10 - layer * 2.5)
        const points: string[] = []
        for (let x = 0; x <= 180; x += 3) {
          const envelope = Math.sin((x / 180) * Math.PI) ** 2
          const wave = Math.sin((x / 180) * Math.PI * 4 - phase + layer * 0.9)
          const y = 16 + wave * amplitude * envelope
          points.push(`${x === 0 ? 'M' : 'L'}${x},${y.toFixed(2)}`)
        }
        path.setAttribute('d', points.join(' '))
      })
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [readAmplitude])
  return (
    <div className="voice-wave" ref={root} aria-hidden="true">
      <svg viewBox="0 0 180 32">
        <path d="M0,16 L180,16" />
        <path d="M0,16 L180,16" />
        <path d="M0,16 L180,16" />
      </svg>
    </div>
  )
}
