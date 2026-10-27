import { useEffect, useRef } from 'react'
import { spokenSubtitle, subtitlePages } from './subtitles'
import type { SpeechCaption, SubtitlePage } from './subtitles'

/** 字幕只读播放器时钟；文字模式单独按阅读节奏展示，不伪装成语音同步。 */
export function DialogueSubtitles({
  speech,
  partial,
  fallbackText,
  author,
  readPosition,
}: {
  speech?: SpeechCaption
  partial: string
  fallbackText: string
  author: string
  readPosition: () => number | null
}) {
  const textElement = useRef<HTMLParagraphElement>(null)
  const authorElement = useRef<HTMLSpanElement>(null)
  const measurer = useRef<HTMLSpanElement>(null)
  const progress = useRef({
    request: '',
    mode: '',
    page: 0,
    since: 0,
    finishedAt: 0,
    lastText: '',
  })

  useEffect(() => {
    const textNode = textElement.current
    const nameNode = authorElement.current
    const measureNode = measurer.current
    if (!textNode || !nameNode || !measureNode) return
    let frame = 0
    let width = textNode.clientWidth || 720
    const cache = new Map<string, SubtitlePage[]>()
    // 测量与字幕相同的字体；不以字符数猜测中英文混排的实际宽度。
    const measure = (text: string) => {
      measureNode.textContent = text
      const measuredWidth = measureNode.getBoundingClientRect().width
      measureNode.textContent = ''
      return measuredWidth
    }
    const pagesFor = (text: string) => {
      let pages = cache.get(text)
      if (!pages) {
        pages = subtitlePages(text, width - 2, measure)
        cache.set(text, pages)
      }
      return pages
    }
    const resize = () => {
      width = textNode.clientWidth || 720
      cache.clear()
    }
    window.addEventListener('resize', resize)
    let activeSegment = ''
    let measuredWidths = new Map<string, number>()
    const draw = (now: number) => {
      const current = progress.current
      if (current.request !== (speech?.requestId ?? '')) {
        Object.assign(current, {
          request: speech?.requestId ?? '',
          page: 0,
          since: now,
          finishedAt: 0,
          lastText: '',
        })
      }
      if (current.mode !== speech?.status) {
        current.mode = speech?.status ?? ''
        current.since = now
      }
      let shown = ''
      let faded = false
      if (partial) {
        shown = pagesFor(partial).at(-1)?.text ?? ''
      } else if (!speech) {
        shown = pagesFor(fallbackText)[0]?.text ?? ''
      } else if (speech.status === 'audio') {
        // 帧循环只更新播放位置；测量结果缓存，避免每帧重复布局测量。
        const key = `${width}:${speech.timings.length}`
        if (key !== activeSegment) {
          activeSegment = key
          measuredWidths = new Map()
        }
        shown = spokenSubtitle(
          speech.timings,
          readPosition(),
          width - 2,
          (text) => {
            let result = measuredWidths.get(text)
            if (result === undefined) {
              result = measure(text)
              measuredWidths.set(text, result)
            }
            return result
          },
        )
      } else if (speech.status === 'finished') {
        current.finishedAt ||= now
        shown = current.lastText
        faded = now - current.finishedAt > 2400
        if (now - current.finishedAt > 2750) shown = ''
      } else if (speech.status === 'text') {
        const pages = pagesFor(speech.text)
        current.page = Math.min(current.page, Math.max(0, pages.length - 1))
        const page = pages[current.page]
        const readingTime = Math.max(2400, (page?.text.length ?? 0) * 100)
        if (
          now - current.since > readingTime &&
          current.page < pages.length - 1
        ) {
          current.page++
          current.since = now
        }
        shown = pages[current.page]?.text ?? ''
        if (speech.complete && current.page === pages.length - 1) {
          faded = now - current.since > readingTime + 2400
          if (now - current.since > readingTime + 2750) shown = ''
        }
      }
      if (speech?.status === 'audio' && !partial && shown)
        current.lastText = shown
      if (textNode.textContent !== shown) textNode.textContent = shown
      nameNode.textContent = shown ? (partial ? '你' : author) : ''
      textNode.classList.toggle('subtitle-faded', faded)
      nameNode.classList.toggle('subtitle-faded', faded)
      frame = requestAnimationFrame(draw)
    }
    draw(performance.now())
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', resize)
    }
  }, [speech, partial, fallbackText, author, readPosition])

  return (
    <>
      <span className="latest-author" ref={authorElement} />
      <p className="subtitle latest-message-text" ref={textElement} />
      <span
        className="subtitle subtitle-measurer"
        aria-hidden="true"
        ref={measurer}
      />
    </>
  )
}
