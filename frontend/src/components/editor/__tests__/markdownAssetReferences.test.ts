import { describe, it, expect } from 'vitest'

import { rewriteMarkdownAssetReferences } from '../markdownAssetReferences'

describe('rewriteMarkdownAssetReferences', () => {
  it('rewrites a basic image reference', () => {
    const result = rewriteMarkdownAssetReferences('![alt](photo.png)', 'photo.png', 'new.png')
    expect(result).toBe('![alt](new.png)')
  })

  it('rewrites a basic link reference', () => {
    const result = rewriteMarkdownAssetReferences('[text](file.pdf)', 'file.pdf', 'new.pdf')
    expect(result).toBe('[text](new.pdf)')
  })

  it('rewrites an angle-bracket target', () => {
    const result = rewriteMarkdownAssetReferences('![alt](<photo.png>)', 'photo.png', 'new.png')
    expect(result).toBe('![alt](<new.png>)')
  })

  it('rewrites a relative prefix target', () => {
    const result = rewriteMarkdownAssetReferences('![alt](./photo.png)', 'photo.png', 'new.png')
    expect(result).toBe('![alt](./new.png)')
  })

  it('does not rewrite when filename does not match', () => {
    const md = '![alt](other.png)'
    const result = rewriteMarkdownAssetReferences(md, 'photo.png', 'new.png')
    expect(result).toBe(md)
  })

  it('does not rewrite plain text occurrences of the filename', () => {
    const md = 'photo.png appears in text'
    const result = rewriteMarkdownAssetReferences(md, 'photo.png', 'new.png')
    expect(result).toBe(md)
  })

  it('rewrites multiple references in a single pass', () => {
    const md = '![first](photo.png)\n[second](photo.png)'
    const result = rewriteMarkdownAssetReferences(md, 'photo.png', 'new.png')
    expect(result).toBe('![first](new.png)\n[second](new.png)')
  })

  it('does not rewrite substring filenames', () => {
    const md = '![alt](ba.png)\n![other](a.png)'
    const result = rewriteMarkdownAssetReferences(md, 'a.png', 'z.png')
    expect(result).toBe('![alt](ba.png)\n![other](z.png)')
  })
})
