/** 字幕排版与语音时间数据；不负责合成、播放或会话保存。 */
export type WordTiming = { text: string; start: number; end: number }
export type TextTiming = {
  index: number
  text: string
  start: number
  end: number | null
  words: WordTiming[] | null
}
export type SpeechCaption = {
  requestId: string
  text: string
  timings: TextTiming[]
  status: 'pending' | 'audio' | 'text' | 'finished' | 'stopped'
  complete: boolean
}
export type SubtitlePage = { text: string; start: number; end: number }

/** 根据播放器位置选择字幕，不根据网络到达顺序推进。 */
export function spokenSubtitle(
  timings: TextTiming[],
  position: number | null,
  width: number,
  measure: (text: string) => number,
): string {
  if (position === null) return ''
  const segment = timings.filter((item) => item.start <= position).at(-1)
  if (!segment) return ''
  const pages = subtitlePages(segment.text, width, measure)
  let offset = 0
  let spokenOffset = 0
  for (const word of segment.words ?? []) {
    const start = segment.text.indexOf(word.text, offset)
    if (start < 0) continue
    if (word.start > position) break
    spokenOffset = start
    offset = start + word.text.length
  }
  return (
    (
      pages.find(
        (page) => page.start <= spokenOffset && spokenOffset < page.end,
      ) ?? pages[0]
    )?.text ?? ''
  )
}

/** 根据实际字体宽度分成两行，记录正文位置供时间匹配。 */
export function subtitlePages(
  text: string,
  width: number,
  measure: (text: string) => number,
): SubtitlePage[] {
  const pages: SubtitlePage[] = []
  let lines: string[] = []
  let line = ''
  let pageStart = 0
  let cursor = 0
  function flushPage() {
    if (line.trim()) lines.push(line.trim())
    if (lines.length)
      pages.push({ text: lines.join('\n'), start: pageStart, end: cursor })
    lines = []
    line = ''
    pageStart = cursor
  }
  // 句尾标点随前一个词或汉字换行，避免下一行以逗号、句号开头。
  const tokens =
    text.match(
      /(?:[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\S\n]+|[\s\S])[，。！？；：、,.!?;:）”’」』]*/gu,
    ) ?? []
  for (const token of tokens) {
    // 网址等单个超长词也必须能换行，不能撑破窄屏字幕。
    const parts = measure(token) > width ? Array.from(token) : [token]
    for (const part of parts) {
      if (line.trim() && measure((line + part).trim()) > width) {
        lines.push(line.trim())
        line = ''
        if (lines.length === 2) flushPage()
      }
      line += part
      cursor += part.length
      if (/[。！？!?\n]/u.test(part)) flushPage()
    }
  }
  flushPage()
  return pages
}
