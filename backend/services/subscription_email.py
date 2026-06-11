"""HTML + plain-text builders for subscription emails.

The post body is the backend-sanitized rendered HTML; we only wrap it. The
unsubscribe link uses Resend's managed merge tag so Resend owns the unsubscribe
flow and suppression."""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

_WRAP_STYLE = (
    "font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;"
    "max-width:640px;margin:0 auto;padding:0 16px;color:#111;line-height:1.6"
)
_HEADER_STYLE = (
    "background:#f6f8fa;border:1px solid #e5e7eb;border-radius:8px;"
    "padding:10px 14px;margin:0 0 24px;font-size:13px;text-align:center"
)
_HEADER_LINK_STYLE = "color:#2563eb;text-decoration:none;font-weight:600"
_HEADER_SEP_STYLE = "color:#9ca3af"
_TITLE_STYLE = "font-size:26px;line-height:1.25;font-weight:700;margin:0 0 20px"
_TITLE_LINK_STYLE = "color:#111;text-decoration:none"
_FOOTER_STYLE = "margin-top:32px;border:none;border-top:1px solid #ddd"
_FOOTER_TEXT_STYLE = "color:#666;font-size:12px"

# Resend's managed-unsubscribe merge tag. Kept as a plain constant so f-strings
# can interpolate it without brace-escaping gymnastics.
_UNSUBSCRIBE_HREF = "{{{RESEND_UNSUBSCRIBE_URL}}}"

# Email clients don't run JavaScript, so KaTeX can't render client-side as it
# does on the web. Pandoc emits math as ``<span class="math …">`` carrying the
# raw (HTML-escaped) TeX; for email we rewrite those spans into images rendered
# by an external LaTeX service so the formulas display in Gmail and elsewhere.
# Privacy/availability tradeoff: each image request leaks the reader's IP to
# latex.codecogs.com and can act as an open-tracking signal; rendering depends
# on the third-party service being reachable. No local alternative exists.
_MATH_IMAGE_BASE_URL = "https://latex.codecogs.com/png.image?"
_MATH_IMAGE_DPI = r"\dpi{120} "
_MATH_SPAN_RE = re.compile(r'<span class="math (inline|display)">(.*?)</span>', re.DOTALL)

_ALLOWED_URL_SCHEMES = ("https://", "http://", "/")


def _safe_href(url: str) -> str:
    """Escape a URL for an href, neutralizing non-http(s)/relative schemes (e.g. javascript:)."""
    if not url.startswith(_ALLOWED_URL_SCHEMES):
        return "#"
    return _html.escape(url)


class _AbsolutePostUrlParser(HTMLParser):
    def __init__(self, post_url: str) -> None:
        super().__init__(convert_charrefs=False)
        self.post_url = post_url
        self.parts: list[str] = []

    def _attributes(self, attrs: list[tuple[str, str | None]]) -> str:
        rendered: list[str] = []
        for name, value in attrs:
            if value is None:
                rendered.append(name)
                continue
            if name in {"href", "src"} and value.startswith("/") and not value.startswith("//"):
                value = urljoin(self.post_url, value)
            rendered.append(f'{name}="{_html.escape(value, quote=True)}"')
        return f" {' '.join(rendered)}" if rendered else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(f"<{tag}{self._attributes(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(f"<{tag}{self._attributes(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")


def _absolute_post_urls(post_html: str, post_url: str) -> str:
    parser = _AbsolutePostUrlParser(post_url)
    parser.feed(post_html)
    parser.close()
    return "".join(parser.parts)


def _render_math_images(post_html: str) -> str:
    """Rewrite Pandoc KaTeX math spans into external-service rendered images.

    Operates on a copy of the email body only; the stored post HTML and the web
    render path are untouched. The raw TeX becomes the image ``alt`` so the
    formula is still readable if a client blocks the image.
    """

    def _replace(match: re.Match[str]) -> str:
        mode = match.group(1)
        # Pandoc HTML-escapes special chars inside the span; decode to get the
        # raw TeX before URL-encoding it for the image service.
        tex = _html.unescape(match.group(2)).strip()
        if not tex:
            return ""
        src = _MATH_IMAGE_BASE_URL + quote(_MATH_IMAGE_DPI + tex, safe="")
        safe_src = _html.escape(src, quote=True)
        safe_alt = _html.escape(tex, quote=True)
        if mode == "display":
            # Block + auto margins centers the image while staying valid phrasing
            # content (Pandoc wraps display math in a <p>, where a block <div>
            # would be invalid and render erratically in some email clients).
            return (
                f'<img src="{safe_src}" alt="{safe_alt}" '
                f'style="display:block;margin:18px auto;max-width:100%">'
            )
        return f'<img src="{safe_src}" alt="{safe_alt}" style="vertical-align:middle">'

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


def build_broadcast_email(
    *,
    post_url: str,
    post_title: str,
    post_html: str,
    controller_name: str,
    postal_address: str,
) -> tuple[str, str]:
    """Return (html, text) for a new-post broadcast email with a managed-unsubscribe footer."""
    safe_title = _html.escape(post_title)
    safe_url = _safe_href(post_url)
    safe_name = _html.escape(controller_name)
    safe_addr = _html.escape(postal_address)
    email_post_html = _render_math_images(_absolute_post_urls(post_html, post_url))
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
