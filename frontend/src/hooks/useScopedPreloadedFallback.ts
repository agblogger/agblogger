import { useState } from 'react'

type PreloadKey = string | readonly unknown[] | null

function serializePreloadKey(key: PreloadKey): string | null {
  if (key === null) {
    return null
  }

  return typeof key === 'string' ? key : JSON.stringify(key)
}

/**
 * Captures preloaded fallback data once per mount via a lazy useState initializer.
 * Returns the data only while the serialized SWR key still matches, ensuring stale
 * preloaded data is discarded when the cache key changes (e.g., after login).
 * Returns null when no preload data exists or the key has diverged.
 */
export function useScopedPreloadedFallback<T>(
  key: PreloadKey,
  readFallback: () => T | null,
): T | null {
  const [preloaded] = useState(() => ({
    key: serializePreloadKey(key),
    data: readFallback(),
  }))

  return preloaded.data !== null && preloaded.key === serializePreloadKey(key)
    ? preloaded.data
    : null
}
