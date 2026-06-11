"""Page-related schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SubscriptionCompliance(BaseModel):
    controller_name: str
    controller_contact: str
    privacy_policy_url: str


class PageConfig(BaseModel):
    """Top-level page configuration."""

    id: str
    title: str
    file: str | None = None


class PageResponse(BaseModel):
    """Page content response."""

    id: str
    title: str
    rendered_html: str


class SiteConfigResponse(BaseModel):
    """Site configuration response."""

    title: str
    description: str
    pages: list[PageConfig]
    subscriptions_enabled: bool = False
    subscription_compliance: SubscriptionCompliance | None = None
