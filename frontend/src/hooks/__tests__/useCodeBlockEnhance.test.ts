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

  it('re-runs enhancement when content parameter changes', () => {
    const ref = { current: container }
    container.innerHTML = ''

    const { rerender } = renderHook(
      ({ content }) => useCodeBlockEnhance(ref, content),
      { initialProps: { content: undefined as string | undefined } },
    )

    expect(container.querySelector('.code-block-header')).toBeNull()

    container.innerHTML = '<pre><code class="language-python">print("hello")</code></pre>'
    rerender({ content: '<pre><code class="language-python">print("hello")</code></pre>' })

    expect(container.querySelector('.code-block-header')).not.toBeNull()
    expect(container.querySelector('.code-block-lang')?.textContent).toBe('python')
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

  it('copies empty string when code element textContent is null', () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    container.innerHTML = '<pre><code class="language-js">placeholder</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    // Simulate null textContent (can occur in real browsers for edge-case elements)
    const codeEl = container.querySelector('code')!
    Object.defineProperty(codeEl, 'textContent', { value: null, configurable: true })

    const copyBtn = container.querySelector('.code-block-copy') as HTMLButtonElement
    copyBtn.click()

    expect(writeText).toHaveBeenCalledWith('')
  })

  it('logs warning when clipboard writeText rejects', async () => {
    const clipboardError = new Error('clipboard denied')
    const writeText = vi.fn().mockRejectedValue(clipboardError)
    Object.assign(navigator, { clipboard: { writeText } })
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    container.innerHTML = '<pre><code class="language-js">code</code></pre>'
    const ref = { current: container }

    renderHook(() => useCodeBlockEnhance(ref))

    const copyBtn = container.querySelector('.code-block-copy') as HTMLButtonElement
    copyBtn.click()

    await vi.waitFor(() => {
      expect(warnSpy).toHaveBeenCalledWith('Code block copy failed:', clipboardError)
    })

    warnSpy.mockRestore()
  })

  it('catches errors during code block enhancement without crashing', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    // Create a container where querySelectorAll returns elements that will cause errors
    // by making parentElement throw when accessed
    container.innerHTML = '<pre><code class="language-js">code</code></pre>'
    const codeEl = container.querySelector('code')!
    const originalParent = Object.getOwnPropertyDescriptor(Node.prototype, 'parentElement')!
    Object.defineProperty(codeEl, 'parentElement', {
      get() { throw new Error('DOM error') },
      configurable: true,
    })

    const ref = { current: container }

    // Should not throw
    expect(() => renderHook(() => useCodeBlockEnhance(ref))).not.toThrow()
    expect(warnSpy).toHaveBeenCalledWith(
      'Code block enhancement failed:',
      expect.any(Error),
    )

    // Restore
    Object.defineProperty(codeEl, 'parentElement', originalParent)
    warnSpy.mockRestore()
  })

  it('catches errors during MutationObserver-triggered enhancement', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    container.innerHTML = ''
    const ref = { current: container }
    renderHook(() => useCodeBlockEnhance(ref))

    // Now add a code block where DOM operations will throw
    const pre = document.createElement('pre')
    const code = document.createElement('code')
    code.className = 'language-js'
    code.textContent = 'code'
    Object.defineProperty(code, 'parentElement', {
      get() { throw new Error('DOM error in observer') },
      configurable: true,
    })
    pre.appendChild(code)
    container.appendChild(pre)

    // Wait for MutationObserver to fire
    await vi.waitFor(() => {
      expect(warnSpy).toHaveBeenCalledWith(
        'Code block enhancement failed:',
        expect.any(Error),
      )
    })

    warnSpy.mockRestore()
  })
})
