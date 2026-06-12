# YouTube Thumbnail Replacement in Broadcast Emails

**Date:** 2026-06-12

## Problem

YouTube `<iframe>` embeds in posts survive HTML sanitization and appear verbatim in broadcast emails. Email clients universally block or silently discard iframes, so subscribers see nothing where a video was embedded. Ghost has the same bug (empty outlined box). Substack, MailerLite, AWeber, and HubSpot all solve this with the same pattern: a clickable thumbnail image linking to the video on YouTube.

## Scope

Email rendering only. Stored post HTML and the web render path are untouched.

## Design

### Transformation

`_EmailBodyParser` in `backend/services/subscription_email.py` is extended to intercept `<iframe>` tags during the existing `_prepare_email_body` pass. When the parser encounters an iframe:

1. Extract the YouTube video ID from the `src` attribute using a new `_YOUTUBE_VIDEO_ID_RE` regex (mirrors `_YOUTUBE_SRC_RE` in `renderer.py`, with a capture group for the 11-char ID).
2. Emit the thumbnail block (see below) in place of the iframe open tag.
3. Set `_in_iframe = True` to suppress all inner content and the closing `</iframe>` tag.

A `_in_iframe` boolean flag (not a depth counter — iframes cannot be nested) suppresses `handle_starttag`, `handle_endtag`, `handle_startendtag`, `handle_data`, `handle_entityref`, and `handle_charref` while active. The flag is cleared on `handle_endtag("iframe")`.

If the `src` attribute is absent or the video ID cannot be extracted, the iframe is silently dropped with no output — defensive, since the sanitizer already guarantees surviving iframes have valid YouTube srcs.

### Video ID Extraction

The regex captures the 11-character video ID from all three allowed src forms:

```
https://www.youtube.com/embed/{ID}[?params]
https://www.youtube.com/shorts/{ID}[?params]
https://www.youtube-nocookie.com/embed/{ID}[?params]
```

The watch link always uses `https://www.youtube.com/watch?v={ID}`.  
The thumbnail always uses `https://img.youtube.com/vi/{ID}/hqdefault.jpg` (480×360, reliably available for every YouTube video; `maxresdefault` is absent for many videos and not worth the server-side probe given `hqdefault` is sufficient for a 640px-wide email).

### Replacement HTML

```html
<a href="https://www.youtube.com/watch?v={ID}" style="display:block;text-decoration:none">
  <img src="https://img.youtube.com/vi/{ID}/hqdefault.jpg"
       alt="YouTube video"
       style="width:100%;max-width:100%;border-radius:8px;display:block">
</a>
<p style="text-align:center;font-size:13px;color:#8a857e;margin:6px 0 20px">
  ▶ <a href="https://www.youtube.com/watch?v={ID}" style="color:#8a857e;text-decoration:none">Watch on YouTube</a>
</p>
```

- `border-radius:8px` matches `_TAG_STYLES["img"]` for visual consistency.
- Caption color `#8a857e` matches `_FOOTNOTES_STYLE` / figcaption muted tone.
- `text-decoration:none` on the outer `<a>` prevents Outlook from drawing an underline border around the image.
- The caption doubles as a text-only fallback for clients that block all images.

## Files Changed

- `backend/services/subscription_email.py` — extend `_EmailBodyParser` with `_in_iframe` flag and iframe → thumbnail replacement; add `_YOUTUBE_VIDEO_ID_RE` constant and `_youtube_thumbnail_html` helper.
- `tests/test_services/test_subscription_email.py` — new tests (see below).

No changes to `renderer.py`, stored HTML, or any other file.

## Tests

All new tests go in `tests/test_services/test_subscription_email.py`:

- Embed URL (`/embed/{ID}`) → thumbnail image src and caption link both use correct video ID and watch URL.
- Shorts URL (`/shorts/{ID}`) → correct watch URL.
- Nocookie URL (`youtube-nocookie.com/embed/{ID}`) → correct watch URL.
- Query params in src (e.g. `?start=30`) → video ID still extracted correctly.
- Self-closing `<iframe ... />` → replaced (sanitizer emits both open and close; parser sees start + end).
- Multiple iframes in one post → each replaced independently.
- Malformed iframe (no `src`) → silently dropped, surrounding content unaffected.
- Existing URL absolutization and inline style injection still apply to surrounding content.
