import { useEffect } from 'react'
import type { RefObject } from 'react'

function extractLanguage(codeEl: Element): string {
  // Pandoc format: class="sourceCode python" on code or pre
  // Standard format: class="language-python"
  for (const cls of codeEl.classList) {
    if (cls === 'sourceCode') continue
    const langMatch = cls.match(/^language-(.+)$/)
    if (langMatch?.[1] != null) return langMatch[1]
    // Pandoc puts the language name as a plain class alongside sourceCode
    if (codeEl.classList.contains('sourceCode') && cls !== 'sourceCode') return cls
  }
  return ''
}

function enhanceCodeBlocks(container: HTMLElement) {
  container.querySelectorAll('pre > code').forEach((codeEl) => {
    const pre = codeEl.parentElement
    if (!pre || pre.querySelector('.code-block-header')) return

    const lang = extractLanguage(codeEl)
    if (!lang && !codeEl.classList.contains('sourceCode') && !codeEl.className.includes('language-')) return

    const header = document.createElement('div')
    header.className = 'code-block-header'

    if (lang) {
      const langLabel = document.createElement('span')
      langLabel.className = 'code-block-lang'
      langLabel.textContent = lang
      header.appendChild(langLabel)
    }

    const copyBtn = document.createElement('button')
    copyBtn.className = 'code-block-copy'
    copyBtn.textContent = 'Copy'
    copyBtn.type = 'button'
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(codeEl.textContent).then(
        () => {
          copyBtn.textContent = 'Copied!'
          setTimeout(() => {
            copyBtn.textContent = 'Copy'
          }, 2000)
        },
        () => {
          copyBtn.textContent = 'Failed'
          setTimeout(() => {
            copyBtn.textContent = 'Copy'
          }, 2000)
        },
      )
    })
    header.appendChild(copyBtn)

    pre.style.position = 'relative'
    pre.insertBefore(header, pre.firstChild)
  })
}

export function useCodeBlockEnhance(contentRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const container = contentRef.current
    if (!container) return

    enhanceCodeBlocks(container)

    const observer = new MutationObserver(() => {
      enhanceCodeBlocks(container)
    })
    observer.observe(container, { childList: true, subtree: true })

    return () => observer.disconnect()
  }, [contentRef])
}
