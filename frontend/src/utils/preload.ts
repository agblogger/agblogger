/** Read and remove the server-injected preload data. One-time read. */
export function readPreloadedData<T>(_type?: abstract new (...args: never[]) => T): T | null {
  const el = document.getElementById('__initial_data__')
  if (el === null) return null

  const raw = el.textContent
  el.remove()
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}
