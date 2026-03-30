import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

// Import after DOM setup
import {
  readPreloadedMeta,
  readPreloadedHtml,
  readPreloadedHtmlMap,
  readPreloaded,
} from '../preload'

function injectScriptTag(data: unknown): HTMLScriptElement {
  const script = document.createElement('script')
  script.id = '__initial_data__'
  script.setAttribute('data-agblogger-preload', '')
  script.type = 'application/json'
  script.textContent = JSON.stringify(data)
  document.body.appendChild(script)
  return script
}

function injectInvalidScriptTag(): HTMLScriptElement {
  const script = document.createElement('script')
  script.id = '__initial_data__'
  script.setAttribute('data-agblogger-preload', '')
  script.type = 'application/json'
  script.textContent = '{ invalid json }'
  document.body.appendChild(script)
  return script
}

function injectRootHtml(html: string): void {
  let root = document.getElementById('root')
  if (!root) {
    root = document.createElement('div')
    root.id = 'root'
    document.body.appendChild(root)
  }
  root.innerHTML = html
}

beforeEach(() => {
  // Clean up any leftover script tags and root element
  document.getElementById('__initial_data__')?.remove()
  const root = document.getElementById('root')
  if (root) root.innerHTML = ''
})

afterEach(() => {
  document.getElementById('__initial_data__')?.remove()
  const root = document.getElementById('root')
  if (root) root.innerHTML = ''
})

// === readPreloadedMeta ===

describe('readPreloadedMeta', () => {
  it('returns parsed JSON from the script tag', () => {
    injectScriptTag({ title: 'Hello', id: 42 })
    const result = readPreloadedMeta()
    expect(result).toEqual({ title: 'Hello', id: 42 })
  })

  it('removes the script tag after reading', () => {
    injectScriptTag({ x: 1 })
    readPreloadedMeta()
    expect(document.getElementById('__initial_data__')).toBeNull()
  })

  it('returns null on second call (tag already removed)', () => {
    injectScriptTag({ x: 1 })
    readPreloadedMeta()
    const result = readPreloadedMeta()
    expect(result).toBeNull()
  })

  it('returns null when no script tag exists', () => {
    const result = readPreloadedMeta()
    expect(result).toBeNull()
  })

  it('returns null and logs error when JSON is invalid', () => {
    injectInvalidScriptTag()
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const result = readPreloadedMeta()
    expect(result).toBeNull()
    expect(consoleSpy).toHaveBeenCalledWith(
      'Failed to parse preloaded data:',
      expect.any(SyntaxError),
    )
    consoleSpy.mockRestore()
  })

  it('ignores rendered content that forges the preload id', () => {
    injectRootHtml('<div id="__initial_data__">{"file_path":"posts/forged/index.md"}</div>')
    injectScriptTag({ file_path: 'posts/real/index.md' })

    const result = readPreloadedMeta()

    expect(result).toEqual({ file_path: 'posts/real/index.md' })
  })
})

// === readPreloadedHtml ===

describe('readPreloadedHtml', () => {
  it('returns innerHTML of matching element inside #root', () => {
    injectRootHtml('<div data-content><p>Post content</p></div>')
    const result = readPreloadedHtml('[data-content]')
    expect(result).toBe('<p>Post content</p>')
  })

  it('returns null when selector does not match', () => {
    injectRootHtml('<div><p>No marker</p></div>')
    const result = readPreloadedHtml('[data-content]')
    expect(result).toBeNull()
  })

  it('returns null when #root does not exist', () => {
    document.getElementById('root')?.remove()
    const result = readPreloadedHtml('[data-content]')
    expect(result).toBeNull()
  })

  it('returns empty string for element with no children', () => {
    injectRootHtml('<div data-content></div>')
    const result = readPreloadedHtml('[data-content]')
    expect(result).toBe('')
  })
})

// === readPreloadedHtmlMap ===

describe('readPreloadedHtmlMap', () => {
  it('returns a map of id → innerHTML for matching list items', () => {
    injectRootHtml(`
      <ul>
        <li data-id="5"><div data-excerpt><p>Excerpt A</p></div></li>
        <li data-id="7"><div data-excerpt><p>Excerpt B</p></div></li>
      </ul>
    `)
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.get('5')).toBe('<p>Excerpt A</p>')
    expect(result.get('7')).toBe('<p>Excerpt B</p>')
    expect(result.size).toBe(2)
  })

  it('returns empty map when no items match itemSelector', () => {
    injectRootHtml('<ul><li><p>No attribute</p></li></ul>')
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(0)
  })

  it('skips items where contentSelector does not match', () => {
    injectRootHtml('<ul><li data-id="3"><p>No excerpt marker</p></li></ul>')
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(0)
  })

  it('returns empty map when #root does not exist', () => {
    document.getElementById('root')?.remove()
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(0)
  })
})

// === readPreloaded ===

describe('readPreloaded', () => {
  it('returns null when no script tag and no spec', () => {
    const result = readPreloaded({})
    expect(result).toBeNull()
  })

  it('returns null when script tag is absent (no preload)', () => {
    const result = readPreloaded({ html: { field: 'rendered_html', selector: '[data-content]' } })
    expect(result).toBeNull()
  })

  it('merges single html field from DOM into metadata', () => {
    injectScriptTag({ id: 1, title: 'My Post', is_draft: false })
    injectRootHtml('<div data-content><p>Post body</p></div>')
    const result = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    expect(result).toEqual({
      id: 1,
      title: 'My Post',
      is_draft: false,
      rendered_html: '<p>Post body</p>',
    })
  })

  it('merges list html fields from DOM into metadata posts array', () => {
    injectScriptTag({
      posts: [
        { id: 5, title: 'Post A', is_draft: false },
        { id: 7, title: 'Post B', is_draft: false },
      ],
      total: 2,
      page: 1,
      per_page: 10,
      total_pages: 1,
    })
    injectRootHtml(`
      <ul>
        <li data-id="5"><div data-excerpt><p>Excerpt A</p></div></li>
        <li data-id="7"><div data-excerpt><p>Excerpt B</p></div></li>
      </ul>
    `)
    const result = readPreloaded({
      listHtml: {
        path: 'posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })
    expect(result).not.toBeNull()
    const posts = result!['posts'] as Array<Record<string, unknown>>
    expect(posts[0]!['rendered_excerpt']).toBe('<p>Excerpt A</p>')
    expect(posts[1]!['rendered_excerpt']).toBe('<p>Excerpt B</p>')
    expect(result!['total']).toBe(2)
  })

  it('merges list html at nested path (posts.posts)', () => {
    injectScriptTag({
      label: { id: 'tech', names: ['Technology'] },
      posts: {
        posts: [
          { id: 3, title: 'Tech Post', is_draft: false },
        ],
        total: 1,
        page: 1,
        per_page: 10,
        total_pages: 1,
      },
    })
    injectRootHtml(`
      <ul>
        <li data-id="3"><div data-excerpt><p>Tech excerpt</p></div></li>
      </ul>
    `)
    const result = readPreloaded({
      listHtml: {
        path: 'posts.posts',
        key: 'id',
        field: 'rendered_excerpt',
        itemSelector: '[data-id]',
        contentSelector: '[data-excerpt]',
      },
    })
    expect(result).not.toBeNull()
    const postsObj = result!['posts'] as Record<string, unknown>
    const posts = postsObj['posts'] as Array<Record<string, unknown>>
    expect(posts[0]!['rendered_excerpt']).toBe('<p>Tech excerpt</p>')
  })

  it('returns metadata without html field when html selector does not match', () => {
    injectScriptTag({ id: 1, title: 'Post' })
    injectRootHtml('<div><p>No content marker</p></div>')
    const result = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    // Meta is returned but without the html field
    expect(result).not.toBeNull()
    expect(result!['id']).toBe(1)
    expect(result!['rendered_html']).toBeUndefined()
  })

  it('removes the script tag (one-shot read)', () => {
    injectScriptTag({ id: 1 })
    readPreloaded({})
    expect(document.getElementById('__initial_data__')).toBeNull()
  })
})

// === Lazy module-level pattern: multiple imports only consume once ===

describe('lazy preload pattern', () => {
  it('readPreloadedMeta only reads the tag once across multiple calls', () => {
    injectScriptTag({ value: 42 })
    const first = readPreloadedMeta()
    const second = readPreloadedMeta()
    expect(first).toEqual({ value: 42 })
    expect(second).toBeNull()
  })

  it('readPreloaded called twice returns null on second call', () => {
    injectScriptTag({ id: 5, title: 'Once' })
    const first = readPreloaded({})
    const second = readPreloaded({})
    expect(first).not.toBeNull()
    expect(second).toBeNull()
  })
})

// === readPreloaded cast pattern ===

describe('readPreloaded cast at call site', () => {
  interface PostStub {
    id: number
    title: string
    rendered_html: string
  }

  it('returns null when no data is present', () => {
    const result = readPreloaded({})
    expect(result).toBeNull()
  })

  it('allows casting to a concrete type via shape-guard', () => {
    injectScriptTag({ id: 1, title: 'Hello', rendered_html: '' })
    injectRootHtml('<div data-content><p>Body</p></div>')
    const raw = readPreloaded({
      html: { field: 'rendered_html', selector: '[data-content]' },
    })
    // Shape guard then cast to the expected type at the call site
    const post = raw !== null && 'id' in raw ? (raw as unknown as PostStub) : null
    expect(post).not.toBeNull()
    expect(post!.id).toBe(1)
    expect(post!.title).toBe('Hello')
    expect(post!.rendered_html).toBe('<p>Body</p>')
  })
})
