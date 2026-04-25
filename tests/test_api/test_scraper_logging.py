"""Integration tests for the social-scraper request/response logging middleware.

Diagnostic middleware that logs request and response details for any request
whose User-Agent matches a known social-preview scraper. Used to investigate
cases where Facebook's Sharing Debugger reports failures the origin can't
reproduce with manual test requests.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest

from backend.config import Settings
from tests.conftest import create_test_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from httpx import AsyncClient


@pytest.fixture
def scraper_settings(tmp_content_dir: Path, tmp_path: Path) -> Settings:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        '<html><head><title>B</title></head><body><div id="root"></div></body></html>'
    )
    db_path = tmp_path / "test.db"
    return Settings(
        secret_key="test-secret-key-with-at-least-32-characters",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{db_path}",
        content_dir=tmp_content_dir,
        frontend_dir=frontend_dir,
        admin_username="admin",
        admin_password="admin123",
    )


@pytest.fixture
async def client(scraper_settings: Settings) -> AsyncGenerator[AsyncClient]:
    async with create_test_client(scraper_settings) as ac:
        yield ac


def _scraper_log_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    prefixes = ("scraper-request", "scraper-response")
    return [r for r in caplog.records if r.message.startswith(prefixes)]


def _request_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    matches = [r for r in caplog.records if r.message.startswith("scraper-request")]
    assert matches, "expected exactly one scraper-request log record"
    return matches[0]


def _response_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    matches = [r for r in caplog.records if r.message.startswith("scraper-response")]
    assert matches, "expected exactly one scraper-response log record"
    return matches[0]


class TestScraperLogMiddleware:
    async def test_logs_facebookexternalhit_request_and_response(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            resp = await client.get(
                "/robots.txt",
                headers={"User-Agent": "facebookexternalhit/1.1"},
            )

        assert resp.status_code == 200
        records = _scraper_log_records(caplog)
        assert len(records) == 2
        request_record = _request_record(caplog)
        response_record = _response_record(caplog)
        assert "method=GET" in request_record.message
        assert "path=/robots.txt" in request_record.message
        assert "facebookexternalhit" in request_record.message.lower()
        assert "status=200" in response_record.message
        assert "body_size=" in response_record.message

    async def test_logs_for_each_known_scraper_user_agent(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        for ua in (
            "facebookexternalhit/1.1",
            "facebookcatalog/1.0",
            "meta-externalagent/1.1",
            "Twitterbot/1.0",
            "LinkedInBot/1.0",
        ):
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="backend.main"):
                await client.get("/robots.txt", headers={"User-Agent": ua})
            assert _scraper_log_records(caplog), f"no log emitted for UA {ua!r}"

    async def test_does_not_log_normal_browser_request(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            await client.get(
                "/robots.txt",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/123.0.0.0 Safari/537.36"
                    ),
                },
            )
        assert not _scraper_log_records(caplog)

    async def test_does_not_log_when_user_agent_missing(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            # httpx adds its own User-Agent by default, so explicitly set empty.
            await client.get("/robots.txt", headers={"User-Agent": ""})
        assert not _scraper_log_records(caplog)

    async def test_logs_head_method_as_received(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # HEAD-to-GET conversion happens in an inner middleware; the scraper
        # log must still see the original HEAD method as the wire-level
        # request — that's the diagnostic value of being outermost.
        with caplog.at_level(logging.INFO, logger="backend.main"):
            await client.head(
                "/robots.txt",
                headers={"User-Agent": "facebookexternalhit/1.1"},
            )
        assert "method=HEAD" in _request_record(caplog).message

    async def test_redacts_sensitive_request_headers(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            await client.get(
                "/robots.txt",
                headers={
                    "User-Agent": "facebookexternalhit/1.1",
                    "Cookie": "session=verysecretvalue",
                    "Authorization": "Bearer verysecrettoken",
                },
            )
        request_record = _request_record(caplog)
        # Sensitive header VALUES must not appear; only their lengths.
        assert "verysecretvalue" not in request_record.message
        assert "verysecrettoken" not in request_record.message
        assert "[redacted len=" in request_record.message

    async def test_logged_request_headers_are_valid_json(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            await client.get(
                "/robots.txt",
                headers={"User-Agent": "facebookexternalhit/1.1"},
            )
        request_record = _request_record(caplog)
        # The headers field is logged via json.dumps; locate the JSON object
        # and confirm it parses back into a dict including the user-agent.
        headers_idx = request_record.message.index("headers=") + len("headers=")
        headers_json = request_record.message[headers_idx:]
        parsed = json.loads(headers_json)
        assert isinstance(parsed, dict)
        assert any(k.lower() == "user-agent" for k in parsed)

    async def test_request_id_matches_between_request_and_response_logs(
        self,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="backend.main"):
            await client.get(
                "/robots.txt",
                headers={"User-Agent": "facebookexternalhit/1.1"},
            )
        req_msg = _request_record(caplog).message
        resp_msg = _response_record(caplog).message
        req_id = req_msg.split("id=", 1)[1].split(" ", 1)[0]
        resp_id = resp_msg.split("id=", 1)[1].split(" ", 1)[0]
        assert req_id == resp_id
