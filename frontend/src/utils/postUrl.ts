/**
 * Extract a URL-friendly slug from a file_path.
 *
 * The backend always emits one of these canonical formats:
 *   "posts/my-post/index.md" → "my-post"
 *   "my-post"                → "my-post" (idempotent, bare slug)
 *
 * Defensive edge cases handled (not emitted by backend, logged with a warning):
 *   "posts/my-post.md" — flat-file format; backend raises ValueError for this
 *
 * Trailing slashes are stripped defensively:
 *   "posts/my-post/" → "my-post"
 */
export function filePathToSlug(filePath: string): string {
  let slug = filePath
  if (slug.startsWith('posts/')) {
    slug = slug.slice(6)
    // A posts/-prefixed path ending in .md but not /index.md is a flat-file
    // format that the backend rejects with ValueError. Warn to aid debugging.
    if (slug.endsWith('.md') && !slug.endsWith('/index.md')) {
      console.warn(
        `filePathToSlug: unexpected flat-file path "posts/${slug}" — ` +
          `the backend never emits this format and raises ValueError for it.`,
      )
    }
  }
  if (slug.endsWith('/index.md')) slug = slug.slice(0, -9)
  if (slug.endsWith('/')) slug = slug.slice(0, -1)
  return slug
}

/** Build the short post URL from a file_path: "/post/<slug>" */
export function postUrl(filePath: string): string {
  return `/post/${filePathToSlug(filePath)}`
}
