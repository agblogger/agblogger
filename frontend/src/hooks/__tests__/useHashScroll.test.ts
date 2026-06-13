import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { useHashScroll } from '@/hooks/useHashScroll'

function makeContainer(id: string): HTMLDivElement {
  const div = document.createElement('div')
  const target = document.createElement('span')
  target.id = id
  target.scrollIntoView = vi.fn()
  div.appendChild(target)
  return div
}

describe('useHashScroll', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function stubHash(hash: string) {
    Object.defineProperty(window, 'location', {
      value: { hash },
      writable: true,
      configurable: true,
    })
  }

  it('does nothing when html is null', () => {
    stubHash('#fn1')
    const container = makeContainer('fn1')
    const scrollSpy = vi.spyOn(container.querySelector('#fn1')!, 'scrollIntoView')
    const ref = { current: container }
    renderHook(() => useHashScroll(ref, null))
    expect(scrollSpy).not.toHaveBeenCalled()
  })

  it('does nothing when ref is null', () => {
    stubHash('#fn1')
    const ref = { current: null }
    expect(() => renderHook(() => useHashScroll(ref, '<p>content</p>'))).not.toThrow()
  })

  it('does nothing when the URL has no hash', () => {
    stubHash('')
    const container = makeContainer('fn1')
    const target = container.querySelector('#fn1')!
    const scrollSpy = vi.spyOn(target, 'scrollIntoView')
    const ref = { current: container }
    renderHook(() => useHashScroll(ref, '<p>content</p>'))
    expect(scrollSpy).not.toHaveBeenCalled()
  })

  it('scrolls to the element matching the hash when html is rendered', () => {
    stubHash('#fn1')
    const container = makeContainer('fn1')
    const target = container.querySelector('#fn1')!
    const scrollSpy = vi.spyOn(target, 'scrollIntoView')
    const ref = { current: container }
    renderHook(() => useHashScroll(ref, '<p>content</p>'))
    expect(scrollSpy).toHaveBeenCalledWith({ block: 'start' })
  })

  it('does nothing when the target element does not exist in the container', () => {
    stubHash('#missing')
    const container = makeContainer('fn1')
    const ref = { current: container }
    expect(() => renderHook(() => useHashScroll(ref, '<p>content</p>'))).not.toThrow()
  })

  it('scrolls again when html changes to new content', () => {
    stubHash('#fn1')
    const container = makeContainer('fn1')
    const target = container.querySelector('#fn1')!
    const scrollSpy = vi.spyOn(target, 'scrollIntoView')
    const ref = { current: container }
    const { rerender } = renderHook(({ html }: { html: string }) => useHashScroll(ref, html), {
      initialProps: { html: '<p>first</p>' },
    })
    expect(scrollSpy).toHaveBeenCalledTimes(1)
    rerender({ html: '<p>second</p>' })
    expect(scrollSpy).toHaveBeenCalledTimes(2)
  })

  it('decodes URL-encoded hash characters to find the element', () => {
    stubHash('#my%20heading')
    const container = document.createElement('div')
    const target = document.createElement('span')
    target.id = 'my heading'
    target.scrollIntoView = vi.fn()
    container.appendChild(target)
    const scrollSpy = vi.spyOn(target, 'scrollIntoView')
    const ref = { current: container }
    renderHook(() => useHashScroll(ref, '<p>content</p>'))
    expect(scrollSpy).toHaveBeenCalledWith({ block: 'start' })
  })
})
