import { useEffect, useRef } from 'react'

/** 从播放或麦克风的实际采样读取音量；静音时不模拟声音。 */
export function VoiceWave({ readAmplitude }: { readAmplitude: () => number }) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let frame = 0
    let level = 0
    function draw(time: number) {
      level = level * 0.7 + Math.min(1, readAmplitude() * 5) * 0.3
      root.current?.classList.toggle('animated', level > 0.005)
      root.current?.querySelectorAll('path').forEach((path, index) => {
        const points = Array.from({ length: 81 }, (_, step) => {
          const x = step * 4
          const envelope = Math.sin((Math.PI * step) / 80) ** 2
          const y =
            36 +
            Math.sin(step * 0.22 - time * 0.004 + index * 0.9) *
              envelope *
              level *
              (27 - index * 5)
          return `${step ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
        })
        path.setAttribute('d', points.join(' '))
      })
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [readAmplitude])
  return (
    <div className="voice-wave" ref={root} aria-hidden="true">
      <svg viewBox="0 0 320 72" fill="none">
        <path className="wave-line wave-line-front" />
        <path className="wave-line wave-line-middle" />
        <path className="wave-line wave-line-back" />
      </svg>
    </div>
  )
}
