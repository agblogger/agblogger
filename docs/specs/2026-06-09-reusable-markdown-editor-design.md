# Reusable Markdown Editor Component — Design

## Problem

The rich markdown editing experience (formatting toolbar, keyboard shortcuts,
debounced live preview, editor↔preview scroll sync, mobile edit/preview tabs,
and asset management) lives only in post editing (`EditorPage.tsx`, ~659 lines).
Page editing (`PagesSection.tsx`, in the admin panel) uses a stripped-down inline
editor: a plain textarea plus a separately re-implemented debounced preview
(`PagePreview`). The debounced `render/preview` call is therefore duplicated, and
pages lack the toolbar, shortcuts, scroll sync, and code-block enhancement that
posts have.

## Goal

Extract a single, general, reusable `MarkdownEditor` component that owns the
entire editing surface, and use it for both post editing and page editing. The
component must be principled: hosts that are not posts (i.e. pages) get the full
editing experience for free, without inheriting post-specific concerns.

## Scope

- **In scope:** a new `MarkdownEditor` component; an extracted
  `useMarkdownPreview` hook; an extended `MarkdownToolbar` (adds save +
  fullscreen toggle); integration into `EditorPage` and `PagesSection`; deletion
  of the duplicated `PagePreview`.
- **Out of scope:** autosave for pages (none exists today; autosave remains a
  host concern for posts); backend asset storage for pages (pages stay
  text-only); any change to the backend rendering/sanitization pipeline.

## Ownership Boundary

**Editor component owns:** the textarea, the toolbar (formatting actions + save +
fullscreen toggle), the live preview, scroll sync, keyboard shortcuts (formatting
+ Cmd/Ctrl+S to save), mobile edit/preview tabs, the fullscreen overlay, and
**all asset handling** (upload, delete, rename including reference rewriting),
gated behind an opt-in prop.

**Host owns:** metadata fields (title, subtitle, labels, draft toggle, author,
timestamps, cross-post), autosave drafts, the `onSave` handler and its error
banners, and the markdown `value`/`onChange` state.

Markdown text uses the React controlled-component pattern (`value` + `onChange`),
consistent with the existing `MarkdownToolbar`. The component performs all
editing interactions (typing, toolbar formatting, asset-reference rewrite on
rename) and reports each new string upward via `onChange`; it does not hold the
markdown in internal state. The host needs the markdown for autosave snapshots,
the save payload, and dirty tracking, so the text is lifted to the host.

## Component API

`frontend/src/components/editor/MarkdownEditor.tsx`:

```ts
interface MarkdownEditorProps {
  value: string
  onChange: (value: string) => void
  disabled?: boolean

  // Save: when onSave is provided, the toolbar shows a save icon and
  // Cmd/Ctrl+S triggers it. canSave gates it (e.g. title required for posts).
  onSave?: () => void
  saving?: boolean
  canSave?: boolean            // default true

  // Asset/preview context:
  filePath?: string | null     // preview asset resolution + asset operations
  enableAssets?: boolean       // posts: FileStrip + toolbar image button; pages: omit
  assetDisabledReason?: string // shown when enableAssets but not yet saved (filePath null)

  editorHeight?: string        // default '80vh' inline; ignored in fullscreen
}
```

## Internal Structure

- **`MarkdownEditor.tsx`** — orchestrator. Owns `textareaRef`/`previewRef`,
  fullscreen state and mobile-tab state, wires `useScrollSync`, handles keyboard
  shortcuts (formatting via existing handler + Cmd/Ctrl+S → `onSave`), and lays
  out the toolbar, textarea, preview, and (when `enableAssets`) the FileStrip +
  hidden image input. Inserts uploaded-image markdown at the textarea cursor.
- **`MarkdownToolbar.tsx`** (extended) — adds a **save** button (visible when
  `onSave` is provided; disabled when `!canSave`, `saving`, or `disabled`) and a
  **fullscreen-toggle** button, alongside the existing format/image buttons.
- **`useMarkdownPreview(value, filePath)`** (new) — the debounced
  `render/preview` call with a request-id race guard, returning `{ html, error }`.
  Applies KaTeX hydration (`useRenderedHtml`) and code-block enhancement
  (`useCodeBlockEnhance`) internally. Replaces both the preview `useEffect` in
  `EditorPage` and the logic in `PagePreview`. Pages gain code-block enhancement
  as a parity win.
- **Reused unchanged:** `toolbarActions`, `wrapSelection`, `useScrollSync`,
  `useFileUpload`, `FileStrip`, `markdownAssetReferences`.

## Data Flow

- `value`/`onChange` are controlled by the host; preview derives from `value`
  inside the component.
- **Save:** the toolbar save icon and Cmd/Ctrl+S both call `onSave`; the host
  performs the API write and renders any error banners. `saving` disables
  controls; `canSave` gates the save affordance.
- **Fullscreen:** internal component state rendered as a fixed overlay; **Esc
  exits**. Covers toolbar + editor + preview only (metadata and FileStrip are
  not shown in fullscreen).
- **Assets:** upload/delete/rename are handled entirely inside the component.
  Rename rewrites references in the body via `markdownAssetReferences` and emits
  the new text through `onChange` like any other edit. The host does not
  participate in asset operations. FileStrip refresh after a toolbar image upload
  is coordinated internally (no host callback).
- Preview HTML is sanitized server-side; the `dangerouslySetInnerHTML` usage
  keeps the existing nosemgrep justification.

## Host Integration

- **`EditorPage`** keeps the metadata box, the header **Save** button (wired to
  the same `handleSave`), autosave, and cross-post. It replaces its toolbar +
  scroll-sync gutter UI + editor/preview grid + FileStrip with a single
  `<MarkdownEditor value={body} onChange={setBody} onSave={handleSave}
  saving={saving} canSave={title.trim().length > 0} filePath={effectiveFilePath}
  enableAssets assetDisabledReason={…} />`. Both the header Save and the toolbar
  save trigger `handleSave`. This removes roughly 250 lines from `EditorPage`.
- **`PagesSection`** replaces the textarea + `PagePreview` split with
  `<MarkdownEditor value={editContent} onChange={setEditContent}
  onSave={handleSavePage} saving={savingPage} canSave={editTitle.trim().length > 0} />`
  (no assets). The page title input stays above the editor. `PagePreview` is
  deleted.

## Error Handling

- Preview render failures show an in-pane "Preview unavailable" message (existing
  pattern) and are logged client-side; no server-facing paths change.
- Save and asset errors stay with the host / `useFileUpload` respectively, as
  today.

## Testing (TDD)

- **Unit:** `useMarkdownPreview` (debounce, request-id race guard, error state);
  new toolbar buttons (save disabled/saving states, fullscreen toggle). Existing
  `wrapSelection` and `useScrollSync` tests remain.
- **Component:** `MarkdownEditor` — typing updates via `onChange`, save icon →
  `onSave`, Cmd/Ctrl+S → `onSave`, fullscreen enter/Esc, mobile tabs, assets
  absent when `enableAssets` is omitted.
- **Integration:** update `EditorPage.test.tsx` for the new structure; cover page
  save through the editor in `PagesSection`.
- **E2E:** Playwright for post and page editing plus fullscreen; remove leftover
  screenshots afterward.
- Single test completion time < 1s; coverage targets per repository gate.

## Docs

Update the Editing Architecture section of `docs/arch/frontend.md` to very briefly mention
the shared `MarkdownEditor` used by both post and page editing. Create a new `docs/arch/editor.md` to describe the editor component architecture in more depth. Keep arch docs concise and match existing style.
