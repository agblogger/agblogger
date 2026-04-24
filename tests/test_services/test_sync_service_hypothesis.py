"""Property-based tests for sync planning invariants."""

from __future__ import annotations

import string
from dataclasses import asdict

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.services.sync_service import FileEntry, SyncChange, SyncPlan, compute_sync_plan

PROPERTY_SETTINGS = settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

_SEGMENT = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=8)
_PATH = st.builds(
    lambda parts, ext: "/".join(parts) + f".{ext}",
    st.lists(_SEGMENT, min_size=1, max_size=3),
    st.sampled_from(["md", "txt", "toml", "png"]),
)
_HASH = st.text(alphabet="0123456789abcdef", min_size=1, max_size=16)
_HASH_MANIFEST = st.dictionaries(keys=_PATH, values=_HASH, max_size=10)


def _to_entries(
    hash_map: dict[str, str],
    *,
    size_overrides: dict[str, int] | None = None,
    mtime_overrides: dict[str, str] | None = None,
) -> dict[str, FileEntry]:
    entries: dict[str, FileEntry] = {}
    for path, content_hash in hash_map.items():
        file_size = size_overrides[path] if size_overrides and path in size_overrides else len(path)
        file_mtime = (
            mtime_overrides[path]
            if mtime_overrides and path in mtime_overrides
            else str(len(content_hash) * 1.5)
        )
        entries[path] = FileEntry(
            file_path=path,
            content_hash=content_hash,
            file_size=file_size,
            file_mtime=file_mtime,
        )
    return entries


def _conflict_signature(plan_conflicts: list[SyncChange]) -> set[tuple[str, str, str]]:
    return {
        (conflict.file_path, str(conflict.change_type), conflict.action)
        for conflict in plan_conflicts
    }


def _plan_signature(
    plan: SyncPlan,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[tuple[str, str, str], ...],
    tuple[str, ...],
]:
    return (
        tuple(plan.to_upload),
        tuple(plan.to_download),
        tuple(plan.to_delete_remote),
        tuple(plan.to_delete_local),
        tuple(sorted(_conflict_signature(plan.conflicts))),
        tuple(plan.no_change),
    )


class TestSyncPlanProperties:
    @PROPERTY_SETTINGS
    @given(
        client_hashes=_HASH_MANIFEST,
        manifest_hashes=_HASH_MANIFEST,
        server_hashes=_HASH_MANIFEST,
    )
    def test_each_path_is_classified_once(
        self,
        client_hashes: dict[str, str],
        manifest_hashes: dict[str, str],
        server_hashes: dict[str, str],
    ) -> None:
        client_manifest = _to_entries(client_hashes)
        server_manifest = _to_entries(manifest_hashes)
        server_current = _to_entries(server_hashes)

        plan = compute_sync_plan(client_manifest, server_manifest, server_current)
        all_paths = set(client_manifest) | set(server_manifest) | set(server_current)

        upload = set(plan.to_upload)
        download = set(plan.to_download)
        delete_remote = set(plan.to_delete_remote)
        delete_local = set(plan.to_delete_local)
        conflicts = {conflict.file_path for conflict in plan.conflicts}
        no_change = set(plan.no_change)

        buckets = [upload, download, delete_remote, delete_local, conflicts, no_change]
        union = set().union(*buckets)
        assert union == all_paths

        for index, bucket in enumerate(buckets):
            for other_index, other_bucket in enumerate(buckets):
                if index == other_index:
                    continue
                assert bucket.isdisjoint(other_bucket)

        assert plan.to_upload == sorted(plan.to_upload)
        assert plan.to_download == sorted(plan.to_download)
        assert plan.to_delete_remote == sorted(plan.to_delete_remote)
        assert plan.to_delete_local == sorted(plan.to_delete_local)
        assert [conflict.file_path for conflict in plan.conflicts] == sorted(
            conflict.file_path for conflict in plan.conflicts
        )

    @PROPERTY_SETTINGS
    @given(
        client_hashes=_HASH_MANIFEST,
        manifest_hashes=_HASH_MANIFEST,
        server_hashes=_HASH_MANIFEST,
    )
    def test_swapping_client_and_server_swaps_directional_actions(
        self,
        client_hashes: dict[str, str],
        manifest_hashes: dict[str, str],
        server_hashes: dict[str, str],
    ) -> None:
        client_manifest = _to_entries(client_hashes)
        server_manifest = _to_entries(manifest_hashes)
        server_current = _to_entries(server_hashes)

        forward = compute_sync_plan(client_manifest, server_manifest, server_current)
        reverse = compute_sync_plan(server_current, server_manifest, client_manifest)

        assert set(forward.to_upload) == set(reverse.to_download)
        assert set(forward.to_download) == set(reverse.to_upload)
        assert set(forward.to_delete_remote) == set(reverse.to_delete_local)
        assert set(forward.to_delete_local) == set(reverse.to_delete_remote)
        assert set(forward.no_change) == set(reverse.no_change)
        assert _conflict_signature(forward.conflicts) == _conflict_signature(reverse.conflicts)

    @PROPERTY_SETTINGS
    @given(current_hashes=_HASH_MANIFEST)
    def test_identical_snapshots_produce_no_actions(self, current_hashes: dict[str, str]) -> None:
        current = _to_entries(current_hashes)
        plan = compute_sync_plan(current, current, current)

        assert plan.to_upload == []
        assert plan.to_download == []
        assert plan.to_delete_remote == []
        assert plan.to_delete_local == []
        assert plan.conflicts == []
        assert set(plan.no_change) == set(current)

    @PROPERTY_SETTINGS
    @given(
        client_hashes=_HASH_MANIFEST,
        manifest_hashes=_HASH_MANIFEST,
        server_hashes=_HASH_MANIFEST,
        size_a=st.dictionaries(
            keys=_PATH,
            values=st.integers(min_value=0, max_value=10_000),
            max_size=10,
        ),
        size_b=st.dictionaries(
            keys=_PATH,
            values=st.integers(min_value=0, max_value=10_000),
            max_size=10,
        ),
        mtime_a=st.dictionaries(keys=_PATH, values=st.text(min_size=1, max_size=20), max_size=10),
        mtime_b=st.dictionaries(keys=_PATH, values=st.text(min_size=1, max_size=20), max_size=10),
    )
    def test_sync_plan_depends_only_on_presence_and_hashes(
        self,
        client_hashes: dict[str, str],
        manifest_hashes: dict[str, str],
        server_hashes: dict[str, str],
        size_a: dict[str, int],
        size_b: dict[str, int],
        mtime_a: dict[str, str],
        mtime_b: dict[str, str],
    ) -> None:
        plan_a = compute_sync_plan(
            _to_entries(client_hashes, size_overrides=size_a, mtime_overrides=mtime_a),
            _to_entries(manifest_hashes, size_overrides=size_a, mtime_overrides=mtime_a),
            _to_entries(server_hashes, size_overrides=size_a, mtime_overrides=mtime_a),
        )
        plan_b = compute_sync_plan(
            _to_entries(client_hashes, size_overrides=size_b, mtime_overrides=mtime_b),
            _to_entries(manifest_hashes, size_overrides=size_b, mtime_overrides=mtime_b),
            _to_entries(server_hashes, size_overrides=size_b, mtime_overrides=mtime_b),
        )

        assert _plan_signature(plan_a) == _plan_signature(plan_b)

    @PROPERTY_SETTINGS
    @given(
        client_hashes=_HASH_MANIFEST,
        manifest_hashes=_HASH_MANIFEST,
        server_hashes=_HASH_MANIFEST,
    )
    def test_conflict_actions_are_consistently_merge(
        self,
        client_hashes: dict[str, str],
        manifest_hashes: dict[str, str],
        server_hashes: dict[str, str],
    ) -> None:
        plan = compute_sync_plan(
            _to_entries(client_hashes),
            _to_entries(manifest_hashes),
            _to_entries(server_hashes),
        )
        for conflict in plan.conflicts:
            assert conflict.action == "merge"
            assert asdict(conflict)["change_type"] in {"conflict", "delete_modify_conflict"}
