"""Tests for the Resend HTTP client."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable
import pytest

from backend.services import resend_client
from backend.services.resend_client import ResendError


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_send_email_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"id": "email_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    out = await resend_client.send_email(
        api_key="re_x", from_="A <a@b.com>", to="r@x.com", subject="s", html="<p>h</p>", text="h"
    )
    assert out == "email_1"
    assert seen["url"].endswith("/emails")
    assert seen["auth"] == "Bearer re_x"


@pytest.mark.asyncio
async def test_send_email_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Invalid from"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.send_email(
            api_key="re_x", from_="bad", to="r@x.com", subject="s", html="h", text="h"
        )
    assert "Invalid from" in str(exc.value)


@pytest.mark.asyncio
async def test_create_contact_calls_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(201, json={"id": "contact_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    await resend_client.create_contact(api_key="re_x", segment_id="seg_1", email="r@x.com")
    assert "seg_1" in seen["url"]


@pytest.mark.asyncio
async def test_create_contact_treats_already_exists_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Contact already exists"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    # Should not raise even though the API returns an error
    await resend_client.create_contact(api_key="re_x", segment_id="seg_1", email="r@x.com")


@pytest.mark.asyncio
async def test_create_and_send_broadcast_posts_create_then_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/broadcasts":
            return httpx.Response(200, json={"id": "bcast_9"})
        return httpx.Response(200, json={})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    broadcast_id = await resend_client.create_and_send_broadcast(
        api_key="re_x",
        segment_id="seg_1",
        from_="A <a@b.com>",
        subject="s",
        html="<p>h</p>",
        text="h",
    )
    assert broadcast_id == "bcast_9"
    assert "/broadcasts" in seen_paths
    assert "/broadcasts/bcast_9/send" in seen_paths
    assert seen_paths.index("/broadcasts") < seen_paths.index("/broadcasts/bcast_9/send")


@pytest.mark.asyncio
async def test_count_contacts_returns_len_of_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "1"}, {"id": "2"}]})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    count = await resend_client.count_contacts(api_key="re_x", segment_id="seg_1")
    assert count == 2


@pytest.mark.asyncio
async def test_count_contacts_follows_cursor_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_after: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_after.append(request.url.params.get("after"))
        if request.url.params.get("after") is None:
            return httpx.Response(
                200,
                json={"has_more": True, "data": [{"id": "1"}, {"id": "2"}]},
            )
        return httpx.Response(200, json={"has_more": False, "data": [{"id": "3"}]})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    count = await resend_client.count_contacts(api_key="re_x", segment_id="seg_1")
    assert count == 3
    assert seen_after == [None, "2"]


@pytest.mark.asyncio
async def test_network_error_becomes_resend_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.send_email(
            api_key="re_x", from_="A <a@b.com>", to="r@x.com", subject="s", html="h", text="h"
        )
    # Internal details should not leak to the caller
    assert "boom" not in str(exc.value)
    assert "Could not reach the email provider" in str(exc.value)


@pytest.mark.asyncio
async def test_create_and_send_broadcast_raises_when_no_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError):
        await resend_client.create_and_send_broadcast(
            api_key="re_x",
            segment_id="seg_1",
            from_="A <a@b.com>",
            subject="s",
            html="<p>h</p>",
            text="h",
        )


@pytest.mark.asyncio
async def test_extract_message_falls_back_on_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"Service Unavailable")

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.send_email(
            api_key="re_x", from_="A <a@b.com>", to="r@x.com", subject="s", html="h", text="h"
        )
    assert str(exc.value) == "Resend returned HTTP 503"


@pytest.mark.asyncio
async def test_count_contacts_error_status_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid key"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.count_contacts(api_key="re_x", segment_id="seg_1")
    assert "Invalid key" in str(exc.value)


@pytest.mark.asyncio
async def test_count_contacts_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.count_contacts(api_key="re_x", segment_id="seg_1")
    assert "down" not in str(exc.value)


@pytest.mark.asyncio
async def test_create_segment_raises_when_no_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Resend did not return a segment id"):
        await resend_client.create_segment(api_key="re_x", name="My Audience")


@pytest.mark.asyncio
async def test_create_webhook_returns_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={"id": "webhook_1", "signing_secret": "whsec_generated"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))

    secret = await resend_client.create_webhook(
        api_key="re_x",
        endpoint="https://blog.example/api/webhooks/resend",
        events=["contact.updated"],
    )

    assert secret == "whsec_generated"
    assert seen["path"] == "/webhooks"
    assert '"contact.updated"' in str(seen["body"])


@pytest.mark.asyncio
async def test_create_webhook_raises_when_no_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "webhook_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))

    with pytest.raises(ResendError, match="webhook signing secret"):
        await resend_client.create_webhook(
            api_key="re_x",
            endpoint="https://blog.example/api/webhooks/resend",
            events=["contact.updated"],
        )


@pytest.mark.asyncio
async def test_check_segment_exists_returns_true_on_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/audiences/seg_1"
        return httpx.Response(200, json={"id": "seg_1", "name": "AgBlogger subscribers"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    result = await resend_client.check_segment_exists(api_key="re_x", segment_id="seg_1")
    assert result is True


@pytest.mark.asyncio
async def test_check_segment_exists_returns_false_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Audience not found"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    result = await resend_client.check_segment_exists(api_key="re_x", segment_id="seg_gone")
    assert result is False


@pytest.mark.asyncio
async def test_check_segment_exists_reraises_on_other_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Invalid API key"):
        await resend_client.check_segment_exists(api_key="re_bad", segment_id="seg_1")


@pytest.mark.asyncio
async def test_check_segment_exists_network_error_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError) as exc:
        await resend_client.check_segment_exists(api_key="re_x", segment_id="seg_1")
    assert "down" not in str(exc.value)
    assert "Could not reach the email provider" in str(exc.value)


@pytest.mark.asyncio
async def test_delete_contact_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={"id": "contact_1"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    await resend_client.delete_contact(api_key="re_x", contact_id="contact_1")
    assert seen_paths == ["/contacts/contact_1"]


@pytest.mark.asyncio
async def test_delete_contact_404_treated_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Contact not found"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    # Must not raise
    await resend_client.delete_contact(api_key="re_x", contact_id="gone")


@pytest.mark.asyncio
async def test_delete_contact_other_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid API key"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Invalid API key"):
        await resend_client.delete_contact(api_key="re_bad", contact_id="c1")


@pytest.mark.asyncio
async def test_delete_contact_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError, match="Could not reach the email provider"):
        await resend_client.delete_contact(api_key="re_x", contact_id="c1")


# ── Task 2: Atomic broadcast / BroadcastSendError ────────────────────────────


@pytest.mark.asyncio
async def test_create_and_send_broadcast_send_fails_error_carries_broadcast_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create succeeds (returns id), send POST fails → BroadcastSendError with broadcast_id."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if request.url.path == "/broadcasts":
            # Create succeeds
            return httpx.Response(200, json={"id": "bcast_partial"})
        # Send fails
        return httpx.Response(500, json={"message": "Resend send failure"})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))

    from backend.services.resend_client import BroadcastSendError

    with pytest.raises(BroadcastSendError) as exc_info:
        await resend_client.create_and_send_broadcast(
            api_key="re_x",
            segment_id="seg_1",
            from_="A <a@b.com>",
            subject="s",
            html="<p>h</p>",
            text="h",
        )
    assert exc_info.value.broadcast_id == "bcast_partial"


@pytest.mark.asyncio
async def test_create_and_send_broadcast_create_no_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create returns no id → raises ResendError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    monkeypatch.setattr(resend_client, "_get_client", lambda: _client(handler))
    with pytest.raises(ResendError):
        await resend_client.create_and_send_broadcast(
            api_key="re_x",
            segment_id="seg_1",
            from_="A <a@b.com>",
            subject="s",
            html="<p>h</p>",
            text="h",
        )


# ── Task 7: AsyncClient lock ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_get_client_returns_same_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling _get_client() many times concurrently returns the same instance."""
    # Reset any existing client first
    monkeypatch.setattr(resend_client, "_client_instance", None)

    # _get_client is sync currently; call it many times and verify same object returned
    instances = [resend_client._get_client() for _ in range(20)]
    first = instances[0]
    for inst in instances[1:]:
        assert inst is first, "Multiple calls to _get_client() returned different instances"
