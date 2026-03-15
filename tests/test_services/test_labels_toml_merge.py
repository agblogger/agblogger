"""Tests for semantic labels.toml merging during sync."""

from __future__ import annotations

import tomllib

import tomli_w

from backend.services.sync_service import merge_labels_toml


def _make_labels_toml(labels: dict[str, dict[str, list[str]]]) -> str:
    """Build a labels.toml string from a simplified dict.

    Each key is a label id, each value has optional 'names' and 'parents' lists.
    """
    toml_data: dict[str, dict[str, dict[str, list[str]]]] = {"labels": {}}
    for label_id, fields in labels.items():
        entry: dict[str, list[str]] = {}
        if "names" in fields:
            entry["names"] = fields["names"]
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
        assert set(merged["swe"]["names"]) == {"software engineering", "SWE"}

    def test_client_adds_name(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering", "coding"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering", "coding"}

    def test_both_add_different_names(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering", "SWE"]}})
        client = _make_labels_toml({"swe": {"names": ["software engineering", "coding"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering", "SWE", "coding"}

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
        assert set(merged["swe"]["names"]) == {"a", "c"}

    def test_parents_set_merge(self) -> None:
        base = _make_labels_toml({"swe": {"names": [], "parents": ["#cs"]}})
        server = _make_labels_toml({"swe": {"names": [], "parents": ["#cs", "#eng"]}})
        client = _make_labels_toml({"swe": {"names": [], "parents": ["#cs", "#math"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["parents"]) == {"#cs", "#eng", "#math"}

    def test_server_adds_new_label(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "math": {"names": ["mathematics"]},
        })
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "math" in merged
        assert set(merged["math"]["names"]) == {"mathematics"}

    def test_client_adds_new_label(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "physics": {"names": ["physics"]},
        })
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "physics" in merged

    def test_both_add_same_label_different_names(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        server = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "math": {"names": ["mathematics"]},
        })
        client = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "math": {"names": ["maths"]},
        })
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["math"]["names"]) == {"mathematics", "maths"}

    def test_server_removes_label(self) -> None:
        base = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "old": {"names": ["old label"]},
        })
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "old": {"names": ["old label"]},
        })
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "old" not in merged

    def test_client_removes_label(self) -> None:
        base = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "old": {"names": ["old label"]},
        })
        server = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "old": {"names": ["old label"]},
        })
        client = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert "old" not in merged

    def test_no_base_returns_server(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["coding"]}})
        result = merge_labels_toml(None, server, client)
        assert result.merged_content == server

    def test_no_conflicts_reported(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        client = _make_labels_toml({"swe": {"names": ["a", "c"]}})
        result = merge_labels_toml(base, server, client)
        assert result.field_conflicts == []

    def test_multiple_labels_merged_independently(self) -> None:
        base = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "cs": {"names": ["computer science"]},
        })
        server = _make_labels_toml({
            "swe": {"names": ["software engineering", "SWE"]},
            "cs": {"names": ["computer science"]},
        })
        client = _make_labels_toml({
            "swe": {"names": ["software engineering"]},
            "cs": {"names": ["computer science", "CS"]},
        })
        result = merge_labels_toml(base, server, client)
        merged = _parse_merged(result.merged_content)
        assert set(merged["swe"]["names"]) == {"software engineering", "SWE"}
        assert set(merged["cs"]["names"]) == {"computer science", "CS"}

    def test_malformed_base_returns_server(self) -> None:
        server = _make_labels_toml({"swe": {"names": ["software engineering"]}})
        client = _make_labels_toml({"swe": {"names": ["coding"]}})
        result = merge_labels_toml("not valid toml {{{{", server, client)
        assert result.merged_content == server

    def test_malformed_server_returns_server_raw(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = "not valid toml {{{{"
        client = _make_labels_toml({"swe": {"names": ["b"]}})
        result = merge_labels_toml(base, server, client)
        assert result.merged_content == server

    def test_malformed_client_returns_server(self) -> None:
        base = _make_labels_toml({"swe": {"names": ["a"]}})
        server = _make_labels_toml({"swe": {"names": ["a", "b"]}})
        result = merge_labels_toml(base, server, "not valid toml {{{{")
        assert result.merged_content == server
