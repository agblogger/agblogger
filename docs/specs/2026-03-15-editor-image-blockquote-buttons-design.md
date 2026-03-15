# Editor Image and Blockquote Toolbar Buttons

Add Image and Blockquote buttons to the post editor's markdown toolbar, placed between Link and Code. The image button opens a file picker restricted to image types, uploads the file, and inserts an inline markdown image reference at the cursor. The blockquote button prefixes selected lines with `> `.

## Toolbar Layout

**Button order:** Bold, Italic, Heading, Link, **Image**, **Blockquote**, Code, Code Block

- Image icon: `ImagePlus` from Lucide
- Blockquote icon: `TextQuote` from Lucide

**Keyboard shortcuts:**

| Shortcut | Action |
|----------|--------|
| Cmd/Ctrl+Shift+I | Image |
| Cmd/Ctrl+Shift+. | Blockquote |

## Blockquote: `linePrefix` Extension to `WrapAction`

### Change to `WrapAction` interface

Add an optional `linePrefix` field:

```ts
interface WrapAction {
  before: string
  after: string
  placeholder: string
  block?: boolean
  linePrefix?: string  // new: prefix each line instead of wrapping
}
```

### Change to `wrapSelection`

When `linePrefix` is set:

1. Get the selected text (or placeholder if empty).
2. Split by newlines.
3. Prefix each line with the `linePrefix` value.
4. Join back together.
5. Still respect `block: true` (prepend `\n` if not at line start).

Cursor placement: select the full inserted text (all prefixed lines).

### Blockquote action definition

```ts
blockquote: { before: '', after: '', placeholder: 'quote text', linePrefix: '> ', block: true }
```

### Keyboard shortcut handling

Refactor `EditorPage.handleEditorKeyDown` to check `e.shiftKey` before dispatching. Currently the handler maps `e.key.toLowerCase()` through a `keyMap` without checking Shift, so Cmd+Shift+I would incorrectly trigger italic. The new logic:

- `(e.key === '>' || e.key === '.') && e.shiftKey` → `'blockquote'` (WrapAction, dispatched via `wrapSelection`; match both because Shift+Period produces `>` as `e.key` in most browsers)
- `e.key === 'I' && e.shiftKey` → call `triggerImageUpload()` directly (not a WrapAction)
- `e.key === 'i' && !e.shiftKey` → `'italic'` (existing behavior, now explicit)

The image shortcut bypasses the WrapAction system since it triggers a file dialog, not text insertion. Match the blockquote shortcut on `e.key === '>' || e.key === '.'` to handle cross-browser differences (Shift+Period reports `>` as `e.key` in most browsers).

**Blockquote toggle (removing `> ` prefixes) is out of scope.** The button always adds prefixes; removing them can be done manually.

## Image Upload: Shared `useFileUpload` Hook

### Hook location

`frontend/src/components/editor/useFileUpload.ts`

### Interface

```ts
useFileUpload(options: {
  filePath: string | null
  accept?: string        // MIME filter, e.g. "image/*"
  multiple?: boolean     // default true
  onStart?: () => void   // called before upload begins (e.g. clear prior errors)
  onSuccess?: (uploaded: string[]) => void  // filenames returned by uploadAssets
  onError?: (message: string) => void
})
```

Returns:

```ts
{
  triggerUpload: () => void   // opens the file dialog
  uploading: boolean          // true while upload in progress
  inputProps: object          // spread onto a hidden <input type="file">
}
```

### Internal behavior

- Manages a hidden `<input type="file">` ref.
- On file selection: calls `uploadAssets(filePath, files)`.
- Parses errors via `HTTPError` / `parseErrorDetail` (same pattern as current FileStrip).
- Resets the input value after upload so the same file can be re-selected.
- `triggerUpload` is a no-op when `filePath` is null.

### Consumer: FileStrip

Replaces its inline `handleUpload`, `fileInputRef`, and `<input>` with `useFileUpload({ filePath, multiple: true, onStart: () => setError(null), onSuccess: () => void loadAssets(), onError: setError })`. All other FileStrip functionality (delete, rename, insert, expand/collapse, thumbnails) is unchanged.

**Implementation note:** The final implementation also passes a `refreshToken` prop to `useFileUpload` to allow the file input to be reset between uploads so the same file can be re-selected after a successful upload.

### Consumer: EditorPage (image toolbar button)

EditorPage creates a hook instance:

```ts
useFileUpload({
  filePath: effectiveFilePath,
  accept: 'image/*',
  multiple: false,
  onSuccess: (filenames) => {
    for (const name of filenames) {
      handleInsertAtCursor(`![${name}](${name})`)
    }
  },
  onError: setError,
})
```

**Implementation note:** The final implementation includes an `imageUploadEnabled` guard so that `filePath` is conditionally passed: `filePath: imageUploadEnabled ? effectiveFilePath : null`. This ensures the hook is always called (preserving hook call order) while keeping the button inert when the post is not eligible for image uploads.

Passes `triggerImageUpload` and `imageUploading` down to MarkdownToolbar.

The hidden `<input type="file">` for image upload is rendered in EditorPage's JSX alongside the MarkdownToolbar (using the hook's `inputProps`).

### MarkdownToolbar changes

Two new optional props:

```ts
onImageClick?: () => void
imageUploading?: boolean
```

The image button calls `onImageClick` instead of going through the `WrapAction` system. While `imageUploading` is true, the button shows a loading state and is disabled.

### Post eligibility guard

The image button is disabled when:
- `effectiveFilePath` is null (unsaved new post) — tooltip: "Save post first to add images"
- `showFileStrip` is false (flat-file post, not directory-backed) — tooltip: "Only directory-backed posts support images"

## Error Handling

- **Upload failure**: `onError` callback surfaces the message. For the image button, this goes to EditorPage's error banner. For FileStrip, its inline error display.
- **Non-image file**: The `accept: "image/*"` attribute restricts the OS file dialog. The backend validates independently as a fallback.
- **Unsaved post**: Image button disabled with tooltip. No error state.

## What Stays Unchanged

- FileStrip's asset listing, delete, rename, insert, and thumbnail preview.
- Backend asset API (`POST /api/posts/{file_path}/assets` and related endpoints).
- `markdownAssetReferences.ts` rewrite logic.

## Testing

- **`wrapSelection` unit tests**: `linePrefix` mode with single line, multi-line, empty selection (placeholder), block mode newline prepend.
- **`useFileUpload` hook tests**: triggers file input, calls upload API, handles errors, respects `accept` filter.
- **MarkdownToolbar component tests**: image and blockquote buttons render, image button disabled when no `onImageClick`, blockquote inserts correct markdown.
- **FileStrip component tests**: verify upload still works after refactoring to shared hook.
