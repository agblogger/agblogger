/**
 * Map over `items` with `worker`, running at most `limit` invocations at a
 * time. Results preserve input order.
 *
 * Use this instead of `Promise.all(items.map(worker))` when `items` can grow
 * unboundedly (e.g. one request per page of a paginated resource): a plain
 * `Promise.all` would fire every request simultaneously, which can overwhelm
 * the backend for large inputs.
 */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = []
  // Wrapper objects are always defined, so a worker can tell "no work left"
  // (cursor past the end) apart from a genuine `undefined` item value.
  const queue = items.map((item, index) => ({ item, index }))
  let cursor = 0

  async function runWorker(): Promise<void> {
    while (cursor < queue.length) {
      const entry = queue[cursor]
      cursor += 1
      // The queue is densely populated; this guard only narrows the indexed
      // access from `... | undefined` to the wrapper type.
      if (entry === undefined) continue
      results[entry.index] = await worker(entry.item, entry.index)
    }
  }

  const workerCount = Math.min(Math.max(limit, 1), queue.length)
  await Promise.all(Array.from({ length: workerCount }, () => runWorker()))
  return results
}
