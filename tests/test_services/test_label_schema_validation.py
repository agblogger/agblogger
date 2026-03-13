"""Tests for label schema validation (Issues 31, 32)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.auth import LoginRequest
from backend.schemas.label import LabelCreate, LabelUpdate


class TestLabelCreateValidation:
    def test_valid_label(self) -> None:
        label = LabelCreate(id="my-label")
        assert label.id == "my-label"

    def test_label_with_names(self) -> None:
        label = LabelCreate(id="swe", names=["software engineering"])
        assert label.names == ["software engineering"]

    def test_empty_names_list_accepted(self) -> None:
        label = LabelCreate(id="swe", names=[])
        assert label.names == []

    def test_empty_name_rejected(self) -> None:
        """Issue 32: Empty name strings should be rejected."""
        with pytest.raises(ValidationError, match="empty or whitespace"):
            LabelCreate(id="test", names=[""])

    def test_whitespace_name_rejected(self) -> None:
        """Issue 32: Whitespace-only names should be rejected."""
        with pytest.raises(ValidationError, match="empty or whitespace"):
            LabelCreate(id="test", names=["   "])

    def test_mixed_valid_invalid_names_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty or whitespace"):
            LabelCreate(id="test", names=["valid", ""])

    def test_uppercase_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LabelCreate(id="UPPER")

    def test_leading_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LabelCreate(id="-bad")

    def test_spaces_in_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LabelCreate(id="has space")

    def test_valid_hyphenated_id(self) -> None:
        label = LabelCreate(id="my-label-1")
        assert label.id == "my-label-1"


class TestLabelUpdateValidation:
    def test_empty_name_rejected(self) -> None:
        """Issue 32: Empty strings in updates should be rejected."""
        with pytest.raises(ValidationError, match="empty or whitespace"):
            LabelUpdate(names=[""])

    def test_empty_names_list_accepted(self) -> None:
        update = LabelUpdate(names=[], parents=["parent-id"])
        assert update.names == []
        assert update.parents == ["parent-id"]

    def test_valid_update(self) -> None:
        update = LabelUpdate(names=["new name"], parents=["parent-id"])
        assert update.names == ["new name"]
        assert update.parents == ["parent-id"]


class TestLoginRequestValidation:
    def test_username_max_length(self) -> None:
        """Issue 31: Username max_length should be 50, not 100."""
        with pytest.raises(ValidationError):
            LoginRequest(username="a" * 51, password="test")

    def test_username_at_max_length(self) -> None:
        login = LoginRequest(username="a" * 50, password="test")
        assert len(login.username) == 50

    def test_empty_username_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LoginRequest(username="", password="test")
