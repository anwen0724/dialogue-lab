// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { SceneEditor } from '../src/features/scenes/SceneEditor'

afterEach(cleanup)

function Editor() {
  const [open, setOpen] = useState(true)
  return open ? (
    <SceneEditor
      onClose={() => setOpen(false)}
      onSaved={() => {}}
      onDeleted={() => {}}
    />
  ) : null
}

test('取消文件选择保留侧栏和未保存内容，面板自身仍可取消', () => {
  // jsdom 不实现原生模态框，仅补齐浏览器边界。
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.setAttribute('open', '')
    },
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value() {
      this.removeAttribute('open')
    },
  })
  render(<Editor />)
  fireEvent.change(screen.getByLabelText('人物名字'), {
    target: { value: 'Alice' },
  })
  for (const label of ['封面图片', '背景图片']) {
    fireEvent(
      screen.getByLabelText(label),
      new Event('cancel', { bubbles: true }),
    )
    expect(screen.getByDisplayValue('Alice')).toBeDefined()
    expect(screen.getByRole('dialog', { name: '新建场景' })).toBeDefined()
  }
  fireEvent(
    screen.getByRole('dialog', { name: '新建场景' }),
    new Event('cancel', { cancelable: true }),
  )
  expect(screen.queryByRole('dialog')).toBeNull()
})
