"""Custom ZAP hooks that keep local scans on the packaged-app target."""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

_CONTEXT_NAME = "agblogger-local"
_MOZILLA_DOMAIN_REGEX = r"^https?://(?:[^/]+\.)?mozilla(?:\.com|\.net|\.org)(?:/.*)?$"
_UNSTABLE_ACTIVE_SCANNER_IDS = ("40026",)


def _zap_common() -> Any:
    return cast("Any", importlib.import_module("zap_common"))


class _ContextApi(Protocol):
    def remove_context(self, _contextname: str) -> object: ...

    def new_context(self, _contextname: str) -> str: ...

    def include_in_context(self, _contextname: str, _regex: str) -> object: ...

    def exclude_from_context(self, _contextname: str, _regex: str) -> object: ...


class _CoreApi(Protocol):
    def exclude_from_proxy(self, _regex: str) -> object: ...


class _SpiderApi(Protocol):
    def exclude_from_scan(self, _regex: str) -> object: ...


class _AjaxSpiderApi(Protocol):
    def set_option_number_of_browsers(self, _value: str) -> object: ...

    def set_option_enable_extensions(self, _value: str) -> object: ...

    def set_option_click_elems_once(self, _value: str) -> object: ...

    def add_excluded_element(
        self,
        _contextname: str,
        _description: str,
        _element: str,
        _xpath: str | None = None,
        _text: str | None = None,
        _attributename: str | None = None,
        _attributevalue: str | None = None,
        _enabled: str | None = None,
    ) -> object: ...


class _AscanApi(Protocol):
    def scanners(self, scanpolicyname: str | None = None) -> list[dict[str, str]]:
        _ = scanpolicyname
        raise NotImplementedError

    def disable_scanners(self, ids: str, scanpolicyname: str | None = None) -> object:
        _ = ids, scanpolicyname
        raise NotImplementedError


class _ZapApi(Protocol):
    context: _ContextApi
    core: _CoreApi
    spider: _SpiderApi
    ascan: _AscanApi

    def __getattr__(self, name: str) -> Any: ...


def _target_port(parts: object) -> int:
    port = getattr(parts, "port", None)
    if port is not None:
        return int(port)
    return 443 if getattr(parts, "scheme", "") == "https" else 80


def _target_origin_regex(target: str) -> str:
    parts = urlsplit(target)
    if parts.hostname is None:
        msg = f"Target URL must include a hostname: {target}"
        raise ValueError(msg)
    scheme = re.escape(parts.scheme)
    host = re.escape(parts.hostname)
    port = _target_port(parts)
    return rf"^{scheme}://{host}:{port}(?:/.*)?$"


def _off_target_regexes(target: str) -> tuple[str, ...]:
    parts = urlsplit(target)
    if parts.hostname is None:
        msg = f"Target URL must include a hostname: {target}"
        raise ValueError(msg)

    port = _target_port(parts)
    local_hosts = ("host.docker.internal", "localhost", "127.0.0.1")
    same_host_excludes = tuple(
        rf"^https?://{re.escape(host)}:(?!{port}(?:/|$))\d+(?:/.*)?$" for host in local_hosts
    )
    return (*same_host_excludes, _MOZILLA_DOMAIN_REGEX)


def _configure_context(zap: _ZapApi, target: str) -> None:
    context_id = zap.context.new_context(_CONTEXT_NAME)
    zap.context.include_in_context(_CONTEXT_NAME, _target_origin_regex(target))
    for regex in _off_target_regexes(target):
        zap.context.exclude_from_context(_CONTEXT_NAME, regex)

    zap_common = _zap_common()
    zap_common.context_name = _CONTEXT_NAME
    zap_common.context_id = context_id
    zap_common.context_users = []
    zap_common.scan_user = None


def _configure_proxy_and_spider_scope(zap: _ZapApi, target: str) -> None:
    for regex in _off_target_regexes(target):
        zap.core.exclude_from_proxy(regex)
        zap.spider.exclude_from_scan(regex)


def _configure_ajax_spider(zap: _ZapApi) -> None:
    ajax_spider = cast("Any", zap.ajaxSpider)
    ajax_spider.set_option_number_of_browsers("1")
    ajax_spider.set_option_enable_extensions("false")
    ajax_spider.set_option_click_elems_once("true")

    # External links and share controls are popup-prone and trigger Crawljax
    # window-handle races in headless Firefox.
    ajax_spider.add_excluded_element(
        _CONTEXT_NAME,
        "external-blank-links",
        "a",
        attributename="target",
        attributevalue="_blank",
        enabled="true",
    )
    ajax_spider.add_excluded_element(
        _CONTEXT_NAME,
        "share-trigger",
        "button",
        attributename="aria-label",
        attributevalue="Share this post",
        enabled="true",
    )
    ajax_spider.add_excluded_element(
        _CONTEXT_NAME,
        "share-email",
        "button",
        attributename="aria-label",
        attributevalue="Share via email",
        enabled="true",
    )


def _disable_unstable_active_scanners(zap: _ZapApi) -> None:
    scanner_ids = {scanner["id"] for scanner in zap.ascan.scanners(scanpolicyname="Default Policy")}
    disabled_ids = [
        scanner_id for scanner_id in _UNSTABLE_ACTIVE_SCANNER_IDS if scanner_id in scanner_ids
    ]
    if not disabled_ids:
        return

    logging.info("Disabling unstable ZAP active scanner(s): %s", ", ".join(disabled_ids))
    zap.ascan.disable_scanners(",".join(disabled_ids), scanpolicyname="Default Policy")


def zap_started(zap: _ZapApi, target: str) -> None:
    """Apply target scoping before ZAP touches the application."""
    _configure_context(zap, target)
    _configure_proxy_and_spider_scope(zap, target)
    _configure_ajax_spider(zap)
    _disable_unstable_active_scanners(zap)
