"""Tests for the built-in subscription privacy policy."""

from backend.api.pages import _privacy_policy_page
from backend.services.subscription_service import PublicSubscriptionCompliance


def test_privacy_policy_escapes_compliance_values() -> None:
    page = _privacy_policy_page(
        PublicSubscriptionCompliance(
            controller_name="<img src=x onerror=alert(1)>",
            controller_contact="<script>alert(2)</script>",
            privacy_policy_url=None,
        )
    )

    assert "<script>" not in page.rendered_html
    assert "<img src=x" not in page.rendered_html
    assert "&lt;script&gt;" in page.rendered_html
    assert "&lt;img src=x onerror=alert(1)&gt;" in page.rendered_html
