const INLINE_ASSET_REFERENCE_PATTERN = /(!?\[[^\]]*])\(\s*(<[^>\n]+>|[^)\s]+)([^)]*)\)/g

function rewriteTarget(target: string, oldName: string, newName: string): string {
  if (target === oldName) {
    return newName
  }
  if (target === `./${oldName}`) {
    return `./${newName}`
  }
  return target
}

export function rewriteMarkdownAssetReferences(
  markdown: string,
  oldName: string,
  newName: string,
): string {
  return markdown.replace(
    INLINE_ASSET_REFERENCE_PATTERN,
    (match, label: string, rawTarget: string, suffix: string) => {
      const target = rawTarget.startsWith('<') && rawTarget.endsWith('>')
        ? rawTarget.slice(1, -1)
        : rawTarget
      const nextTarget = rewriteTarget(target, oldName, newName)
      if (nextTarget === target) {
        return match
      }
      const rewrittenTarget = rawTarget.startsWith('<') && rawTarget.endsWith('>')
        ? `<${nextTarget}>`
        : nextTarget
      return `${label}(${rewrittenTarget}${suffix})`
    },
  )
}
