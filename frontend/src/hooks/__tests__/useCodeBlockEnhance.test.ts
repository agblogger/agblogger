import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useCodeBlockEnhance } from '../useCodeBlockEnhance'

describe('useCodeBlockEnhance', () => {
  let container: HTMLDivElement

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
  })

  afterEach(() => {
    document.body.removeChild(container)
  })

  it('adds header to code blocks with language-* class', () => {
    container.innerHTML = '<pre><code class="language-python">print("hello")</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    const header = container.querySelector('.code-block-header')
    expect(header).not.toBeNull()
    expect(container.querySelector('.code-block-lang')?.textContent).toBe('python')
    expect(container.querySelector('.code-block-copy')?.textContent).toBe('Copy')
  })

  it('adds header to Pandoc sourceCode code blocks', () => {
    container.innerHTML = '<pre class="sourceCode python"><code class="sourceCode python">print("hello")</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    const header = container.querySelector('.code-block-header')
    expect(header).not.toBeNull()
    expect(container.querySelector('.code-block-lang')?.textContent).toBe('python')
    expect(container.querySelector('.code-block-copy')?.textContent).toBe('Copy')
  })

  it('does not add header to code blocks without language class', () => {
    container.innerHTML = '<pre><code>plain code</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    expect(container.querySelector('.code-block-header')).toBeNull()
  })

  it('does not duplicate headers on re-render', () => {
    container.innerHTML = '<pre><code class="language-js">code</code></pre>'
    const ref = { current: container }

    const { rerender } = renderHook(() => useCodeBlockEnhance(ref))
    rerender()

    const headers = container.querySelectorAll('.code-block-header')
    expect(headers).toHaveLength(1)
  })

  it('copies code to clipboard on copy button click', () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    container.innerHTML = '<pre><code class="language-js">const x = 1</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    const copyBtn = container.querySelector('.code-block-copy') as HTMLButtonElement
    copyBtn.click()

    expect(writeText).toHaveBeenCalledWith('const x = 1')
  })
})
