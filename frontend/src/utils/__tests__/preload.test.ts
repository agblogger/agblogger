import { describe, it, expect, beforeEach } from 'vitest'
import { readPreloadedMeta, readPreloadedHtml, readPreloadedHtmlMap } from '@/utils/preload'

describe('readPreloadedMeta', () => {
  beforeEach(() => {
    document.getElementById('__initial_data__')?.remove()
  })

  it('returns null when no script tag exists', () => {
    expect(readPreloadedMeta()).toBeNull()
  })

  it('reads and parses JSON from script tag', () => {
    const data = { id: 1, title: 'Hello' }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(data)
    document.body.appendChild(script)

    const result = readPreloadedMeta()
    expect(result).toEqual(data)
  })

  it('removes the script tag after reading', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedMeta()
    expect(document.getElementById('__initial_data__')).toBeNull()
  })

  it('returns null on second call', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedMeta()
    expect(readPreloadedMeta()).toBeNull()
  })

  it('returns null for invalid JSON', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = 'not valid json'
    document.body.appendChild(script)

    expect(readPreloadedMeta()).toBeNull()
  })
})

describe('readPreloadedHtml', () => {
  beforeEach(() => {
    const root = document.getElementById('root')
    if (root) root.innerHTML = ''
    else {
      const div = document.createElement('div')
      div.id = 'root'
      document.body.appendChild(div)
    }
  })

  it('returns null when selector matches nothing', () => {
    expect(readPreloadedHtml('[data-content]')).toBeNull()
  })

  it('extracts innerHTML from matched element inside root', () => {
    const root = document.getElementById('root')!
    root.innerHTML = '<article><h1>Title</h1><div data-content><p>Body</p></div></article>'

    const result = readPreloadedHtml('[data-content]')
    expect(result).toBe('<p>Body</p>')
  })

  it('does not match elements outside root', () => {
    document.body.insertAdjacentHTML('beforeend', '<div data-content><p>Outside</p></div>')

    const result = readPreloadedHtml('[data-content]')
    expect(result).toBeNull()

    document.body.querySelector('[data-content]')?.remove()
  })
})

describe('readPreloadedHtmlMap', () => {
  beforeEach(() => {
    const root = document.getElementById('root')
    if (root) root.innerHTML = ''
    else {
      const div = document.createElement('div')
      div.id = 'root'
      document.body.appendChild(div)
    }
  })

  it('returns empty map when no items match', () => {
    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(0)
  })

  it('extracts id-keyed map of content HTML', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><a>Post One</a><div data-excerpt><p>Excerpt one</p></div></li>' +
      '<li data-id="2"><a>Post Two</a><div data-excerpt><p>Excerpt two</p></div></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(2)
    expect(result.get('1')).toBe('<p>Excerpt one</p>')
    expect(result.get('2')).toBe('<p>Excerpt two</p>')
  })

  it('skips items missing content selector', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><a>Post One</a><div data-excerpt><p>Excerpt</p></div></li>' +
      '<li data-id="2"><a>Post Two</a></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(1)
    expect(result.get('1')).toBe('<p>Excerpt</p>')
  })

  it('skips items missing id attribute', () => {
    const root = document.getElementById('root')!
    root.innerHTML =
      '<ul>' +
      '<li data-id="1"><div data-excerpt><p>One</p></div></li>' +
      '<li><div data-excerpt><p>No id</p></div></li>' +
      '</ul>'

    const result = readPreloadedHtmlMap('[data-id]', 'data-id', '[data-excerpt]')
    expect(result.size).toBe(1)
  })
})
