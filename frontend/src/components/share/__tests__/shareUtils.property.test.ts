import { describe, expect, it, vi } from 'vitest'
import fc from 'fast-check'

import {
  getShareText,
  getShareUrl,
  isValidHostname,
  stripProtocol,
} from '../shareUtils'

const alphaNumChars = 'abcdefghijklmnopqrstuvwxyz0123456789'.split('')
const alphaNumHyphenChars = 'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')

const hostnameLabelArb = fc.oneof(
  fc.constantFrom(...alphaNumChars),
  fc
    .tuple(
      fc.constantFrom(...alphaNumChars),
      fc.array(fc.constantFrom(...alphaNumHyphenChars), { minLength: 0, maxLength: 8 }),
      fc.constantFrom(...alphaNumChars),
    )
    .map(([first, middle, last]) => `${first}${middle.join('')}${last}`),
)

const hostnameArb = fc
  .array(hostnameLabelArb, { minLength: 2, maxLength: 5 })
  .map((labels) => labels.join('.'))

const slugChunkArb = fc
  .array(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')), {
    minLength: 1,
    maxLength: 12,
  })
  .map((chars) => chars.join(''))

const urlArb = fc
  .tuple(hostnameArb, fc.array(slugChunkArb, { minLength: 1, maxLength: 4 }))
  .map(([host, chunks]) => `https://${host}/${chunks.join('/')}`)

const textArb = fc.string({ maxLength: 80 })

function expectQueryParam(url: URL, key: string, expected: string): void {
  expect(url.searchParams.get(key)).toBe(expected)
}

describe('shareUtils property tests', () => {
  it('stripProtocol is idempotent and removes protocol prefixes', () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 120 }), (input) => {
        const once = stripProtocol(input)
        const twice = stripProtocol(once)

        expect(twice).toBe(once)
        expect(once.startsWith('http://')).toBe(false)
        expect(once.startsWith('https://')).toBe(false)
        expect(once).toBe(once.trim())
      }),
      { numRuns: 400 },
    )
  })

  it('accepts syntactically valid generated hostnames (with optional protocol)', () => {
    fc.assert(
      fc.property(hostnameArb, fc.boolean(), (hostname, useProtocol) => {
        const value = useProtocol ? `https://${hostname}` : hostname
        expect(isValidHostname(value)).toBe(true)
      }),
      { numRuns: 300 },
    )
  })

  it('rejects hostnames once path/query/fragment/userinfo/space segments are introduced', () => {
    const suffixArb = fc.constantFrom('/path', '?q=1', '#frag', '@attacker.net', ' with-space')

    fc.assert(
      fc.property(hostnameArb, suffixArb, (hostname, suffix) => {
        expect(isValidHostname(`${hostname}${suffix}`)).toBe(false)
      }),
      { numRuns: 300 },
    )
  })

  it('formats share text exactly for author and no-author variants', () => {
    fc.assert(
      fc.property(textArb, fc.option(textArb, { nil: null }), urlArb, (title, author, url) => {
        const actual = getShareText(title, author, url)
        const expected = author === null ? `“${title}” ${url}` : `“${title}” by ${author} ${url}`
        expect(actual).toBe(expected)
      }),
      { numRuns: 300 },
    )
  })

  it('encodes and maps query params correctly for social share platforms', () => {
    fc.assert(
      fc.property(textArb, urlArb, textArb, (text, url, title) => {
        const bluesky = new URL(getShareUrl('bluesky', text, url, title))
        expect(bluesky.origin).toBe('https://bsky.app')
        expect(bluesky.pathname).toBe('/intent/compose')
        expectQueryParam(bluesky, 'text', text)

        const x = new URL(getShareUrl('x', text, url, title))
        expect(x.origin).toBe('https://x.com')
        expect(x.pathname).toBe('/intent/tweet')
        expectQueryParam(x, 'text', text)

        const facebook = new URL(getShareUrl('facebook', text, url, title))
        expect(facebook.origin).toBe('https://www.facebook.com')
        expect(facebook.pathname).toBe('/sharer/sharer.php')
        expectQueryParam(facebook, 'u', url)

        const linkedIn = new URL(getShareUrl('linkedin', text, url, title))
        expect(linkedIn.origin).toBe('https://www.linkedin.com')
        expect(linkedIn.pathname).toBe('/sharing/share-offsite/')
        expectQueryParam(linkedIn, 'url', url)

        const reddit = new URL(getShareUrl('reddit', text, url, title))
        expect(reddit.origin).toBe('https://www.reddit.com')
        expect(reddit.pathname).toBe('/submit')
        expectQueryParam(reddit, 'url', url)
        expectQueryParam(reddit, 'title', title)
      }),
      { numRuns: 250 },
    )
  })

  it('builds mastodon URLs only when a non-empty instance is provided', () => {
    fc.assert(
      fc.property(textArb, urlArb, textArb, hostnameArb, (text, url, title, hostname) => {
        const withInstance = getShareUrl('mastodon', text, url, title, hostname)
        expect(withInstance).toBe(`https://${hostname}/share?text=${encodeURIComponent(text)}`)

        expect(getShareUrl('mastodon', text, url, title)).toBe('')
        expect(getShareUrl('mastodon', text, url, title, '')).toBe('')
      }),
      { numRuns: 250 },
    )
  })

  it('builds email share links with subject/body parameters', () => {
    fc.assert(
      fc.property(textArb, urlArb, textArb, (text, url, title) => {
        const email = new URL(getShareUrl('email', text, url, title))
        expect(email.protocol).toBe('mailto:')
        expect(email.pathname).toBe('')
        expectQueryParam(email, 'subject', title)
        expectQueryParam(email, 'body', text)
      }),
      { numRuns: 250 },
    )
  })

  it('returns empty URL and warns on unknown platforms', () => {
    fc.assert(
      fc.property(textArb, urlArb, textArb, fc.string({ minLength: 1, maxLength: 20 }), (text, url, title, suffix) => {
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
        const platform = `unknown-${suffix}`

        try {
          const result = getShareUrl(platform, text, url, title)
          expect(result).toBe('')
          expect(warnSpy).toHaveBeenCalledOnce()
        } finally {
          warnSpy.mockRestore()
        }
      }),
      { numRuns: 150 },
    )
  })
})
