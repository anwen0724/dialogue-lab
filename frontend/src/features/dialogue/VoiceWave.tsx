import { useEffect, useRef } from 'react'

const BAR_COUNT = 29

/** 从播放或麦克风的实际采样读取音量；静音时不模拟声音。 */
export function VoiceWave({ readAmplitude }: { readAmplitude: () => number }) {
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let frame = 0
    let level = 0
    const recentLevels = new Float32Array(BAR_COUNT)
    const bars = root.current?.querySelectorAll('rect')
    function draw() {
      level = level * 0.7 + Math.min(1, readAmplitude() * 5) * 0.3
      // 相邻竖条展示短暂的音量变化，中心较高；没有声音时收拢并淡出。
      recentLevels.copyWithin(1, 0)
      recentLevels[0] = level
      root.current?.classList.toggle('animated', level > 0.005)
      bars?.forEach((bar, index) => {
        const distance = Math.abs(index - (BAR_COUNT - 1) / 2)
        const envelope = 0.2 + 0.8 * Math.cos((distance / BAR_COUNT) * Math.PI)
        const height = 4 + recentLevels[distance] * envelope * 40
        bar.setAttribute('height', height.toFixed(1))
        bar.setAttribute('y', ((48 - height) / 2).toFixed(1))
      })
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(frame)
  }, [readAmplitude])
  return (
    <div className="voice-wave" ref={root} aria-hidden="true">
      <svg viewBox="0 0 200 48">
        {Array.from({ length: BAR_COUNT }, (_, index) => (
          <rect key={index} x={index * 7} y={22} width={4} height={4} rx={2} />
        ))}
      </svg>
    </div>
  )
}
