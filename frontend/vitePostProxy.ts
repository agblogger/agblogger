import { statSync } from 'node:fs'
import path from 'node:path'

import { shouldProxyPostRequest } from './src/utils/postAssetProxy'

const defaultContentDir = process.env['AGBLOGGER_CONTENT_DIR'] ?? path.resolve(__dirname, '../content')

function resolvePathInsidePosts(contentDir: string, ...segments: string[]): string | null {
  const postsDir = path.resolve(contentDir, 'posts')
  const resolvedPath = path.resolve(postsDir, ...segments)
  const relativePath = path.relative(postsDir, resolvedPath)

  if (relativePath === '' || relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
    return null
  }

  return resolvedPath
}

function isExistingPostAsset(filePath: string, contentDir: string): boolean {
  const assetPath = resolvePathInsidePosts(contentDir, filePath)
  if (assetPath === null) {
    return false
  }

  try {
    return statSync(assetPath).isFile() && path.extname(assetPath) !== '.md'
  } catch {
    return false
  }
}

function isExistingCanonicalPost(filePath: string, contentDir: string): boolean {
  const postPath = resolvePathInsidePosts(contentDir, filePath, 'index.md')
  if (postPath === null) {
    return false
  }

  try {
    return statSync(postPath).isFile()
  } catch {
    return false
  }
}

export function shouldProxyPostRequestToBackend(
  requestUrl: string,
  contentDir: string = defaultContentDir,
): boolean {
  return shouldProxyPostRequest(
    requestUrl,
    (filePath) => isExistingPostAsset(filePath, contentDir),
    (filePath) => isExistingCanonicalPost(filePath, contentDir),
  )
}
