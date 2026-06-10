"""HTML + plain-text builders for subscription emails.

The post body is the backend-sanitized rendered HTML; we only wrap it. The
unsubscribe link uses Resend's managed merge tag so Resend owns the unsubscribe
flow and suppression."""

from __future__ import annotations

import html as _html

_WRAP_STYLE = "font-family:system-ui,Arial,sans-serif;max-width:640px;margin:0 auto;color:#111"

_ALLOWED_URL_SCHEMES = ("https://", "http://", "/")


def _safe_href(url: str) -> str:
    """Escape a URL for an href, neutralizing non-http(s)/relative schemes (e.g. javascript:)."""
    if not url.startswith(_ALLOWED_URL_SCHEMES):
        return "#"
    return _html.escape(url)


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
    footer = (
        f'<hr style="margin-top:32px;border:none;border-top:1px solid #ddd">'
        f'<p style="color:#666;font-size:12px">'
        f"{safe_name} — {safe_addr}<br>"
        f'<a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}">Unsubscribe</a></p>'
    )
    html = (
        f'<div style="{_WRAP_STYLE}">'
        f'<p><a href="{safe_url}">{safe_title}</a></p>'
        f"{post_html}"
        f"{footer}"
        f"</div>"
    )
    text = (
        f"{post_title}\n{post_url}\n\n"
        f"Read it online at the link above.\n\n"
        f"{controller_name} — {postal_address}\n"
        f"Unsubscribe: see the link in the HTML version."
    )
    return html, text
