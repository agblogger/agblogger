"""Tests for AssetInfo schema field constraints.

Ensures that AssetInfo enforces:
- name must be non-empty (min_length=1)
- size must be non-negative (ge=0)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.schemas.post import AssetInfo


class TestAssetInfoConstraints:
    """AssetInfo must enforce field constraints on name and size."""

    def test_valid_asset_info(self) -> None:
        """Valid AssetInfo should be created without error."""
        asset = AssetInfo(name="photo.png", size=1024, is_image=True)
        assert asset.name == "photo.png"
        assert asset.size == 1024
        assert asset.is_image is True

    def test_zero_size_accepted(self) -> None:
        """Zero-byte files should be accepted."""
        asset = AssetInfo(name="empty.txt", size=0, is_image=False)
        assert asset.size == 0

    def test_empty_name_rejected(self) -> None:
        """An empty name should be rejected."""
        with pytest.raises(ValidationError, match="name"):
            AssetInfo(name="", size=100, is_image=False)

    def test_negative_size_rejected(self) -> None:
        """A negative size should be rejected."""
        with pytest.raises(ValidationError, match="size"):
            AssetInfo(name="file.txt", size=-1, is_image=False)
