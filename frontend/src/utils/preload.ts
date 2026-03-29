/** Read and remove the server-injected preload data. One-time read. */
export function readPreloadedData<T = unknown>(): T | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  el.remove()
  try {
    return JSON.parse(el.textContent ?? '') as T
  } catch {
    return null
  }
}
