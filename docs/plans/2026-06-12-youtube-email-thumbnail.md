# YouTube Email Thumbnail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace YouTube `<iframe>` embeds in broadcast emails with a clickable thumbnail image linking to YouTube, so subscribers see video content instead of a blank area.

**Architecture:** Extend `_EmailBodyParser` in `subscription_email.py` with an `_in_iframe` flag. When an `<iframe>` open tag is encountered, extract the video ID, emit a thumbnail `<img>` wrapped in an `<a>`, and suppress all content through the matching `</iframe>`. No changes to stored HTML or the web render path.

**Tech Stack:** Python `html.parser.HTMLParser`, `re`, existing `subscription_email.py` patterns.

---

### Task 1: Write failing tests for YouTube iframe → thumbnail replacement

**Files:**
- Modify: `tests/test_services/test_subscription_email.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_services/test_subscription_email.py` (after the last existing test):

```python
def test_broadcast_email_youtube_embed_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast(
        "<p>Before</p>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "<p>After</p>"
    )
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html
    assert "Watch on YouTube" in html
    assert "Before" in html
    assert "After" in html


def test_broadcast_email_youtube_shorts_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast('<iframe src="https://www.youtube.com/shorts/dQw4w9WgXcQ"></iframe>')
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_youtube_nocookie_iframe_replaced_with_thumbnail() -> None:
    html = _broadcast(
        '<iframe src="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"></iframe>'
    )
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_youtube_iframe_with_query_params_uses_correct_video_id() -> None:
    html = _broadcast(
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?start=30"></iframe>'
    )
    assert "<iframe" not in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in html


def test_broadcast_email_multiple_youtube_iframes_each_replaced() -> None:
    html = _broadcast(
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        '<iframe src="https://www.youtube.com/embed/AAAAAAAAAAA"></iframe>'
    )
    assert "<iframe" not in html
    assert html.count("img.youtube.com/vi/") == 2
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
    assert "img.youtube.com/vi/AAAAAAAAAAA/hqdefault.jpg" in html


def test_broadcast_email_iframe_without_src_silently_dropped() -> None:
    html = _broadcast("<p>Before</p><iframe></iframe><p>After</p>")
    assert "<iframe" not in html
    assert "youtube" not in html
    assert "Before" in html
    assert "After" in html


def test_broadcast_email_surrounding_content_unaffected_by_iframe_replacement() -> None:
    html = _broadcast(
        "<h2>Section</h2>"
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
        "<p>Continue reading.</p>"
    )
    assert "Section" in html
    assert "Continue reading." in html
    assert "img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg" in html
```

- [ ] **Step 2: Run the tests to confirm they all fail**

```bash
just test-backend -- tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_embed_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_shorts_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_nocookie_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_iframe_with_query_params_uses_correct_video_id tests/test_services/test_subscription_email.py::test_broadcast_email_multiple_youtube_iframes_each_replaced tests/test_services/test_subscription_email.py::test_broadcast_email_iframe_without_src_silently_dropped tests/test_services/test_subscription_email.py::test_broadcast_email_surrounding_content_unaffected_by_iframe_replacement
```

Expected: 7 FAILED — assertions fail because iframes currently pass through to the email HTML unchanged.

---

### Task 2: Implement iframe → thumbnail replacement and make tests pass

**Files:**
- Modify: `backend/services/subscription_email.py`

- [ ] **Step 1: Add the `_YOUTUBE_VIDEO_ID_RE` regex constant**

In `subscription_email.py`, after the `_MATH_SPAN_RE` line (line 159), add:

```python
_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"^https://www\.(?:youtube\.com/(?:embed|shorts)/|youtube-nocookie\.com/embed/)"
    r"([a-zA-Z0-9_-]{11})(?:\?[a-zA-Z0-9_=&%-]*)?$"
)
```

This mirrors `_YOUTUBE_SRC_RE` in `renderer.py` but adds a capture group for the 11-character video ID.

- [ ] **Step 2: Add the `_youtube_thumbnail_html` helper**

Place this before `class _EmailBodyParser` (alongside the other module-level helpers such as `_safe_href`). Add:

```python
def _youtube_thumbnail_html(video_id: str) -> str:
    safe_id = _html.escape(video_id, quote=True)
    watch_url = f"https://www.youtube.com/watch?v={safe_id}"
    thumb_url = f"https://img.youtube.com/vi/{safe_id}/hqdefault.jpg"
    return (
        f'<a href="{watch_url}" style="display:block;text-decoration:none">'
        f'<img src="{thumb_url}" alt="YouTube video"'
        f' style="width:100%;max-width:100%;border-radius:8px;display:block">'
        f"</a>"
        f'<p style="text-align:center;font-size:13px;color:#8a857e;margin:6px 0 20px">'
        f'▶ <a href="{watch_url}" style="color:#8a857e;text-decoration:none">Watch on YouTube</a>'
        f"</p>"
    )
```

- [ ] **Step 3: Add `_in_iframe` to `_EmailBodyParser.__init__`**

In `_EmailBodyParser.__init__`, add `self._in_iframe = False` after `self._pre_depth = 0`:

```python
def __init__(self, post_url: str) -> None:
    super().__init__(convert_charrefs=False)
    self.post_url = post_url
    self.parts: list[str] = []
    self._pre_depth = 0
    self._in_iframe = False
```

- [ ] **Step 4: Update `handle_starttag` to intercept iframes**

Replace the existing `handle_starttag` with:

```python
def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    if self._in_iframe:
        return
    if tag == "iframe":
        src = next((v for n, v in attrs if n == "src" and v is not None), None)
        if src:
            m = _YOUTUBE_VIDEO_ID_RE.fullmatch(src.strip())
            if m:
                self.parts.append(_youtube_thumbnail_html(m.group(1)))
        self._in_iframe = True
        return
    if tag == "pre":
        self._pre_depth += 1
    self.parts.append(self._render_open(tag, attrs, self_closing=False))
    if "note" in _classes(attrs):
        self.parts.append(_NOTE_LABEL_HTML)
```

- [ ] **Step 5: Update `handle_startendtag` to intercept self-closing iframes**

Replace the existing `handle_startendtag` with:

```python
def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
    if self._in_iframe:
        return
    if tag == "iframe":
        src = next((v for n, v in attrs if n == "src" and v is not None), None)
        if src:
            m = _YOUTUBE_VIDEO_ID_RE.fullmatch(src.strip())
            if m:
                self.parts.append(_youtube_thumbnail_html(m.group(1)))
        return
    self.parts.append(self._render_open(tag, attrs, self_closing=True))
```

- [ ] **Step 6: Update `handle_endtag` to clear `_in_iframe` on `</iframe>`**

Replace the existing `handle_endtag` with:

```python
def handle_endtag(self, tag: str) -> None:
    if tag == "iframe":
        self._in_iframe = False
        return
    if self._in_iframe:
        return
    self.parts.append(f"</{tag}>")
    if tag == "pre" and self._pre_depth > 0:
        self._pre_depth -= 1
```

- [ ] **Step 7: Guard `handle_data`, `handle_entityref`, `handle_charref`, `handle_comment` against iframe content**

Replace each of the four remaining handler methods:

```python
def handle_data(self, data: str) -> None:
    if self._in_iframe:
        return
    self.parts.append(data)

def handle_entityref(self, name: str) -> None:
    if self._in_iframe:
        return
    self.parts.append(f"&{name};")

def handle_charref(self, name: str) -> None:
    if self._in_iframe:
        return
    self.parts.append(f"&#{name};")

def handle_comment(self, data: str) -> None:
    if self._in_iframe:
        return
    self.parts.append(f"<!--{data}-->")
```

- [ ] **Step 8: Run the new tests to confirm they all pass**

```bash
just test-backend -- tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_embed_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_shorts_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_nocookie_iframe_replaced_with_thumbnail tests/test_services/test_subscription_email.py::test_broadcast_email_youtube_iframe_with_query_params_uses_correct_video_id tests/test_services/test_subscription_email.py::test_broadcast_email_multiple_youtube_iframes_each_replaced tests/test_services/test_subscription_email.py::test_broadcast_email_iframe_without_src_silently_dropped tests/test_services/test_subscription_email.py::test_broadcast_email_surrounding_content_unaffected_by_iframe_replacement
```

Expected: 7 PASSED.

- [ ] **Step 9: Run the full backend check to confirm no regressions**

```bash
just check-backend
```

Expected: all checks and tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/services/subscription_email.py tests/test_services/test_subscription_email.py
git commit -m "feat: replace YouTube iframes with thumbnail images in broadcast emails"
```
