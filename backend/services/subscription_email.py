"""HTML + plain-text builders for subscription emails.

The post body is the backend-sanitized rendered HTML; we wrap it and restyle it
for email delivery. Email clients run no JavaScript and ignore external/most
embedded CSS, so the web ``.prose`` styles (see ``frontend/src/index.css``) are
inlined here onto the post HTML so broadcasts resemble the on-site rendering.
The unsubscribe link uses Resend's managed merge tag so Resend owns the
unsubscribe flow and suppression."""

from __future__ import annotations

import asyncio
import html as _html
import logging
import re
import struct
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

import httpx

logger = logging.getLogger(__name__)

# Fonts: custom web fonts (DM Sans, Lora, JetBrains Mono) don't load in email,
# so fall back to widely available system equivalents that match their style.
_SANS = "system-ui,-apple-system,Segoe UI,Arial,sans-serif"
_SERIF = "Georgia,'Times New Roman',serif"
_MONO = "'JetBrains Mono','Fira Code',Menlo,Consolas,monospace"

# Body text mirrors the web ``.prose`` block: ~1.05rem with generous leading.
_WRAP_STYLE = (
    f"font-family:{_SANS};font-size:17px;line-height:1.75;"
    "max-width:640px;margin:0 auto;padding:0 16px;color:#1a1a1a"
)
_HEADER_STYLE = (
    "background:#f6f8fa;border:1px solid #e5e7eb;border-radius:8px;"
    "padding:10px 14px;margin:0 0 24px;font-size:13px;text-align:center"
)
_HEADER_LINK_STYLE = "color:#2563eb;text-decoration:none;font-weight:600"
_HEADER_SEP_STYLE = "color:#9ca3af"
_TITLE_STYLE = (
    f"font-family:{_SERIF};font-size:28px;line-height:1.25;font-weight:600;margin:0 0 20px"
)
_TITLE_LINK_STYLE = "color:#1a1a1a;text-decoration:none"
_FOOTER_STYLE = "margin-top:32px;border:none;border-top:1px solid #ddd"
_FOOTER_TEXT_STYLE = "color:#666;font-size:12px"

# Resend's managed-unsubscribe merge tag. Kept as a plain constant so f-strings
# can interpolate it without brace-escaping gymnastics.
_UNSUBSCRIBE_HREF = "{{{RESEND_UNSUBSCRIBE_URL}}}"

# ── Post-body styling (inlined web .prose styles, adapted for email) ──────────
# Mirrors frontend/src/index.css: rem→px against a 16px root, CSS variables
# resolved to the light-theme palette, pseudo-elements turned into real markup.
_TAG_STYLES: dict[str, str] = {
    "p": "margin:0 0 20px",
    "a": "color:#c44b2b;text-decoration:underline",
    "h1": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:32px;margin:24px 0 16px",
    "h2": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:26px;margin:32px 0 12px",
    "h3": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:21px;margin:28px 0 8px",
    "h4": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:18px;margin:24px 0 8px",
    "h5": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:16px;margin:24px 0 8px",
    "h6": f"font-family:{_SERIF};font-weight:600;line-height:1.2;font-size:15px;margin:24px 0 8px",
    "ul": "margin:16px 0;padding-left:24px",
    "ol": "margin:16px 0;padding-left:24px",
    "li": "margin:0 0 6px",
    "blockquote": (
        "border-left:3px solid #c44b2b;padding:8px 20px;margin:24px 0;"
        "background:#f5f0ea;font-style:italic"
    ),
    "pre": (
        f"background:#1e1e2e;color:#cdd6f4;padding:20px;border-radius:8px;overflow-x:auto;"
        f"font-family:{_MONO};font-size:14px;line-height:1.6;margin:24px 0"
    ),
    "code": (
        f"font-family:{_MONO};background:#ede8e1;padding:2px 5px;border-radius:4px;font-size:0.85em"
    ),
    "hr": "border:none;border-top:1px solid #e0dbd4;margin:40px 0",
    "table": "width:100%;border-collapse:collapse;margin:24px 0;font-size:15px",
    "th": "padding:12px;text-align:left;border:1px solid #e0dbd4",
    "td": "padding:12px;text-align:left;border:1px solid #e0dbd4",
    "img": "border-radius:8px;max-width:100%",
    "figcaption": (
        f"text-align:center;font-family:{_MONO};font-size:13px;margin-top:8px;color:#8a857e"
    ),
}
# Admonition callout (``::: note``) and footnotes section are class-based.
_NOTE_STYLE = (
    "border:1px solid #c8c1b8;border-left:3px solid #8a857e;background:#f5f0ea;"
    "border-radius:4px;padding:12px 20px;margin:24px 0"
)
_FOOTNOTES_STYLE = "font-size:0.85em"
# The web renders the "Note" label via a ::before pseudo-element; email needs
# real markup, so it is injected as the callout's first child.
_NOTE_LABEL_HTML = (
    '<div style="font-size:12px;font-weight:600;letter-spacing:0.05em;'
    'text-transform:uppercase;color:#8a857e;margin-bottom:8px">Note</div>'
)

# Pandoc/skylighting highlight token classes → inline styles, mirroring the
# Catppuccin Mocha palette in `.prose pre` (frontend/src/index.css). Applied
# only inside <pre> so author classes elsewhere aren't accidentally recolored.
_HL_MAUVE = "color:#cba6f7"
_HL_GREEN = "color:#a6e3a1"
_HL_PEACH = "color:#fab387"
_HL_SKY = "color:#89dceb"
_HL_RED = "color:#f38ba8"
_HL_YELLOW = "color:#f9e2af"
_HL_OVERLAY = "color:#6c7086;font-style:italic"
_HIGHLIGHT_STYLES: dict[str, str] = {
    "kw": f"{_HL_MAUVE};font-weight:500",  # keyword
    "cf": f"{_HL_MAUVE};font-weight:500",  # control flow
    "im": _HL_MAUVE,  # import
    "dt": _HL_YELLOW,  # data type
    "at": _HL_YELLOW,  # attribute
    "wa": f"{_HL_YELLOW};font-style:italic",  # warning
    "dv": _HL_PEACH,  # decimal value
    "bn": _HL_PEACH,  # base-N integer
    "fl": _HL_PEACH,  # float
    "cn": _HL_PEACH,  # constant
    "ch": _HL_GREEN,  # char
    "st": _HL_GREEN,  # string
    "vs": _HL_GREEN,  # verbatim string
    "ss": _HL_GREEN,  # special string
    "sc": _HL_GREEN,  # special char
    "co": _HL_OVERLAY,  # comment
    "do": _HL_OVERLAY,  # documentation
    "an": _HL_OVERLAY,  # annotation
    "cv": _HL_OVERLAY,  # comment var
    "in": _HL_OVERLAY,  # information
    "ot": _HL_SKY,  # other token
    "bu": _HL_SKY,  # built-in
    "op": _HL_SKY,  # operator
    "fu": "color:#89b4fa",  # function
    "al": f"{_HL_RED};font-weight:500",  # alert
    "er": f"{_HL_RED};font-weight:500",  # error
    "pp": _HL_RED,  # preprocessor
    "va": "color:#cdd6f4",  # variable
    "re": "color:#f2cdcd",  # region marker
}

# Email clients don't run JavaScript, so KaTeX can't render client-side as it
# does on the web. Pandoc emits math as ``<span class="math …">`` carrying the
# raw (HTML-escaped) TeX; for email we rewrite those spans into images rendered
# by an external LaTeX service. The image is rendered at a high DPI and displayed
# at a smaller, text-matched size (measured per formula) so it stays crisp on the
# high-density screens where most email is read while matching the surrounding
# text. Privacy/availability tradeoff: each image request leaks the reader's IP to
# latex.codecogs.com and can act as an open-tracking signal; rendering depends on
# the third-party service being reachable. No local alternative exists.
_MATH_IMAGE_BASE_URL = "https://latex.codecogs.com/png.image?"
# Source is rendered at 3x the display size for crispness; the display size
# (~120 DPI) is calibrated so a lone variable matches 17px body text.
_MATH_SOURCE_DPI = 360
_MATH_DISPLAY_DPI = 120
_MATH_FETCH_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MATH_FETCH_CONCURRENCY = 6
_MATH_SPAN_RE = re.compile(r'<span class="math (inline|display)">(.*?)</span>', re.DOTALL)

_ALLOWED_URL_SCHEMES = ("https://", "http://", "/")

# A measurer maps a math-image URL to its (width, height) in pixels, or None
# when the dimensions can't be determined (so we fall back to an unsized image).
MathMeasurer = Callable[[str], Awaitable[tuple[int, int] | None]]


def _safe_href(url: str) -> str:
    """Escape a URL for an href, neutralizing non-http(s)/relative schemes (e.g. javascript:)."""
    if not url.startswith(_ALLOWED_URL_SCHEMES):
        return "#"
    return _html.escape(url)


def _classes(attrs: list[tuple[str, str | None]]) -> list[str]:
    for name, value in attrs:
        if name == "class" and value:
            return value.split()
    return []


def _email_style(tag: str, classes: list[str], in_pre: bool) -> str | None:
    """Return the inline style for an element, or None to leave it unstyled."""
    if "note" in classes:
        return _NOTE_STYLE
    if "footnotes" in classes:
        return _FOOTNOTES_STYLE
    if in_pre:
        for cls in classes:
            if cls in _HIGHLIGHT_STYLES:
                return _HIGHLIGHT_STYLES[cls]
        if tag == "code":
            # Inside a <pre> the block style already covers the code; an inline
            # background here would be wrong (mirrors web `:not(pre) > code`).
            return None
    return _TAG_STYLES.get(tag)


def _merge_style(attrs: list[tuple[str, str | None]], style: str) -> list[tuple[str, str | None]]:
    merged: list[tuple[str, str | None]] = []
    found = False
    for name, value in attrs:
        if name == "style":
            found = True
            merged.append((name, f"{value};{style}" if value else style))
        else:
            merged.append((name, value))
    if not found:
        merged.append(("style", style))
    return merged


def _render_attrs(attrs: list[tuple[str, str | None]]) -> str:
    rendered: list[str] = []
    for name, value in attrs:
        if value is None:
            rendered.append(name)
        else:
            rendered.append(f'{name}="{_html.escape(value, quote=True)}"')
    return f" {' '.join(rendered)}" if rendered else ""


class _EmailBodyParser(HTMLParser):
    """Rewrite post HTML for email: absolutize URLs and inline ``.prose`` styles.

    Root-relative and fragment ``href``/``src`` values are made absolute against
    the post URL (email clients don't share the page origin and don't reliably
    support intra-document links), and element styles are inlined so the body
    resembles the on-site rendering.
    """

    def __init__(self, post_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.post_url = post_url
        self.parts: list[str] = []
        self._pre_depth = 0

    def _absolutize(self, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        for name, value in attrs:
            if value is not None:
                is_fragment_link = name == "href" and value.startswith("#")
                is_root_relative_url = (
                    name in {"href", "src"} and value.startswith("/") and not value.startswith("//")
                )
                if is_fragment_link or is_root_relative_url:
                    value = urljoin(self.post_url, value)
            out.append((name, value))
        return out

    def _render_open(
        self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool
    ) -> str:
        attrs = self._absolutize(attrs)
        style = _email_style(tag, _classes(attrs), self._pre_depth > 0)
        if style:
            attrs = _merge_style(attrs, style)
        slash = "/" if self_closing else ""
        return f"<{tag}{_render_attrs(attrs)}{slash}>"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre":
            self._pre_depth += 1
        self.parts.append(self._render_open(tag, attrs, self_closing=False))
        if "note" in _classes(attrs):
            self.parts.append(_NOTE_LABEL_HTML)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self._render_open(tag, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")
        if tag == "pre" and self._pre_depth > 0:
            self._pre_depth -= 1

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")


def _prepare_email_body(post_html: str, post_url: str) -> str:
    parser = _EmailBodyParser(post_url)
    parser.feed(post_html)
    parser.close()
    return "".join(parser.parts)


def _math_src(tex: str, dpi: int) -> str:
    return _MATH_IMAGE_BASE_URL + quote(rf"\dpi{{{dpi}}} " + tex, safe="")


def _math_img(mode: str, tex: str, dim: tuple[int, int] | None) -> str:
    """Build the <img> for one math span, sizing it from the measured dimensions.

    With dimensions, the high-DPI source is displayed at the text-matched size
    (explicit width/height, which all email clients honor) so it is both crisp
    and correctly sized. Without them, fall back to a display-DPI image at its
    natural size — correctly sized but softer — rather than risk a giant image.
    """
    safe_alt = _html.escape(tex, quote=True)
    if dim is not None:
        width = max(1, round(dim[0] * _MATH_DISPLAY_DPI / _MATH_SOURCE_DPI))
        height = max(1, round(dim[1] * _MATH_DISPLAY_DPI / _MATH_SOURCE_DPI))
        safe_src = _html.escape(_math_src(tex, _MATH_SOURCE_DPI), quote=True)
        size = f'width="{width}" height="{height}"'
        if mode == "display":
            return (
                f'<img src="{safe_src}" alt="{safe_alt}" {size} '
                f'style="display:block;margin:18px auto;max-width:100%;height:auto">'
            )
        return f'<img src="{safe_src}" alt="{safe_alt}" {size} style="vertical-align:middle">'
    safe_src = _html.escape(_math_src(tex, _MATH_DISPLAY_DPI), quote=True)
    if mode == "display":
        return (
            f'<img src="{safe_src}" alt="{safe_alt}" '
            f'style="display:block;margin:18px auto;max-width:100%">'
        )
    return f'<img src="{safe_src}" alt="{safe_alt}" style="vertical-align:middle">'


async def _fetch_png_dimensions(client: httpx.AsyncClient, url: str) -> tuple[int, int] | None:
    """Fetch a PNG and read its pixel dimensions from the IHDR chunk, or None on failure."""
    try:
        response = await client.get(url)
        response.raise_for_status()
        data = response.content
    except httpx.HTTPError as exc:
        logger.warning("Math image measurement request failed: %s", exc)
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        logger.warning("Math image measurement got a non-PNG response (%d bytes)", len(data))
        return None
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error as exc:
        logger.warning("Math image dimension parse failed: %s", exc)
        return None
    return (int(width), int(height))


async def _render_math_images(post_html: str, measure: MathMeasurer) -> str:
    """Rewrite Pandoc KaTeX math spans into external-service rendered images.

    Operates on a copy of the email body only; the stored post HTML and the web
    render path are untouched. Each distinct formula is measured once,
    concurrently, so identical formulas don't trigger redundant requests.
    """
    if not _MATH_SPAN_RE.search(post_html):
        return post_html

    sources: dict[str, str] = {}
    for match in _MATH_SPAN_RE.finditer(post_html):
        tex = _html.unescape(match.group(2)).strip()
        if tex and tex not in sources:
            sources[tex] = _math_src(tex, _MATH_SOURCE_DPI)

    semaphore = asyncio.Semaphore(_MATH_FETCH_CONCURRENCY)

    async def _measure_one(tex: str, url: str) -> tuple[str, tuple[int, int] | None]:
        async with semaphore:
            return tex, await measure(url)

    measured = await asyncio.gather(*(_measure_one(tex, url) for tex, url in sources.items()))
    dims = dict(measured)

    def _replace(match: re.Match[str]) -> str:
        tex = _html.unescape(match.group(2)).strip()
        if not tex:
            return ""
        return _math_img(match.group(1), tex, dims.get(tex))

    return _MATH_SPAN_RE.sub(_replace, post_html)


def build_confirmation_email(*, confirm_url: str, controller_name: str) -> tuple[str, str]:
    """Return (html, text) for the double opt-in confirmation email."""
    safe_name = _html.escape(controller_name)
    safe_url = _safe_href(confirm_url)
    html = (
        f'<div style="{_WRAP_STYLE}">'
        f"<p>Please confirm your subscription to {safe_name}.</p>"
        f'<p><a href="{safe_url}">Confirm my subscription</a></p>'
        f'<p style="color:#666;font-size:13px">If you didn\'t request this, ignore this email '
        f"and you won't be subscribed.</p>"
        f"</div>"
    )
    text = (
        f"Please confirm your subscription to {controller_name}.\n\n"
        f"Confirm: {confirm_url}\n\n"
        f"If you didn't request this, ignore this email and you won't be subscribed."
    )
    return html, text


async def build_broadcast_email(
    *,
    post_url: str,
    post_title: str,
    post_html: str,
    controller_name: str,
    postal_address: str,
    measure_math: MathMeasurer | None = None,
) -> tuple[str, str]:
    """Return (html, text) for a new-post broadcast email with a managed-unsubscribe footer."""
    safe_title = _html.escape(post_title)
    safe_url = _safe_href(post_url)
    safe_name = _html.escape(controller_name)
    safe_addr = _html.escape(postal_address)

    body = _prepare_email_body(post_html, post_url)
    if measure_math is not None:
        email_post_html = await _render_math_images(body, measure_math)
    elif _MATH_SPAN_RE.search(body):
        async with httpx.AsyncClient(timeout=_MATH_FETCH_TIMEOUT) as client:

            async def _measure(url: str) -> tuple[int, int] | None:
                return await _fetch_png_dimensions(client, url)

            email_post_html = await _render_math_images(body, _measure)
    else:
        email_post_html = body

    header = (
        f'<div style="{_HEADER_STYLE}">'
        f'<a href="{safe_url}" style="{_HEADER_LINK_STYLE}">View this post online</a>'
        f'<span style="{_HEADER_SEP_STYLE}"> &nbsp;·&nbsp; </span>'
        f'<a href="{_UNSUBSCRIBE_HREF}" style="{_HEADER_LINK_STYLE}">Unsubscribe</a>'
        f"</div>"
    )
    title = (
        f'<h1 style="{_TITLE_STYLE}">'
        f'<a href="{safe_url}" style="{_TITLE_LINK_STYLE}">{safe_title}</a></h1>'
    )
    footer = (
        f'<hr style="{_FOOTER_STYLE}">'
        f'<p style="{_FOOTER_TEXT_STYLE}">'
        f"{safe_name} — {safe_addr}<br>"
        f'<a href="{_UNSUBSCRIBE_HREF}">Unsubscribe</a></p>'
    )
    html = f'<div style="{_WRAP_STYLE}">{header}{title}{email_post_html}{footer}</div>'
    text = (
        f"{post_title}\n\n"
        f"View this post online: {post_url}\n\n"
        f"{controller_name} — {postal_address}\n"
        f"Unsubscribe: see the link in the HTML version."
    )
    return html, text
