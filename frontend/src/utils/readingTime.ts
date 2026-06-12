function readingMinutes(wordCount: number): number {
  return Math.max(1, Math.ceil(wordCount / 200))
}

export function readingTimeShort(wordCount: number): string {
  return `${readingMinutes(wordCount)} min read`
}

export function readingTime(wordCount: number): string {
  return `${readingTimeShort(wordCount)} · ${wordCount.toLocaleString()} words`
}
