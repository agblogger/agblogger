"""Property-based tests for URL rewriting and path safety boundaries."""

from __future__ import annotations

import posixpath
import re
import string
from typing import TYPE_CHECKING

from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.api.content import _validate_path
from backend.api.sync import _resolve_safe_path
from backend.pandoc.renderer import rewrite_relative_urls
from cli.sync_client import _is_safe_local_path

if TYPE_CHECKING:
    from pathlib import Path

PROPERTY_SETTINGS = settings(
    max_examples=220,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

_SEGMENT = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-_",
    min_size=1,
    max_size=10,
)
_SKIP_PREFIXES = ("/", "#", "data:", "http:", "https:", "mailto:", "tel:")
_SKIP_VALUES = st.sampled_from(
    [
        "/about",
        "#section",
        "data:image/png;base64,abc123",
        "http://example.com/path",
        "https://example.com/path",
        "mailto:user@example.com",
        "tel:+123456789",
    ]
)


@st.composite
def _post_file_path(draw: st.DrawFn) -> str:
    return "posts/" + draw(_SEGMENT) + "/" + draw(_SEGMENT) + "/index.md"


@st.composite
def _non_skip_relative_url(draw: st.DrawFn) -> str:
    start = draw(st.sampled_from(["img.png", "doc.pdf", "assets", "nested", "x-y", "v1"]))
    tail = draw(
        st.lists(
            st.sampled_from(["img.png", "doc.pdf", "nested", ".", "..", "asset"]),
            max_size=4,
        )
    )
    value = "/".join([start, *tail])
    if value.startswith(_SKIP_PREFIXES):
        value = value.lstrip("./")
    return value


@st.composite
def _raw_path(draw: st.DrawFn) -> str:
    part = st.sampled_from(
        [
            "posts",
            "assets",
            "index.toml",
            "labels.toml",
            "etc",
            "..",
            ".",
            "",
            "file.md",
            "subdir",
            "..%2Fescape",
        ]
    )
    parts = draw(st.lists(part, min_size=1, max_size=7))
    path = "/".join(parts)
    if draw(st.booleans()):
        path = "/" + path
    return path


@st.composite
def _safe_content_path(draw: st.DrawFn) -> str:
    prefix = draw(st.sampled_from(["posts", "assets"]))
    segments = draw(st.lists(_SEGMENT, min_size=1, max_size=4))
    return prefix + "/" + "/".join(segments)


def _extract_attr_value(html: str) -> str:
    match = re.search(r"""(?:src|href)=(["'])([^"']*)\1""", html)
    assert match is not None
    return match.group(2)


class TestUrlRewritingProperties:
    @PROPERTY_SETTINGS
    @given(
        file_path=_post_file_path(),
        attr=st.sampled_from(["src", "href"]),
        quote=st.sampled_from(['"', "'"]),
        value=_non_skip_relative_url(),
    )
    def test_relative_urls_rewrite_to_expected_safe_targets(
        self,
        file_path: str,
        attr: str,
        quote: str,
        value: str,
    ) -> None:
        html = f"<a {attr}={quote}{value}{quote}>"
        rewritten = rewrite_relative_urls(html, file_path)

        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(file_path), value.removeprefix("./"))
        )
        if resolved.startswith(".."):
            assert rewritten == html
            return

        if resolved.startswith("posts/"):
            short = resolved.removeprefix("posts/")
            expected = f"<a {attr}={quote}/post/{short}{quote}>"
        else:
            expected = f"<a {attr}={quote}/api/content/{resolved}{quote}>"
        assert rewritten == expected
        assert "/.." not in rewritten

    @PROPERTY_SETTINGS
    @given(
        file_path=_post_file_path(),
        attr=st.sampled_from(["src", "href"]),
        quote=st.sampled_from(['"', "'"]),
        value=_SKIP_VALUES,
    )
    def test_skip_prefix_urls_are_not_rewritten(
        self,
        file_path: str,
        attr: str,
        quote: str,
        value: str,
    ) -> None:
        html = f"<a {attr}={quote}{value}{quote}>"
        rewritten = rewrite_relative_urls(html, file_path)
        assert rewritten == html

    @PROPERTY_SETTINGS
    @given(
        file_path=_post_file_path(),
        attrs=st.lists(
            st.tuples(
                st.sampled_from(["src", "href"]),
                st.sampled_from(['"', "'"]),
                st.one_of(_non_skip_relative_url(), _SKIP_VALUES),
            ),
            min_size=1,
            max_size=8,
        ),
    )
    def test_rewrite_relative_urls_is_idempotent(
        self,
        file_path: str,
        attrs: list[tuple[str, str, str]],
    ) -> None:
        html = " ".join(f"<x {attr}={quote}{value}{quote}></x>" for attr, quote, value in attrs)
        once = rewrite_relative_urls(html, file_path)
        twice = rewrite_relative_urls(once, file_path)
        assert twice == once


class TestPathBoundaryProperties:
    @PROPERTY_SETTINGS
    @given(file_path=_raw_path())
    def test_sync_resolve_safe_path_never_returns_outside_root(
        self,
        tmp_path: Path,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        (content_dir / "assets").mkdir(parents=True, exist_ok=True)

        try:
            resolved = _resolve_safe_path(content_dir, file_path)
        except HTTPException as exc:
            assert exc.status_code in {400, 403}
        else:
            assert resolved.is_relative_to(content_dir.resolve())

    @PROPERTY_SETTINGS
    @given(file_path=_raw_path())
    def test_cli_is_safe_local_path_never_returns_outside_root(
        self,
        tmp_path: Path,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        content_dir.mkdir(parents=True, exist_ok=True)

        resolved = _is_safe_local_path(content_dir, file_path)
        if resolved is None:
            return
        assert resolved.is_relative_to(content_dir.resolve())

    @PROPERTY_SETTINGS
    @given(file_path=_raw_path())
    def test_content_validate_path_never_returns_outside_root(
        self,
        tmp_path: Path,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        (content_dir / "assets").mkdir(parents=True, exist_ok=True)

        try:
            resolved = _validate_path(file_path, content_dir)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            assert resolved.is_relative_to(content_dir.resolve())
            assert file_path.startswith(("posts/", "assets/"))

    @PROPERTY_SETTINGS
    @given(file_path=_safe_content_path())
    def test_generated_safe_paths_are_accepted_by_all_resolvers(
        self,
        tmp_path: Path,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        (content_dir / "assets").mkdir(parents=True, exist_ok=True)

        resolved_content = _validate_path(file_path, content_dir)
        resolved_sync = _resolve_safe_path(content_dir, file_path)
        resolved_cli = _is_safe_local_path(content_dir, file_path)

        assert resolved_cli is not None
        assert resolved_content == resolved_sync
        assert resolved_cli == (content_dir / file_path).resolve()
        assert resolved_content.is_relative_to(content_dir.resolve())
