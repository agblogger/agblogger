"""Property-based tests for TOML label configuration parsing and serialization."""

from __future__ import annotations

import string
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.filesystem.toml_manager import (
    LabelDef,
    parse_labels_config,
    write_labels_config,
)

PROPERTY_SETTINGS = settings(
    max_examples=220,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_LABEL_ID = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-",
    min_size=1,
    max_size=12,
).filter(lambda s: s[0].isalnum())

_LABEL_NAME = st.text(
    alphabet=string.ascii_letters + string.digits + " -",
    min_size=1,
    max_size=30,
)

_LABEL_NAMES = st.lists(_LABEL_NAME, min_size=0, max_size=3)


@st.composite
def _label_defs(draw: st.DrawFn) -> dict[str, LabelDef]:
    """Generate a dictionary of label definitions with valid parent references."""
    ids = draw(st.lists(_LABEL_ID, unique=True, min_size=0, max_size=8))
    result: dict[str, LabelDef] = {}
    for i, label_id in enumerate(ids):
        names = draw(_LABEL_NAMES)
        # Parents can only reference earlier labels (ensures valid refs, avoids cycles)
        possible_parents = ids[:i]
        if possible_parents:
            parents = draw(
                st.lists(
                    st.sampled_from(possible_parents),
                    unique=True,
                    max_size=min(3, len(possible_parents)),
                )
            )
        else:
            parents = []
        result[label_id] = LabelDef(id=label_id, names=names, parents=parents)
    return result


class TestLabelConfigRoundtripProperties:
    @PROPERTY_SETTINGS
    @given(labels=_label_defs())
    def test_write_then_parse_preserves_labels(self, labels: dict[str, LabelDef]) -> None:
        """write_labels_config → parse_labels_config preserves all label definitions."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_labels_config(tmp_path, labels)
            parsed = parse_labels_config(tmp_path)

            assert set(parsed.keys()) == set(labels.keys())
            for label_id, original in labels.items():
                roundtripped = parsed[label_id]
                assert roundtripped.id == original.id
                assert roundtripped.names == original.names
                assert sorted(roundtripped.parents) == sorted(original.parents)

    @PROPERTY_SETTINGS
    @given(labels=_label_defs())
    def test_roundtrip_is_idempotent(self, labels: dict[str, LabelDef]) -> None:
        """Writing, parsing, and writing again produces the same file content."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_labels_config(tmp_path, labels)
            first_content = (tmp_path / "labels.toml").read_text(encoding="utf-8")

            parsed = parse_labels_config(tmp_path)
            write_labels_config(tmp_path, parsed)
            second_content = (tmp_path / "labels.toml").read_text(encoding="utf-8")

            assert first_content == second_content


class TestParentSerializationProperties:
    @PROPERTY_SETTINGS
    @given(label_id=_LABEL_ID, parent_id=_LABEL_ID, names=_LABEL_NAMES)
    def test_single_parent_uses_singular_key(
        self, label_id: str, parent_id: str, names: list[str]
    ) -> None:
        """A label with exactly one parent is written with 'parent' (singular)."""
        if label_id == parent_id:
            return
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            labels = {label_id: LabelDef(id=label_id, names=names, parents=[parent_id])}
            write_labels_config(tmp_path, labels)
            content = (tmp_path / "labels.toml").read_text(encoding="utf-8")
            # Singular "parent" key, not "parents"
            assert "parent = " in content
            assert "parents" not in content

    @PROPERTY_SETTINGS
    @given(
        label_id=_LABEL_ID,
        parent_ids=st.lists(_LABEL_ID, unique=True, min_size=2, max_size=3),
        names=_LABEL_NAMES,
    )
    def test_multiple_parents_uses_plural_key(
        self,
        label_id: str,
        parent_ids: list[str],
        names: list[str],
    ) -> None:
        """A label with 2+ parents is written with 'parents' (plural)."""
        if label_id in parent_ids:
            return
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            labels = {label_id: LabelDef(id=label_id, names=names, parents=parent_ids)}
            write_labels_config(tmp_path, labels)
            content = (tmp_path / "labels.toml").read_text(encoding="utf-8")
            assert "parents = " in content

    @PROPERTY_SETTINGS
    @given(label_id=_LABEL_ID, names=_LABEL_NAMES)
    def test_no_parents_omits_parent_key(self, label_id: str, names: list[str]) -> None:
        """A label with no parents has neither 'parent' nor 'parents' in the TOML."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            labels = {label_id: LabelDef(id=label_id, names=names, parents=[])}
            write_labels_config(tmp_path, labels)
            content = (tmp_path / "labels.toml").read_text(encoding="utf-8")
            assert "parent" not in content


class TestHashPrefixStrippingProperties:
    @PROPERTY_SETTINGS
    @given(label_id=_LABEL_ID, parent_id=_LABEL_ID, names=_LABEL_NAMES)
    def test_hash_prefix_is_stripped_during_parse(
        self, label_id: str, parent_id: str, names: list[str]
    ) -> None:
        """Parent references written with # prefix are parsed without it."""
        if label_id == parent_id:
            return
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            labels = {label_id: LabelDef(id=label_id, names=names, parents=[parent_id])}
            write_labels_config(tmp_path, labels)
            # Verify # is in the file
            content = (tmp_path / "labels.toml").read_text(encoding="utf-8")
            assert f'"#{parent_id}"' in content

            # Parse and verify # is stripped
            parsed = parse_labels_config(tmp_path)
            assert parsed[label_id].parents == [parent_id]


class TestMissingFileProperties:
    def test_missing_file_returns_empty_dict(self) -> None:
        """parse_labels_config returns {} for missing labels.toml."""
        with tempfile.TemporaryDirectory() as tmp:
            assert parse_labels_config(Path(tmp)) == {}
