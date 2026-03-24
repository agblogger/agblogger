import { describe, expect, it } from 'vitest'

import { filePathToSlug, postUrl } from '../postUrl'

describe('filePathToSlug', () => {
  it('strips posts/ prefix and /index.md suffix from directory-backed post', () => {
    expect(filePathToSlug('posts/2026-03-23-my-post/index.md')).toBe('2026-03-23-my-post')
  })

  it('returns bare slug unchanged (idempotent)', () => {
    expect(filePathToSlug('my-post')).toBe('my-post')
  })

  it('strips trailing slash', () => {
    expect(filePathToSlug('posts/my-post/')).toBe('my-post')
  })

  it('strips posts/ prefix when no extension is present', () => {
    expect(filePathToSlug('posts/hello')).toBe('hello')
  })

  it('preserves nested path segments for nested directory post', () => {
    expect(filePathToSlug('posts/2026/recap/index.md')).toBe('2026/recap')
  })

  it('returns bare slug with date prefix unchanged', () => {
    expect(filePathToSlug('2026-03-23-my-post')).toBe('2026-03-23-my-post')
  })
})

describe('postUrl', () => {
  it('produces correct URL for directory-backed post', () => {
    expect(postUrl('posts/my-post/index.md')).toBe('/post/my-post')
  })

  it('produces correct URL for bare slug', () => {
    expect(postUrl('my-post')).toBe('/post/my-post')
  })
})
