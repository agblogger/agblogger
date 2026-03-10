"""Property-based tests for front matter merge and normalization logic."""

from __future__ import annotations

import string
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import frontmatter as fm
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.filesystem.frontmatter import RECOGNIZED_FIELDS
from backend.services.datetime_service import format_datetime
from backend.services.sync_service import FileEntry, merge_frontmatter, normalize_post_frontmatter

if TYPE_CHECKING:
    from pathlib import Path

GENERAL_SETTINGS = settings(
    max_examples=220,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
IO_SETTINGS = settings(
    max_examples=90,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

_TEXT_ALPHA = string.ascii_letters + string.digits + " -_"
_SEGMENT = st.text(alphabet=string.ascii_lowercase + string.digits + "-_", min_size=1, max_size=12)
_TITLE_TEXT = st.text(alphabet=_TEXT_ALPHA, min_size=1, max_size=40).map(str.strip).filter(bool)
_BODY_TEXT = st.text(alphabet=_TEXT_ALPHA + "\n", min_size=0, max_size=180)
_LABEL_VALUE = st.text(
    alphabet=string.ascii_lowercase + string.digits + "#_-",
    min_size=0,
    max_size=10,
)
_LABEL_LIST = st.lists(_LABEL_VALUE, max_size=8)
_UNKNOWN_KEYS = ("custom_field", "another_key", "x_meta")
_ALL_KEYS = ("title", "author", "created_at", "draft", "labels", "modified_at", *_UNKNOWN_KEYS)
_CONFLICT_FIELDS = {"title", "author", "created_at", "draft"}

_FROZEN_NOW = datetime(2026, 2, 18, 12, 0, 0, tzinfo=UTC)
_FROZEN_TIMESTAMP = format_datetime(_FROZEN_NOW)


def _metadata_value_strategy(key: str) -> st.SearchStrategy[object]:
    if key in {"title", "author"} or key in _UNKNOWN_KEYS:
        return st.one_of(
            st.text(alphabet=_TEXT_ALPHA, min_size=0, max_size=40),
            st.integers(min_value=-50, max_value=50),
            st.booleans(),
            st.none(),
        )
    if key in {"created_at", "modified_at"}:
        return st.one_of(
            st.datetimes(timezones=st.just(UTC)),
            st.dates(),
            st.text(alphabet=_TEXT_ALPHA + ":+", min_size=1, max_size=35),
            st.integers(min_value=0, max_value=100),
            st.none(),
        )
    if key == "draft":
        return st.one_of(
            st.booleans(),
            st.text(alphabet=string.ascii_letters, min_size=0, max_size=12),
            st.integers(min_value=-3, max_value=3),
            st.none(),
        )
    if key == "labels":
        return st.one_of(
            st.lists(_LABEL_VALUE, max_size=8),
            st.text(alphabet=_TEXT_ALPHA, min_size=0, max_size=20),
            st.integers(min_value=0, max_value=5),
            st.none(),
        )
    msg = f"Unexpected key strategy request: {key}"
    raise AssertionError(msg)


@st.composite
def _frontmatter_dict(draw: st.DrawFn) -> dict[str, object]:
    keys = draw(st.lists(st.sampled_from(_ALL_KEYS), unique=True, max_size=len(_ALL_KEYS)))
    metadata: dict[str, object] = {}
    for key in keys:
        metadata[key] = draw(_metadata_value_strategy(key))
    return metadata


@st.composite
def _post_body(draw: st.DrawFn) -> str:
    content = draw(_BODY_TEXT) or "Body"
    if draw(st.booleans()):
        heading = draw(_TITLE_TEXT)
        return f"# {heading}\n\n{content}\n"
    return f"{content}\n"


@st.composite
def _safe_post_path(draw: st.DrawFn) -> str:
    if draw(st.booleans()):
        folder = draw(st.lists(_SEGMENT, min_size=1, max_size=2))
        return "posts/" + "/".join(folder) + "/index.md"
    name = draw(_SEGMENT)
    return f"posts/{name}.md"


@st.composite
def _traversal_post_path(draw: st.DrawFn) -> str:
    escape_depth = draw(st.integers(min_value=2, max_value=5))
    name = draw(_SEGMENT)
    return "posts/" + ("../" * escape_depth) + f"{name}.md"


def _serialize_post(metadata: dict[str, object], body: str) -> str:
    return fm.dumps(fm.Post(body, **metadata)) + "\n"


def _write_raw_post(content_dir: Path, file_path: str, raw_content: str) -> None:
    full_path = content_dir / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(raw_content, encoding="utf-8")


class TestMergeFrontmatterProperties:
    @GENERAL_SETTINGS
    @given(server=_frontmatter_dict(), client=_frontmatter_dict())
    def test_merge_without_base_returns_server_and_expected_conflicts(
        self,
        server: dict[str, object],
        client: dict[str, object],
    ) -> None:
        result = merge_frontmatter(None, server, client)

        expected_conflicts = [
            key
            for key in ("title", "author", "created_at", "draft")
            if key in server and key in client and server.get(key) != client.get(key)
        ]
        assert result.merged == dict(server)
        assert result.field_conflicts == expected_conflicts

    @GENERAL_SETTINGS
    @given(base=_frontmatter_dict(), server=_frontmatter_dict(), client=_frontmatter_dict())
    def test_merge_with_base_never_emits_modified_at_and_conflicts_are_supported(
        self,
        base: dict[str, object],
        server: dict[str, object],
        client: dict[str, object],
    ) -> None:
        result = merge_frontmatter(base, server, client)

        assert "modified_at" not in result.merged
        assert set(result.field_conflicts).issubset(_CONFLICT_FIELDS)
        assert len(result.field_conflicts) == len(set(result.field_conflicts))

    @GENERAL_SETTINGS
    @given(base=_frontmatter_dict(), server=_frontmatter_dict(), client=_frontmatter_dict())
    def test_labels_are_sorted_and_unique_when_present(
        self,
        base: dict[str, object],
        server: dict[str, object],
        client: dict[str, object],
    ) -> None:
        result = merge_frontmatter(base, server, client)
        if "labels" not in result.merged:
            return
        labels = result.merged["labels"]
        assert isinstance(labels, list)
        assert labels == sorted(set(labels))

    @GENERAL_SETTINGS
    @given(base_labels=_LABEL_LIST, server_labels=_LABEL_LIST, client_labels=_LABEL_LIST)
    def test_labels_follow_set_delta_merge_semantics(
        self,
        base_labels: list[str],
        server_labels: list[str],
        client_labels: list[str],
    ) -> None:
        result = merge_frontmatter(
            {"labels": base_labels},
            {"labels": server_labels},
            {"labels": client_labels},
        )

        base_set = set(base_labels)
        server_set = set(server_labels)
        client_set = set(client_labels)
        expected = sorted(
            (base_set | (server_set - base_set) | (client_set - base_set))
            - (base_set - server_set)
            - (base_set - client_set)
        )
        assert result.merged["labels"] == expected


class TestNormalizeFrontmatterProperties:
    @IO_SETTINGS
    @given(
        metadata=_frontmatter_dict(),
        body=_post_body(),
        file_path=_safe_post_path(),
    )
    def test_new_post_normalization_preserves_unknown_fields_and_backfills_required_fields(
        self,
        tmp_path: Path,
        metadata: dict[str, object],
        body: str,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        _write_raw_post(content_dir, file_path, _serialize_post(metadata, body))

        with patch("backend.services.sync_service.now_utc", return_value=_FROZEN_NOW):
            warnings = normalize_post_frontmatter(
                uploaded_files=[file_path],
                old_manifest={},
                content_dir=content_dir,
            )

        post = fm.loads((content_dir / file_path).read_text(encoding="utf-8"))
        assert "created_at" in post.metadata
        assert "modified_at" in post.metadata
        assert isinstance(post.get("title"), str)
        assert post["title"].strip() != ""

        unknown_keys = [key for key in metadata if key not in RECOGNIZED_FIELDS]
        for key in unknown_keys:
            assert key in post.metadata
            assert any(f"'{key}'" in warning for warning in warnings)

    @IO_SETTINGS
    @given(
        metadata=_frontmatter_dict(),
        body=_post_body(),
        file_path=_safe_post_path(),
    )
    def test_edited_post_always_refreshes_modified_at(
        self,
        tmp_path: Path,
        metadata: dict[str, object],
        body: str,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        _write_raw_post(content_dir, file_path, _serialize_post(metadata, body))
        old_manifest = {
            file_path: FileEntry(
                file_path=file_path,
                content_hash="hash",
                file_size=123,
                file_mtime="1.0",
            )
        }

        with patch("backend.services.sync_service.now_utc", return_value=_FROZEN_NOW):
            warnings = normalize_post_frontmatter(
                uploaded_files=[file_path],
                old_manifest=old_manifest,
                content_dir=content_dir,
            )

        post = fm.loads((content_dir / file_path).read_text(encoding="utf-8"))
        assert post["modified_at"] == _FROZEN_TIMESTAMP
        assert "created_at" in post.metadata
        assert isinstance(post.get("title"), str)
        assert post["title"].strip() != ""

        unknown_keys = [key for key in metadata if key not in RECOGNIZED_FIELDS]
        for key in unknown_keys:
            assert key in post.metadata
            assert any(f"'{key}'" in warning for warning in warnings)

    @IO_SETTINGS
    @given(file_path=_traversal_post_path())
    def test_traversal_paths_are_rejected_without_side_effects(
        self,
        tmp_path: Path,
        file_path: str,
    ) -> None:
        content_dir = tmp_path / "content"
        (content_dir / "posts").mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside.md"
        original_outside = "outside sentinel"
        outside.write_text(original_outside, encoding="utf-8")

        with patch("backend.services.sync_service.now_utc", return_value=_FROZEN_NOW):
            warnings = normalize_post_frontmatter(
                uploaded_files=[file_path],
                old_manifest={},
                content_dir=content_dir,
            )

        assert any("invalid path" in warning for warning in warnings)
        assert outside.read_text(encoding="utf-8") == original_outside
