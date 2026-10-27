import { expect, test } from 'vitest'
import {
  spokenSubtitle,
  subtitlePages,
} from '../src/features/dialogue/subtitles'

test('长句按可用宽度排为两行，所有文字均保留且短英文单词不断开', () => {
  const text = '以前有个修表匠，铺子小得只能转身，柜台上摆着一只不走的钟。'
  const pages = subtitlePages(text, 8, (value) => value.length)
  expect(pages.length).toBeGreaterThan(1)
  expect(pages.map((page) => page.text.replaceAll('\n', '')).join('')).toBe(
    text,
  )
  for (const page of pages) {
    expect(page.text.split('\n').length).toBeLessThanOrEqual(2)
    expect(page.text.split('\n').every((line) => line.length <= 8)).toBe(true)
  }
  const english = subtitlePages(
    'Hello there friend',
    11,
    (value) => value.length,
  )
  expect(english[0].text).toBe('Hello there\nfriend')
  const punctuation = subtitlePages(
    '一二三四五六七八，九十。',
    8,
    (value) => value.length,
  )
  expect(punctuation[0].text).toBe('一二三四五六七\n八，九十。')
})

test('提前收到下一句也只显示正在播放的句子，长句按真实字词时间换页', () => {
  const timings = [
    {
      index: 0,
      text: '一二三四五六',
      start: 0,
      end: 6,
      words: Array.from('一二三四五六', (text, index) => ({
        text,
        start: index,
        end: index + 1,
      })),
    },
    { index: 1, text: '下一句', start: 6, end: 8, words: null },
  ]
  const measure = (value: string) => value.length
  expect(spokenSubtitle(timings, null, 2, measure)).toBe('')
  expect(spokenSubtitle(timings, 0.5, 2, measure)).toBe('一二\n三四')
  expect(spokenSubtitle(timings, 4.2, 2, measure)).toBe('五六')
  expect(spokenSubtitle(timings, 6.1, 2, measure)).toBe('下一\n句')
})
