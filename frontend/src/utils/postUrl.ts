/**
 * Extract a URL-friendly slug from a file_path.
 *
 *   "posts/2026-03-23-my-post/index.md" → "2026-03-23-my-post"
 *   "posts/hello.md"                    → "hello"
 *   "2026-03-23-my-post"                → "2026-03-23-my-post" (idempotent)
 */
export function filePathToSlug(filePath: string): string {
  let slug = filePath
  if (slug.startsWith('posts/')) slug = slug.slice(6)
  if (slug.endsWith('/index.md')) slug = slug.slice(0, -9)
  else if (slug.endsWith('.md')) slug = slug.slice(0, -3)
  if (slug.endsWith('/')) slug = slug.slice(0, -1)
  return slug
}

/** Build the short post URL from a file_path: "/post/<slug>" */
export function postUrl(filePath: string): string {
  return `/post/${filePathToSlug(filePath)}`
}
