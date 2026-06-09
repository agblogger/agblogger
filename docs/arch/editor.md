# Markdown Editor Architecture

`MarkdownEditor` (`frontend/src/components/editor/MarkdownEditor.tsx`) is the
single reusable editing surface used by both post authoring (`EditorPage`) and
page authoring (`PagesSection`).

## Boundary

The component is controlled via `value`/`onChange`: it performs all editing
interactions (typing, toolbar formatting, asset-reference rewrites on rename)
and reports each new markdown string upward. It does not store the markdown
itself, so hosts retain it for autosave, save payloads, and dirty tracking.

**Component owns:** the toolbar (formatting actions + save + fullscreen toggle),
textarea, live preview, scroll sync, keyboard shortcuts (formatting +
Cmd/Ctrl+S), mobile edit/preview tabs, the fullscreen overlay, and — when
`enableAssets` is set — file attachment management (upload/delete/rename) plus
toolbar image upload.

**Host owns:** metadata fields, autosave, the `onSave` handler and error
banners.

## Pieces

- `MarkdownEditor.tsx` — orchestrator and layout.
- `MarkdownToolbar.tsx` — formatting, image, save, and fullscreen buttons.
- `useMarkdownPreview` (`frontend/src/hooks/`) — debounced backend
  `render/preview` call plus KaTeX hydration and code-block enhancement; the
  single source of preview behavior.
- Supporting units: `wrapSelection`/`toolbarActions` (formatting transforms),
  `useScrollSync` (editor↔preview alignment), `useFileUpload` + `FileStrip` +
  `markdownAssetReferences` (assets).

## Usage

- Posts: `enableAssets` on, `filePath` is the post path (null until first save,
  which disables image upload with a reason). The post page also keeps a header
  Save button wired to the same handler.
- Pages: text-only (no `enableAssets`); saved via the toolbar save button.

Preview HTML is rendered and sanitized server-side; the component mounts it via
`dangerouslySetInnerHTML`.
