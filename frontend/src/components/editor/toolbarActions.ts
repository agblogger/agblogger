import type { WrapAction } from './wrapSelection'

export const actions: Record<string, WrapAction> = {
  bold: { before: '**', after: '**', placeholder: 'bold text' },
  italic: { before: '_', after: '_', placeholder: 'italic text' },
  underline: { before: '[', after: ']{.underline}', placeholder: 'underlined text' },
  strikethrough: { before: '~~', after: '~~', placeholder: 'strikethrough text' },
  highlight: { before: '==', after: '==', placeholder: 'highlighted text' },
  heading: { before: '## ', after: '', placeholder: 'Heading', block: true },
  h3: { before: '### ', after: '', placeholder: 'Heading 3', block: true },
  h4: { before: '#### ', after: '', placeholder: 'Heading 4', block: true },
  bulletList: { before: '', after: '', placeholder: 'list item', linePrefix: '- ', block: true },
  orderedList: { before: '', after: '', placeholder: 'list item', linePrefix: '1. ', block: true },
  link: { before: '[', after: '](url)', placeholder: 'link text' },
  blockquote: { before: '', after: '', placeholder: 'quote text', linePrefix: '> ', block: true },
  code: { before: '`', after: '`', placeholder: 'code' },
  codeblock: { before: '```\n', after: '\n```', placeholder: 'code', block: true },
  youtube: {
    before: '<iframe src="https://www.youtube.com/embed/',
    after: '" allowfullscreen></iframe>',
    placeholder: 'VIDEO_ID',
    block: true,
  },
}
