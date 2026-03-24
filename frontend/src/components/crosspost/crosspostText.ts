import { filePathToSlug } from '@/utils/postUrl'

export function buildPostUrl(postPath: string): string {
  return `${window.location.origin}/post/${filePathToSlug(postPath)}`
}

export function buildDefaultText(
  postTitle: string,
  postExcerpt: string,
  postLabels: string[],
  postPath: string,
): string {
  const excerpt = postExcerpt || postTitle
  const hashtags = postLabels
    .slice(0, 5)
    .map((label) => `#${label}`)
    .join(' ')
  const url = buildPostUrl(postPath)

  const parts = [excerpt]
  if (hashtags) {
    parts.push(hashtags)
  }
  parts.push(url)

  return parts.join('\n\n')
}
