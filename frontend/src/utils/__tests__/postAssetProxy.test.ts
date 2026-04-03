import { describe, expect, it, vi } from 'vitest'

import { shouldProxyPostRequest } from '../postAssetProxy'

describe('shouldProxyPostRequest', () => {
  it('proxies extensionless post assets when the backend content file exists', () => {
    const hasExistingAsset = vi.fn((filePath: string) => filePath === 'my-post/LICENSE')

    expect(shouldProxyPostRequest('/post/my-post/LICENSE', hasExistingAsset)).toBe(true)
    expect(hasExistingAsset).toHaveBeenCalledWith('my-post/LICENSE')
  })

  it('decodes encoded extensionless asset names before checking the filesystem', () => {
    const hasExistingAsset = vi.fn((filePath: string) => filePath === 'my-post/LICENSE copy')

    expect(shouldProxyPostRequest('/post/my-post/LICENSE%20copy', hasExistingAsset)).toBe(true)
    expect(hasExistingAsset).toHaveBeenCalledWith('my-post/LICENSE copy')
  })

  it('keeps nested post slugs in the SPA when no asset exists', () => {
    const hasExistingAsset = vi.fn(() => false)

    expect(shouldProxyPostRequest('/post/2026/recap', hasExistingAsset)).toBe(false)
  })

  it('still proxies dotted asset paths without a filesystem hit', () => {
    const hasExistingAsset = vi.fn(() => false)

    expect(shouldProxyPostRequest('/post/my-post/photo.png', hasExistingAsset)).toBe(true)
  })
})
