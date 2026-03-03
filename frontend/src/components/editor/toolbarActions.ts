import type { WrapAction } from './wrapSelection'

export const actions: Record<string, WrapAction> = {
  bold: { before: '**', after: '**', placeholder: 'bold text' },
  italic: { before: '_', after: '_', placeholder: 'italic text' },
  heading: { before: '## ', after: '', placeholder: 'Heading', block: true },
  link: { before: '[', after: '](url)', placeholder: 'link text' },
  code: { before: '`', after: '`', placeholder: 'code' },
  codeblock: { before: '```\n', after: '\n```', placeholder: 'code', block: true },
}
