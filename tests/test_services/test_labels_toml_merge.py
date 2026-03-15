"""Tests for semantic labels.toml merging during sync."""

from __future__ import annotations

import tomllib

import tomli_w

from backend.services.sync_service import merge_labels_toml


def _make_labels_toml(
    labels: dict[str, dict[str, str | list[str]]],
) -> str:
    """Build a labels.toml string from a simplified dict.

    Each key is a label id, each value has optional 'names' and 'parents' lists.
    """
    toml_data: dict[str, dict[str, dict[str, str | list[str]]]] = {"labels": {}}
    for label_id, fields in labels.items():
        entry: dict[str, str | list[str]] = {}
        if "names" in fields:
            entry["names"] = fields["names"]
        if "parent" in fields:
            entry["parent"] = fields["parent"]
        if "parents" in fields:
            entry["parents"] = fields["parents"]
        toml_data["labels"][label_id] = entry
    return tomli_w.dumps(toml_data)


def _parse_merged(content: str) -> dict[str, dict[str, list[str]]]:
    """Parse merged labels.toml content back into a simplified dict."""
    data = tomllib.loads(content)
    result: dict[str, dict[str, list[str]]] = {}
    for label_id, info in data.get("labels", {}).items():
        entry: dict[str, list[str]] = {}
        if "names" in info:
            entry["names"] = info["names"]
        if "parents" in info:
            entry["parents"] = info["parents"]
        result[label_id] = entry
    return result


class TestMergeLabelsToml:
    def test_no_changes(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, base, base)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering"}

    def test_server_adds_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering", "SWE"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["software engineering", "SWE"]

    def test_client_adds_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering", "coding"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["software engineering", "coding"]

    def test_both_add_different_names(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering", "SWE"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering", "coding"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["software engineering", "SWE", "coding"]

    def test_server_removes_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering", "programming"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering", "programming"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering"}

    def test_both_remove_same_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering", "programming"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering"}

    def test_server_adds_client_removes_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b", "c"]}})
        client = _make_labels_toml({"swe": {"names": ["a"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["a", "c"]

    def test_parents_set_merge(self) -> None:
        base = _make_labels_toml({"swe": {"names": [], "parents": ["#cs"]}})
        server = _make_labels_toml({"swe": {"names": [], "parents": ["#cs", "#eng"]}})
        client = _make_labels_toml({"swe": {"names": [], "parents": ["#cs", "#math"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["parents"]) == {"#cs", "#eng", "#math"}

    def test_server_adds_new_label(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "math": {"names": ["mathematics"]},
            }
        )
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "math" in merged
        assert set(merged["math"]["names"]) == {"mathematics"}

    def test_client_adds_new_label(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "physics": {"names": ["physics"]},
            }
        )
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "physics" in merged

    def test_both_add_same_label_different_names(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "math": {"names": ["mathematics"]},
            }
        )
        client = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "math": {"names": ["maths"]},
            }
        )
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["math"]["names"] == ["mathematics", "maths"]

    def test_server_removes_label(self) -> None:
        base = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "old": {"names": ["old label"]},
            }
        )
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "old": {"names": ["old label"]},
            }
        )
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "old" not in merged

    def test_client_removes_label(self) -> None:
        base = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "old": {"names": ["old label"]},
            }
        )
        server = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "old": {"names": ["old label"]},
            }
        )
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "old" not in merged

    def test_no_base_returns_client(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["coding"]}})
        result = merge_labels_toml(None, server, client)
        assert result.merged_content == client
        assert result.field_conflicts == ["_no_base"]

    def test_no_conflicts_reported(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        client = _make_labels_toml({"swe": {"names": ["a", "c"]}})
        result = merge_labels_toml(base, server, client)
        assert result.field_conflicts == []

    def test_multiple_labels_merged_independently(self) -> None:
        base = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "cs": {"names": ["computer science"]},
            }
        )
        server = _make_labels_toml(
            {
                "swe": {"names": ["software engineering", "SWE"]},
                "cs": {"names": ["computer science"]},
            }
        )
        client = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "cs": {"names": ["computer science", "CS"]},
            }
        )
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["software engineering", "SWE"]
        assert merged["cs"]["names"] == ["computer science", "CS"]

    def test_name_merge_preserves_primary_alias_order(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering", "programming"]}})
        server = _make_labels_toml(
            {"swe": {"names": ["software engineering", "programming", "SWE"]}}
        )
        client = _make_labels_toml({"swe": {"names": ["software engineering", "programming"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged["swe"]["names"] == ["software engineering", "programming", "SWE"]

    def test_single_parent_is_preserved_during_merge(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"], "parent": "#cs"}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"], "parent": "#cs"}})
        client = _make_labels_toml(
            {"swe": {"names": ["software engineering", "SWE"], "parent": "#cs"}}
        )
        result = merge_labels_toml(base, server, client)
        merged = tomllib.loads(result.merged_content)
        assert merged["labels"]["swe"]["parent"] == "#cs"
        assert "parents" not in merged["labels"]["swe"]

    def test_malformed_base_returns_client(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["coding"]}})
        result = merge_labels_toml("not valid toml {{{{", server, client)
        assert result.merged_content == client
        assert result.field_conflicts == ["_parse_error"]

    def test_malformed_server_returns_client(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = "not valid toml {{{{"
        client = _make_labels_toml({"swe": {"names": ["b"]}})
        result = merge_labels_toml(base, server, client)
        assert result.merged_content == client
        assert result.field_conflicts == ["_parse_error"]

    def test_malformed_client_returns_client_raw(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        result = merge_labels_toml(base, server, "not valid toml {{{{")
        assert result.merged_content == "not valid toml {{{{"
        assert result.field_conflicts == ["_parse_error"]

    # --- Error-signaling tests (TDD: written to fail before fix) ---

    def test_malformed_server_signals_parse_error(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        client = _make_labels_toml({"swe": {"names": ["b"]}})
        result = merge_labels_toml(base, "not valid toml {{{{", client)
        assert result.field_conflicts == ["_parse_error"]

    def test_malformed_base_signals_parse_error(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["a"]}})
        client = _make_labels_toml({"swe": {"names": ["b"]}})
        result = merge_labels_toml("not valid toml {{{{", server, client)
        assert result.field_conflicts == ["_parse_error"]

    def test_malformed_client_signals_parse_error(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        result = merge_labels_toml(base, server, "not valid toml {{{{")
        assert result.field_conflicts == ["_parse_error"]

    def test_no_base_signals_no_base(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["coding"]}})
        result = merge_labels_toml(None, server, client)
        assert result.field_conflicts == ["_no_base"]

    # --- Behavior-pinning tests for concurrent add+remove of same item ---

    def test_server_adds_client_removes_same_name_removal_wins(self) -> None:
        """Server adds name X, client removes name X from base that has X → X NOT in result."""
        base = _make_labels_toml({"swe": {"names": ["a", "X"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "X", "new"]}})
        client = _make_labels_toml({"swe": {"names": ["a"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "X" not in merged["swe"]["names"]

    def test_server_removes_client_adds_back_same_name_removal_wins(self) -> None:
        """Server removes name X, client adds name X back to base that has X → X NOT in result."""
        base = _make_labels_toml({"swe": {"names": ["a", "X"]}})
        server = _make_labels_toml({"swe": {"names": ["a"]}})
        client = _make_labels_toml({"swe": {"names": ["a", "X", "new"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "X" not in merged["swe"]["names"]

    # --- Edge case behavior-pinning tests ---

    def test_empty_labels_all_sides_produces_empty_result(self) -> None:
        """Empty labels table on all sides → merged result has empty labels."""
        base = _make_labels_toml({})
        server = _make_labels_toml({})
        client = _make_labels_toml({})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged == {}

    def test_both_sides_remove_same_label_simultaneously(self) -> None:
        """Both sides remove the same label → label is removed from merged result."""
        base = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "old": {"names": ["old label"]},
            }
        )
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "old" not in merged

    def test_base_has_labels_server_and_client_empty_removes_all(self) -> None:
        """Base has labels, server and client have empty [labels] tables → all labels removed."""
        base = _make_labels_toml(
            {
                "swe": {"names": ["software engineering"]},
                "cs": {"names": ["computer science"]},
            }
        )
        server = _make_labels_toml({})
        client = _make_labels_toml({})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert merged == {}
