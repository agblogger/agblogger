from __future__ import annotations

import html as _html

from hypothesis import given
from hypothesis import strategies as st

from backend.services.subscription_email import (
    build_broadcast_email,
    build_confirmation_email,
)


def test_confirmation_email_contains_confirm_link() -> None:
    html, text = build_confirmation_email(
        confirm_url="https://blog.example/subscribe/confirm?token=T",
        controller_name="Jane Blog",
    )
    assert "https://blog.example/subscribe/confirm?token=T" in html
    assert "https://blog.example/subscribe/confirm?token=T" in text
    assert "Jane Blog" in html
    assert "ignore" in text.lower()  # "if you didn't request this, ignore"


def test_broadcast_email_has_post_link_unsubscribe_and_footer() -> None:
    html, text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "https://blog.example/post/hello" in html
    assert "<p>Body</p>" in html
    assert "{{{RESEND_UNSUBSCRIBE_URL}}}" in html  # Resend-managed unsubscribe
    assert "Jane Blog" in html and "1 Main St, Town" in html
    assert "Hello" in text


def test_confirmation_email_escapes_controller_name() -> None:
    html, _text = build_confirmation_email(
        confirm_url="https://blog.example/subscribe/confirm?token=T",
        controller_name="<script>alert(1)</script>",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_broadcast_email_does_not_escape_post_html() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Hello <strong>world</strong></p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "<p>Hello <strong>world</strong></p>" in html


def test_broadcast_email_converts_root_relative_post_urls_to_absolute() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html='<p><img src="/post/hello/image.png"><a href="/page/about">About</a></p>',
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'src="https://blog.example/post/hello/image.png"' in html
    assert 'href="https://blog.example/page/about"' in html


def test_broadcast_email_escapes_title_in_html() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="A & B <x>",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert "&amp;" in html
    assert "&lt;x&gt;" in html
    assert "<x>" not in html


def test_broadcast_email_neutralizes_javascript_post_url() -> None:
    html, _text = build_broadcast_email(
        post_url="javascript:alert(1)",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="1 Main St, Town",
    )
    assert 'href="javascript:' not in html
    assert 'href="#"' in html


def test_confirmation_email_neutralizes_javascript_url() -> None:
    html, _text = build_confirmation_email(
        confirm_url="javascript:alert(1)",
        controller_name="Jane Blog",
    )
    assert 'href="javascript:' not in html
    assert 'href="#"' in html


def test_broadcast_email_escapes_footer_fields() -> None:
    html, _text = build_broadcast_email(
        post_url="https://blog.example/post/hello",
        post_title="Hello",
        post_html="<p>Body</p>",
        controller_name="Jane Blog",
        postal_address="<script>bad</script>",
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


@given(name=st.text())
def test_confirmation_html_always_escapes_controller_name(name: str) -> None:
    html, _ = build_confirmation_email(confirm_url="https://blog.example/c", controller_name=name)
    assert _html.escape(name) in html
