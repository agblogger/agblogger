import { useState } from 'react'

type PreloadKey = string | readonly unknown[] | null

function serializePreloadKey(key: PreloadKey): string | null {
  if (key === null) {
    return null
  }

  return typeof key === 'string' ? key : JSON.stringify(key)
}

export function useScopedPreloadedFallback<T>(
  key: PreloadKey,
  readFallback: () => T | null,
): T | null {
  const [preloaded] = useState(() => ({
    key: serializePreloadKey(key),
    data: readFallback(),
  }))

  const currentKey = serializePreloadKey(key)
  return preloaded.data !== null && currentKey !== null && preloaded.key === currentKey
    ? preloaded.data
    : null
}
