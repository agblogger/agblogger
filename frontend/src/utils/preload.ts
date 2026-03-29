/** Read and remove the server-injected preload metadata JSON. One-time read. */
export function readPreloadedMeta<T>(): T | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  const raw = el.textContent
  el.remove()
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

/** Extract innerHTML from a single element matching `selector` inside #root. */
export function readPreloadedHtml(selector: string): string | null {
  const root = document.getElementById('root')
  if (root === null) return null

  const el = root.querySelector(selector)
  if (el === null) return null

  return el.innerHTML
}

/**
 * Extract an id-keyed map of innerHTML from list items inside #root.
 *
 * Queries all elements matching `itemSelector`, reads the id from `idAttr`,
 * and extracts innerHTML from the child matching `contentSelector`.
 */
export function readPreloadedHtmlMap(
  itemSelector: string,
  idAttr: string,
  contentSelector: string,
): Map<string, string> {
  const result = new Map<string, string>()
  const root = document.getElementById('root')
  if (root === null) return result

  const items = root.querySelectorAll(itemSelector)
  for (const item of items) {
    const id = item.getAttribute(idAttr)
    if (id === null) continue

    const contentEl = item.querySelector(contentSelector)
    if (contentEl === null) continue

    result.set(id, contentEl.innerHTML)
  }

  return result
}
