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

Add a case in `EditorPage.handleEditorKeyDown` for Shift+`.` (period) mapping to the `'blockquote'` action.

## Image Upload: Shared `useFileUpload` Hook

### Hook location

`frontend/src/components/editor/useFileUpload.ts`

### Interface

```ts
useFileUpload(options: {
  filePath: string | null
  accept?: string        // MIME filter, e.g. "image/*"
  multiple?: boolean     // default true
  onSuccess?: (uploaded: AssetInfo[]) => void
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

Replaces its inline `handleUpload`, `fileInputRef`, and `<input>` with `useFileUpload({ filePath, multiple: true, onSuccess: reloadAssets, onError: setError })`. All other FileStrip functionality (delete, rename, insert, expand/collapse, thumbnails) is unchanged.

### Consumer: EditorPage (image toolbar button)

EditorPage creates a hook instance:

```ts
useFileUpload({
  filePath: effectiveFilePath,
  accept: 'image/*',
  multiple: false,
  onSuccess: (assets) => {
    // Insert ![filename](filename) at cursor for each uploaded image
    for (const asset of assets) {
      handleInsertAtCursor(`![${asset.name}](${asset.name})`)
    }
  },
  onError: setError,
})
```

Passes `triggerImageUpload` and `imageUploading` down to MarkdownToolbar.

### MarkdownToolbar changes

Two new optional props:

```ts
onImageClick?: () => void
imageUploading?: boolean
```

The image button calls `onImageClick` instead of going through the `WrapAction` system. While `imageUploading` is true, the button shows a loading state and is disabled.

### Unsaved post guard

When `effectiveFilePath` is null (unsaved new post), the image button is disabled with tooltip "Save post first to add images".

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
