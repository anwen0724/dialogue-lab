// @vitest-environment jsdom
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { DialogueSubtitles } from '../src/features/dialogue/DialogueSubtitles'
import type { SpeechCaption } from '../src/features/dialogue/subtitles'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

/** 时间与尺寸替代浏览器边界；字幕选择、翻页和淡出均执行真实组件。 */
function clock() {
  let frame: FrameRequestCallback = () => {}
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frame = callback
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.spyOn(performance, 'now').mockReturnValue(100)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(82)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      return { width: (this.textContent?.length ?? 0) * 10 } as DOMRect
    },
  )
  return (time: number) => act(() => frame(time))
}

test('字幕只随播放位置换页，生成提前完成也不抢跑，播放结束淡出，停止立即清空', () => {
  const tick = clock()
  let position: number | null = null
  const readPosition = () => position
  const speech: SpeechCaption = {
    requestId: 'one',
    text: '第一句。第二句。',
    complete: true,
    status: 'audio',
    timings: [
      { index: 0, text: '第一句。', start: 0, end: 1, words: null },
      { index: 1, text: '第二句。', start: 1, end: 2, words: null },
    ],
  }
  const props = { partial: '', fallbackText: '', author: 'Emma', readPosition }
  const view = render(<DialogueSubtitles {...props} speech={speech} />)
  const subtitle = () => view.container.querySelector('.latest-message-text')
  expect(subtitle()?.textContent).toBe('')
  position = 0.5
  tick(200)
  expect(subtitle()?.textContent).toBe('第一句。')
  tick(5000)
  expect(subtitle()?.textContent).toBe('第一句。')
  position = 1.1
  tick(5100)
  expect(subtitle()?.textContent).toBe('第二句。')
  view.rerender(
    <DialogueSubtitles {...props} speech={{ ...speech, status: 'finished' }} />,
  )
  expect(subtitle()?.textContent).toBe('第二句。')
  tick(2600)
  expect(subtitle()?.classList.contains('subtitle-faded')).toBe(true)
  tick(2900)
  expect(subtitle()?.textContent).toBe('')
  view.rerender(<DialogueSubtitles {...props} speech={speech} />)
  expect(subtitle()?.textContent).toBe('第二句。')
  view.rerender(
    <DialogueSubtitles {...props} speech={{ ...speech, status: 'stopped' }} />,
  )
  expect(subtitle()?.textContent).toBe('')
})

test('等待合成失败后，文字模式从第一页开始逐页展示，识别临时结果显示末页', () => {
  const tick = clock()
  const speech: SpeechCaption = {
    requestId: 'one',
    text: '第一句。第二句。',
    complete: true,
    status: 'pending',
    timings: [],
  }
  const props = {
    partial: '',
    fallbackText: '',
    author: 'Emma',
    readPosition: () => null,
  }
  const view = render(<DialogueSubtitles {...props} speech={speech} />)
  tick(10000)
  vi.spyOn(performance, 'now').mockReturnValue(10000)
  view.rerender(
    <DialogueSubtitles {...props} speech={{ ...speech, status: 'text' }} />,
  )
  const subtitle = () =>
    view.container.querySelector('.latest-message-text')?.textContent
  expect(subtitle()).toBe('第一句。')
  tick(12500)
  expect(subtitle()).toBe('第二句。')
  view.rerender(
    <DialogueSubtitles
      {...props}
      partial="第一句。第二句。最新识别。"
      speech={speech}
    />,
  )
  expect(subtitle()).toBe('最新识别。')
})
