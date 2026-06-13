"""Tests for label validation in PostSave schema.

Ensures that labels in PostSave match the expected label ID format:
lowercase alphanumeric with hyphens, starting with alphanumeric.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.post import PostSave


class TestPostSaveLabelValidation:
    """PostSave.labels should reject invalid label IDs."""

    def test_valid_labels_accepted(self) -> None:
        """Labels matching the label ID pattern should be accepted."""
        post = PostSave(title="Test", body="Content", labels=["swe", "cs", "my-label-1"])
        assert post.labels == ["swe", "cs", "my-label-1"]

    def test_label_with_underscore_accepted(self) -> None:
        """Labels with underscores should be accepted."""
        post = PostSave(title="Test", body="Content", labels=["my_label", "swe_cs"])
        assert post.labels == ["my_label", "swe_cs"]

    def test_label_with_mixed_hyphen_underscore_accepted(self) -> None:
        """Labels mixing hyphens and underscores should be accepted."""
        post = PostSave(title="Test", body="Content", labels=["my-label_v2"])
        assert post.labels == ["my-label_v2"]

    def test_label_starting_with_underscore_rejected(self) -> None:
        """Labels starting with an underscore should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["_bad"])

    def test_empty_labels_list_accepted(self) -> None:
        """An empty labels list should be accepted."""
        post = PostSave(title="Test", body="Content", labels=[])
        assert post.labels == []

    def test_empty_string_label_rejected(self) -> None:
        """An empty string label should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=[""])

    def test_whitespace_only_label_rejected(self) -> None:
        """A whitespace-only label should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["  "])

    def test_label_with_hash_prefix_rejected(self) -> None:
        """Labels with # prefix should be rejected (stored without # in PostSave)."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["#swe"])

    def test_label_with_special_characters_rejected(self) -> None:
        """Labels with special characters (other than hyphen) should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["swe@foo"])

    def test_label_with_uppercase_accepted(self) -> None:
        """Labels with uppercase characters should be accepted."""
        post = PostSave(title="Test", body="Content", labels=["SWE", "MyLabel"])
        assert post.labels == ["SWE", "MyLabel"]

    def test_label_starting_with_hyphen_rejected(self) -> None:
        """Labels starting with a hyphen should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["-swe"])

    def test_label_with_spaces_rejected(self) -> None:
        """Labels containing spaces should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["my label"])

    def test_mixed_valid_and_invalid_rejected(self) -> None:
        """If any label is invalid, the whole list should be rejected."""
        with pytest.raises(ValidationError, match="label"):
            PostSave(title="Test", body="Content", labels=["swe", ""])
