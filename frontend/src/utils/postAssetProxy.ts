const POST_ROUTE_PREFIX = '/post/'

function decodePostFilePath(filePath: string): string | null {
  try {
    return decodeURIComponent(filePath)
  } catch {
    return null
  }
}

export function looksLikePostAssetPath(filePath: string): boolean {
  if (!filePath.includes('/')) {
    return false
  }

  const leaf = filePath.replace(/\/+$/, '').split('/').at(-1) ?? ''
  if (leaf === '' || leaf === 'index.md') {
    return false
  }

  const leafExtension = leaf.includes('.') ? `.${leaf.split('.').at(-1) ?? ''}` : ''
  return leafExtension !== '' && leafExtension !== '.md'
}

export function shouldProxyPostRequest(
  requestUrl: string,
  hasExistingAsset: (filePath: string) => boolean,
  hasCanonicalPost: (filePath: string) => boolean = () => false,
): boolean {
  const pathname = new URL(requestUrl, 'http://localhost').pathname
  if (!pathname.startsWith(POST_ROUTE_PREFIX)) {
    return false
  }

  const encodedFilePath = pathname.slice(POST_ROUTE_PREFIX.length)
  const filePath = decodePostFilePath(encodedFilePath)
  if (filePath === null) {
    return false
  }

  if (filePath === '' || filePath.split('/').includes('..')) {
    return false
  }

  if (hasExistingAsset(filePath)) {
    return true
  }

  if (hasCanonicalPost(filePath)) {
    return false
  }

  return looksLikePostAssetPath(filePath)
}
