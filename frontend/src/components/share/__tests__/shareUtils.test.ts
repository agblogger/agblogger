import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  getShareText,
  getShareUrl,
  canNativeShare,
  nativeShare,
  copyToClipboard,
  getMastodonInstance,
  setMastodonInstance,
  isValidHostname,
  SHARE_PLATFORMS,
} from '../shareUtils'

import { throwingLocalStorage } from './testUtils'

describe('getShareText', () => {
  it('formats text with title, author, and URL', () => {
    const result = getShareText('My Post', 'Alice', 'https://blog.example.com/post/hello')
    expect(result).toBe('\u201cMy Post\u201d by Alice https://blog.example.com/post/hello')
  })

  it('handles title with special characters', () => {
    const result = getShareText('What\'s "new" in 2026?', 'Bob', 'https://example.com/post/x')
    expect(result).toContain('What\'s "new" in 2026?')
    expect(result).toContain('by Bob')
  })

  it('handles null author', () => {
    const result = getShareText('My Post', null, 'https://example.com/post/x')
    expect(result).toBe('\u201cMy Post\u201d https://example.com/post/x')
  })
})

describe('getShareUrl', () => {
  const url = 'https://blog.example.com/post/hello'
  const text = '\u201cHello World\u201d by Alice https://blog.example.com/post/hello'
  const title = 'Hello World'

  it('returns Bluesky compose intent URL', () => {
    const result = getShareUrl('bluesky', text, url, title)
    expect(result).toBe(`https://bsky.app/intent/compose?text=${encodeURIComponent(text)}`)
  })

  it('returns X tweet intent URL', () => {
    const result = getShareUrl('x', text, url, title)
    expect(result).toBe(`https://x.com/intent/tweet?text=${encodeURIComponent(text)}`)
  })

  it('returns Facebook sharer URL', () => {
    const result = getShareUrl('facebook', text, url, title)
    expect(result).toBe(
      `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`,
    )
  })

  it('returns LinkedIn share URL', () => {
    const result = getShareUrl('linkedin', text, url, title)
    expect(result).toBe(
      `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
    )
  })

  it('returns Reddit submit URL', () => {
    const result = getShareUrl('reddit', text, url, title)
    expect(result).toBe(
      `https://www.reddit.com/submit?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}`,
    )
  })

  it('returns mailto URL for email', () => {
    const result = getShareUrl('email', text, url, title)
    expect(result).toBe(
      `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(text)}`,
    )
  })

  it('returns Mastodon share URL with instance', () => {
    const result = getShareUrl('mastodon', text, url, title, 'mastodon.social')
    expect(result).toBe(
      `https://mastodon.social/share?text=${encodeURIComponent(text)}`,
    )
  })

  it('returns empty string for mastodon without instance', () => {
    const result = getShareUrl('mastodon', text, url, title)
    expect(result).toBe('')
  })

  // Issue #8: unknown platform should warn and return empty string
  it('returns empty string for unknown platform', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const result = getShareUrl('tiktok', text, url, title)
    expect(result).toBe('')
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('tiktok'))
    warnSpy.mockRestore()
  })
})

describe('canNativeShare', () => {
  afterEach(() => {
    // Restore navigator.share to undefined (jsdom default)
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
  })

  it('returns true when navigator.share is available', () => {
    Object.defineProperty(navigator, 'share', {
      value: vi.fn(),
      writable: true,
      configurable: true,
    })
    expect(canNativeShare()).toBe(true)
  })

  it('returns false when navigator.share is unavailable', () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      writable: true,
      configurable: true,
    })
    expect(canNativeShare()).toBe(false)
  })
})

describe('nativeShare', () => {
  it('calls navigator.share with correct data', async () => {
    const mockShare = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'share', {
      value: mockShare,
      writable: true,
      configurable: true,
    })

    await nativeShare('Title', 'Text', 'https://example.com')
    expect(mockShare).toHaveBeenCalledWith({
      title: 'Title',
      text: 'Text',
      url: 'https://example.com',
    })
  })
})

describe('copyToClipboard', () => {
  it('returns true on success', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
      writable: true,
      configurable: true,
    })
    const result = await copyToClipboard('text')
    expect(result).toBe(true)
  })

  it('returns false on failure', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('fail')) },
      writable: true,
      configurable: true,
    })
    const result = await copyToClipboard('text')
    expect(result).toBe(false)
  })
})

describe('mastodon instance localStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns null when no instance saved', () => {
    expect(getMastodonInstance()).toBeNull()
  })

  it('saves and retrieves instance', () => {
    setMastodonInstance('mastodon.social')
    expect(getMastodonInstance()).toBe('mastodon.social')
  })

  // Issue #4: localStorage access should be protected
  it('returns null when localStorage throws SecurityError', () => {
    const original = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      value: throwingLocalStorage,
      writable: true,
    })
    expect(getMastodonInstance()).toBeNull()
    Object.defineProperty(window, 'localStorage', {
      value: original,
      writable: true,
    })
  })

  it('does not throw when setMastodonInstance encounters SecurityError', () => {
    const original = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      value: throwingLocalStorage,
      writable: true,
    })
    expect(() => setMastodonInstance('test.social')).not.toThrow()
    Object.defineProperty(window, 'localStorage', {
      value: original,
      writable: true,
    })
  })
})

// Issue #1: hostname validation
describe('isValidHostname', () => {
  it('accepts valid hostnames', () => {
    expect(isValidHostname('mastodon.social')).toBe(true)
    expect(isValidHostname('hachyderm.io')).toBe(true)
    expect(isValidHostname('masto.host')).toBe(true)
    expect(isValidHostname('social.example.co.uk')).toBe(true)
  })

  it('rejects hostnames with path separators', () => {
    expect(isValidHostname('evil.com/phishing')).toBe(false)
  })

  it('rejects hostnames with query strings', () => {
    expect(isValidHostname('evil.com?x=1')).toBe(false)
  })

  it('rejects hostnames with hash fragments', () => {
    expect(isValidHostname('evil.com#fragment')).toBe(false)
  })

  it('rejects hostnames with @ signs', () => {
    expect(isValidHostname('user@evil.com')).toBe(false)
  })

  it('rejects hostnames with spaces', () => {
    expect(isValidHostname('mastodon social')).toBe(false)
  })

  it('rejects empty strings', () => {
    expect(isValidHostname('')).toBe(false)
  })

  it('rejects single-label hostnames (no dot)', () => {
    expect(isValidHostname('localhost')).toBe(false)
  })

  it('strips protocol prefixes before validating', () => {
    expect(isValidHostname('https://mastodon.social')).toBe(true)
    expect(isValidHostname('http://mastodon.social')).toBe(true)
  })
})

// Issue #2: shared SHARE_PLATFORMS constant
describe('SHARE_PLATFORMS', () => {
  it('contains all expected platforms', () => {
    const ids = SHARE_PLATFORMS.map((p) => p.id)
    expect(ids).toContain('bluesky')
    expect(ids).toContain('mastodon')
    expect(ids).toContain('x')
    expect(ids).toContain('facebook')
    expect(ids).toContain('linkedin')
    expect(ids).toContain('reddit')
  })

  it('has labels for all platforms', () => {
    for (const platform of SHARE_PLATFORMS) {
      expect(platform.label).toBeTruthy()
    }
  })
})
