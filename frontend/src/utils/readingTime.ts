export function readingTime(wordCount: number): string {
  const minutes = Math.max(1, Math.ceil(wordCount / 200))
  return `${minutes} min read · ${wordCount.toLocaleString()} words`
}
