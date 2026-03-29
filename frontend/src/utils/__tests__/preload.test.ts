import { describe, it, expect, beforeEach } from 'vitest'
import { readPreloadedData } from '@/utils/preload'

describe('readPreloadedData', () => {
  beforeEach(() => {
    document.getElementById('__initial_data__')?.remove()
  })

  it('returns null when no script tag exists', () => {
    expect(readPreloadedData()).toBeNull()
  })

  it('reads and parses JSON from script tag', () => {
    const data = { posts: [{ title: 'Hello' }], total: 1 }
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = JSON.stringify(data)
    document.body.appendChild(script)

    const result = readPreloadedData()
    expect(result).toEqual(data)
  })

  it('removes the script tag after reading', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedData()
    expect(document.getElementById('__initial_data__')).toBeNull()
  })

  it('returns null on second call', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = '{"key":"value"}'
    document.body.appendChild(script)

    readPreloadedData()
    expect(readPreloadedData()).toBeNull()
  })

  it('returns null for invalid JSON', () => {
    const script = document.createElement('script')
    script.id = '__initial_data__'
    script.type = 'application/json'
    script.textContent = 'not valid json'
    document.body.appendChild(script)

    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(readPreloadedData()).toBeNull()
    consoleSpy.mockRestore()
  })
})
