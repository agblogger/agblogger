import { useState } from 'react'

import {
  copyToClipboard,
  getValidMastodonInstance,
  getShareText,
  getShareUrl,
  nativeShare,
} from './shareUtils'

interface ShareHandlers {
  shareText: string
  copied: boolean
  copyFailed: boolean
  showMastodonPrompt: boolean
  setShowMastodonPrompt: (show: boolean) => void
  handlePlatformClick: (platformId: string) => void
  handleEmailClick: () => void
  handleCopy: () => Promise<void>
  handleNativeShare: () => Promise<void>
}

export function useShareHandlers(
  title: string,
  author: string | null,
  url: string,
  onAction?: () => void,
): ShareHandlers {
  const [showMastodonPrompt, setShowMastodonPrompt] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)

  const shareText = getShareText(title, author, url)

  function handlePlatformClick(platformId: string) {
    if (platformId === 'mastodon') {
      const instance = getValidMastodonInstance()
      if (instance !== null) {
        const shareUrl = getShareUrl('mastodon', shareText, url, title, instance)
        window.open(shareUrl, '_blank', 'noopener,noreferrer')
        onAction?.()
      } else {
        setShowMastodonPrompt(true)
      }
      return
    }
    const shareUrl = getShareUrl(platformId, shareText, url, title)
    if (shareUrl !== '') {
      window.open(shareUrl, '_blank', 'noopener,noreferrer')
      onAction?.()
    }
  }

  function handleEmailClick() {
    const emailUrl = getShareUrl('email', shareText, url, title)
    window.open(emailUrl, '_self')
    onAction?.()
  }

  async function handleCopy() {
    const success = await copyToClipboard(url)
    if (success) {
      setCopied(true)
      setTimeout(() => {
        setCopied(false)
        onAction?.()
      }, 3000)
    } else {
      setCopyFailed(true)
      setTimeout(() => {
        setCopyFailed(false)
      }, 3000)
    }
  }

  async function handleNativeShare() {
    try {
      await nativeShare(title, shareText, url)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return
      }
      throw err
    }
  }

  return {
    shareText,
    copied,
    copyFailed,
    showMastodonPrompt,
    setShowMastodonPrompt,
    handlePlatformClick,
    handleEmailClick,
    handleCopy,
    handleNativeShare,
  }
}
