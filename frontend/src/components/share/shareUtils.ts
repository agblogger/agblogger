const MASTODON_INSTANCE_KEY = 'agblogger:mastodon-instance'
const HOSTNAME_RE =
  /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$/

export const SHARE_PLATFORMS = [
  { id: 'bluesky', label: 'Share on Bluesky' },
  { id: 'mastodon', label: 'Share on Mastodon' },
  { id: 'x', label: 'Share on X' },
  { id: 'facebook', label: 'Share on Facebook' },
  { id: 'linkedin', label: 'Share on LinkedIn' },
  { id: 'reddit', label: 'Share on Reddit' },
] as const

export function getShareText(title: string, author: string | null, url: string): string {
  if (author !== null) {
    return `\u201c${title}\u201d by ${author} ${url}`
  }
  return `\u201c${title}\u201d ${url}`
}

/**
 * Build a platform-specific share URL. Returns '' when the platform
 * is unknown or when Mastodon is requested without an instance.
 * Callers should check for '' before opening the URL.
 */
export function getShareUrl(
  platform: string,
  text: string,
  url: string,
  title: string,
  mastodonInstance?: string,
): string {
  switch (platform) {
    case 'bluesky':
      return `https://bsky.app/intent/compose?text=${encodeURIComponent(text)}`
    case 'mastodon':
      if (mastodonInstance === undefined || mastodonInstance === '') return ''
      return `https://${mastodonInstance}/share?text=${encodeURIComponent(text)}`
    case 'x':
      return `https://x.com/intent/tweet?text=${encodeURIComponent(text)}`
    case 'facebook':
      return `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}&quote=${encodeURIComponent(title)}`
    case 'linkedin':
      return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`
    case 'reddit':
      return `https://www.reddit.com/submit?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}`
    case 'email':
      return `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(text)}`
    default:
      console.warn(`getShareUrl: unknown platform "${platform}"`)
      return ''
  }
}

export function canNativeShare(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function'
}

export async function nativeShare(title: string, text: string, url: string): Promise<void> {
  await navigator.share({ title, text, url })
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function getMastodonInstance(): string | null {
  try {
    return localStorage.getItem(MASTODON_INSTANCE_KEY)
  } catch {
    return null
  }
}

export function getValidMastodonInstance(): string | null {
  const instance = getMastodonInstance()
  if (instance === null) return null
  if (!isValidHostname(instance)) return null
  return stripProtocol(instance)
}

export function setMastodonInstance(instance: string): void {
  try {
    localStorage.setItem(MASTODON_INSTANCE_KEY, instance)
  } catch {
    // Storage unavailable — instance will not persist but share still works
  }
}

/**
 * Validate that a string looks like a hostname (e.g. mastodon.social).
 * Strips protocol prefixes before checking. Rejects values containing
 * path separators, query strings, fragments, or other URL-unsafe characters.
 */
export function isValidHostname(value: string): boolean {
  let hostname = value.replace(/^https?:\/\//, '')
  hostname = hostname.trim()
  if (hostname === '') return false
  return HOSTNAME_RE.test(hostname)
}

/**
 * Strip protocol prefixes (https://, http://) from a hostname string.
 */
export function stripProtocol(value: string): string {
  return value.replace(/^https?:\/\//, '').trim()
}
