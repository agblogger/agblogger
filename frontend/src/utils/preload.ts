/** Read and remove the server-injected preload metadata JSON. One-time read. */
export function readPreloadedMeta(): unknown {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  const raw = el.textContent
  el.remove()
  try {
    return JSON.parse(raw) as unknown
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

export interface HtmlField {
  field: string
  selector: string
}

export interface ListHtmlField {
  path: string
  key: string
  field: string
  itemSelector: string
  contentSelector: string
}

export interface PreloadSpec {
  html?: HtmlField
  listHtml?: ListHtmlField
}

/** Declarative preload reader: reads slim JSON metadata and merges HTML extracted from the DOM. */
export function readPreloaded(spec: PreloadSpec): unknown {
  const meta = readPreloadedMeta()
  if (meta === null) return null

  const record = meta as Record<string, unknown>

  if (spec.html !== undefined) {
    const html = readPreloadedHtml(spec.html.selector)
    record[spec.html.field] = html ?? ''
  }

  if (spec.listHtml !== undefined) {
    const { path, key, field, itemSelector, contentSelector } = spec.listHtml
    const idAttr = itemSelector.replace(/^\[|\]$/g, '')
    const htmlMap = readPreloadedHtmlMap(itemSelector, idAttr, contentSelector)

    const segments = path.split('.')
    let target: unknown = record
    for (const segment of segments) {
      target = (target as Record<string, unknown>)[segment]
    }

    if (Array.isArray(target)) {
      for (const item of target) {
        const itemRecord = item as Record<string, unknown>
        const itemId = String(itemRecord[key])
        itemRecord[field] = htmlMap.get(itemId) ?? ''
      }
    }
  }

  return record
}
