"""Tests for ZAP hook hardening."""

from __future__ import annotations

import re
from typing import Any, cast

from cli.zap_hooks import _disable_unstable_active_scanners, _off_target_regexes


class _FakeAscan:
    def __init__(self, scanners: list[dict[str, str]]) -> None:
        self._scanners = scanners
        self.disabled: list[tuple[str, str | None]] = []

    def scanners(self, scanpolicyname: str | None = None) -> list[dict[str, str]]:
        return self._scanners

    def disable_scanners(self, ids: str, scanpolicyname: str | None = None) -> object:
        self.disabled.append((ids, scanpolicyname))
        return {}


class _FakeZap:
    def __init__(self, scanners: list[dict[str, str]]) -> None:
        self.ascan = _FakeAscan(scanners)


def test_off_target_regexes_exclude_other_local_ports_but_not_target() -> None:
    regexes = _off_target_regexes("http://host.docker.internal:8080/")

    same_host_regex = next(regex for regex in regexes if "host\\.docker\\.internal" in regex)

    assert re.match(same_host_regex, "http://host.docker.internal:5173/") is not None
    assert re.match(same_host_regex, "http://host.docker.internal:8080/") is None


def test_disable_unstable_active_scanners_disables_dom_xss_only() -> None:
    zap = _FakeZap(
        [
            {"id": "40026", "name": "Cross Site Scripting (DOM Based)"},
            {"id": "99999", "name": "Cross Site Scripting (Reflected)"},
        ]
    )

    _disable_unstable_active_scanners(cast("Any", zap))

    assert zap.ascan.disabled == [("40026", "Default Policy")]
