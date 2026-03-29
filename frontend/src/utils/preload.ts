/**
 * Utilities for reading server-injected preload data on initial page load.
 *
 * The backend injects two sources of preloaded data:
 *   1. `<script id="__initial_data__" type="application/json">` — structured metadata (no HTML fields)
 *   2. DOM elements inside `<div id="root">` with data attributes — rendered HTML content
 *
 * These utilities merge both sources into typed objects matching the API response shapes.
 * All reads are one-shot: `readPreloadedMeta` removes the script tag on first call.
 */

/**
 * Reads and removes the `#__initial_data__` JSON script tag.
 * Returns parsed object or null. One-time read — returns null on every subsequent call.
 */
export function readPreloadedMeta(): Record<string, unknown> | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null
  const text = el.textContent
  el.remove()
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch (e) {
    console.error('Failed to parse preloaded data:', e)
    return null
  }
}

/**
 * Queries `selector` inside `#root` and returns its `innerHTML`, or null if not found.
 * Does not remove the element — React mount handles cleanup.
 */
export function readPreloadedHtml(selector: string): string | null {
  const root = document.getElementById('root')
  if (root === null) return null
  const el = root.querySelector(selector)
  if (el === null) return null
  return el.innerHTML
}

/**
 * Queries all elements matching `itemSelector` inside `#root`.
 * For each item, reads the `idAttr` attribute value and the innerHTML of the child
 * matching `contentSelector`. Returns a Map<id, innerHTML>.
 *
 * NOTE: `itemSelector` must be a simple `[attr]` attribute selector, e.g. `[data-id]`.
 * The `idAttr` is the bare attribute name used to read the value, e.g. `data-id`.
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

// Spec types for the declarative readPreloaded API

interface HtmlField {
  /** Target field name on the merged object, e.g. 'rendered_html' */
  field: string
  /** CSS selector for the content element inside #root, e.g. '[data-content]' */
  selector: string
}

interface ListHtmlField {
  /** Dot-separated path to the array in the JSON metadata, e.g. 'posts' or 'posts.posts' */
  path: string
  /** JSON field on each item to match against the DOM id attribute value, e.g. 'id' */
  key: string
  /** Target field name to set on each item, e.g. 'rendered_excerpt' */
  field: string
  /** CSS selector for list item elements inside #root, e.g. '[data-id]' */
  itemSelector: string
  /** CSS selector for the content element within each item, e.g. '[data-excerpt]' */
  contentSelector: string
}

interface PreloadSpec {
  html?: HtmlField
  listHtml?: ListHtmlField
}

/**
 * Navigates a dot-separated path on a plain object and returns the value at that path.
 */
function getByPath(obj: Record<string, unknown>, path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>((acc, segment) => {
      if (acc !== null && typeof acc === 'object' && segment in acc) {
        return (acc as Record<string, unknown>)[segment]
      }
      return undefined
    }, obj)
}

/**
 * Sets a value at a dot-separated path on a plain object (mutates the object).
 */
function setByPath(obj: Record<string, unknown>, path: string, value: unknown): void {
  const segments = path.split('.')
  let cursor: Record<string, unknown> = obj
  for (const segment of segments.slice(0, -1)) {
    const next = cursor[segment]
    if (next !== null && typeof next === 'object') {
      cursor = next as Record<string, unknown>
    } else {
      return
    }
  }
  const last = segments[segments.length - 1]
  if (last !== undefined) {
    cursor[last] = value
  }
}

/**
 * High-level declarative preload reader. Reads metadata from the JSON script tag and
 * merges rendered HTML from the DOM according to the provided spec.
 *
 * Returns the merged object, or null if no preload data was found (e.g. client navigation).
 * Cast the result to your expected type at the call site.
 */
export function readPreloaded(spec: PreloadSpec): Record<string, unknown> | null {
  const meta = readPreloadedMeta()
  if (meta === null) return null

  const result: Record<string, unknown> = { ...meta }

  if (spec.html !== undefined) {
    const html = readPreloadedHtml(spec.html.selector)
    if (html !== null) {
      result[spec.html.field] = html
    }
  }

  if (spec.listHtml !== undefined) {
    const { path, key, field, itemSelector, contentSelector } = spec.listHtml
    // Derive the bare attribute name from the itemSelector (supports simple [attr] selectors only)
    const idAttr = itemSelector.replace(/^\[|\]$/g, '')
    const htmlMap = readPreloadedHtmlMap(itemSelector, idAttr, contentSelector)

    const arr = getByPath(result, path)
    if (Array.isArray(arr)) {
      const merged = arr.map((item: unknown) => {
        if (item === null || typeof item !== 'object') return item
        const record = item as Record<string, unknown>
        const idVal = String(record[key])
        const html = htmlMap.get(idVal)
        if (html !== undefined) {
          return { ...record, [field]: html }
        }
        return record
      })
      setByPath(result, path, merged)
    }
  }

  return result
}
