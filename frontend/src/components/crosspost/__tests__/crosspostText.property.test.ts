import { describe, expect, it } from 'vitest'
import fc from 'fast-check'

import { buildDefaultText, buildPostUrl } from '@/components/crosspost/crosspostText'

const slugChars = 'abcdefghijklmnopqrstuvwxyz0123456789-'.split('')

const slugChunkArb = fc
  .array(fc.constantFrom(...slugChars), { minLength: 1, maxLength: 18 })
  .map((chars) => chars.join(''))

const slugArb = fc
  .array(slugChunkArb, { minLength: 1, maxLength: 4 })
  .map((parts) => parts.join('/'))

const labelArb = fc
  .array(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789'.split('')), {
    minLength: 1,
    maxLength: 10,
  })
  .map((chars) => chars.join(''))

const pathVariantArb = fc.record({
  hasPostsPrefix: fc.boolean(),
  slug: slugArb,
  suffix: fc.constantFrom('', '/index.md'),
})

describe('cross-post text/url property tests', () => {
  it('buildPostUrl normalizes post paths to a stable public URL', () => {
    fc.assert(
      fc.property(pathVariantArb, ({ hasPostsPrefix, slug, suffix }) => {
        const inputPath = `${hasPostsPrefix ? 'posts/' : ''}${slug}${suffix}`
        const result = new URL(buildPostUrl(inputPath))

        expect(result.origin).toBe(window.location.origin)
        expect(result.pathname).toBe(`/post/${slug}`)
      }),
      { numRuns: 300 },
    )
  })

  it('buildDefaultText preserves content contract: excerpt/title + optional hashtags + URL', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 120 }),
        fc.string({ maxLength: 120 }),
        fc.array(labelArb, { maxLength: 12 }),
        pathVariantArb,
        (title, excerpt, labels, pathVariant) => {
          const path = `${pathVariant.hasPostsPrefix ? 'posts/' : ''}${pathVariant.slug}${pathVariant.suffix}`
          const actual = buildDefaultText(title, excerpt, labels, path)

          const bodyText = excerpt !== '' ? excerpt : title
          const hashtags = labels.slice(0, 5).map((label) => `#${label}`).join(' ')
          const url = buildPostUrl(path)

          const expectedParts = [bodyText]
          if (hashtags !== '') {
            expectedParts.push(hashtags)
          }
          expectedParts.push(url)

          expect(actual).toBe(expectedParts.join('\n\n'))
        },
      ),
      { numRuns: 300 },
    )
  })

  it('never includes more than five hashtags in the default text', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 120 }),
        fc.string({ maxLength: 120 }),
        fc.array(labelArb, { maxLength: 20 }),
        pathVariantArb,
        (title, excerpt, labels, pathVariant) => {
          const path = `${pathVariant.hasPostsPrefix ? 'posts/' : ''}${pathVariant.slug}${pathVariant.suffix}`
          const actual = buildDefaultText(title, excerpt, labels, path)

          const parts = actual.split('\n\n')
          const hashtagPart = labels.length > 0 ? (parts[1] ?? '') : ''
          const hashtagCount = (hashtagPart.match(/#[a-z0-9]+/g) ?? []).length

          expect(hashtagCount).toBe(Math.min(labels.length, 5))
        },
      ),
      { numRuns: 300 },
    )
  })
})
