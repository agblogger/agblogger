import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fc from 'fast-check'

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

  describe('console.warn for posts/-prefixed path with .md but not /index.md', () => {
    beforeEach(() => {
      vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('logs a warning when path is posts/hello.md (flat-file format not emitted by backend)', () => {
      filePathToSlug('posts/hello.md')
      expect(console.warn).toHaveBeenCalledOnce()
      expect(console.warn).toHaveBeenCalledWith(
        expect.stringContaining('posts/hello.md'),
      )
    })

    it('does NOT warn for a valid directory-backed path posts/hello/index.md', () => {
      filePathToSlug('posts/hello/index.md')
      expect(console.warn).not.toHaveBeenCalled()
    })

    it('does NOT warn for a bare slug', () => {
      filePathToSlug('my-post')
      expect(console.warn).not.toHaveBeenCalled()
    })
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

const slugChars = 'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')

const slugChunkArb = fc
  .array(fc.constantFrom(...slugChars), { minLength: 1, maxLength: 18 })
  .map((chars) => chars.join(''))

/** Generates a valid slug: one or more slug-chunks joined by '/' */
const slugArb = fc
  .array(slugChunkArb, { minLength: 1, maxLength: 4 })
  .map((parts) => parts.join('/'))

describe('filePathToSlug property tests', () => {
  it('idempotency: filePathToSlug(slug) === slug for bare slugs', () => {
    fc.assert(
      fc.property(slugArb, (slug) => {
        expect(filePathToSlug(slug)).toBe(slug)
      }),
      { numRuns: 300 },
    )
  })

  it('roundtrip: filePathToSlug("posts/" + s + "/index.md") === s for valid slugs', () => {
    fc.assert(
      fc.property(slugArb, (s) => {
        expect(filePathToSlug(`posts/${s}/index.md`)).toBe(s)
      }),
      { numRuns: 300 },
    )
  })
})

describe('postUrl property tests', () => {
  it('postUrl always starts with /post/ for any input', () => {
    fc.assert(
      fc.property(fc.string(), (input) => {
        expect(postUrl(input).startsWith('/post/')).toBe(true)
      }),
      { numRuns: 300 },
    )
  })
})
