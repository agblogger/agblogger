import { statSync } from 'node:fs'
import path from 'node:path'

import { shouldProxyPostRequest } from './src/utils/postAssetProxy'

const defaultContentDir = process.env['AGBLOGGER_CONTENT_DIR'] ?? path.resolve(__dirname, '../content')

function isExistingPostAsset(filePath: string, contentDir: string): boolean {
  const postsDir = path.resolve(contentDir, 'posts')
  const assetPath = path.resolve(postsDir, filePath)
  const relativePath = path.relative(postsDir, assetPath)

  if (relativePath === '' || relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
    return false
  }

  try {
    return statSync(assetPath).isFile() && path.extname(assetPath) !== '.md'
  } catch {
    return false
  }
}

export function shouldProxyPostRequestToBackend(
  requestUrl: string,
  contentDir: string = defaultContentDir,
): boolean {
  return shouldProxyPostRequest(requestUrl, (filePath) => isExistingPostAsset(filePath, contentDir))
}
