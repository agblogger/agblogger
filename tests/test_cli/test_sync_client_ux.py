"""Tests for sync client UX improvements: confirmation, error handling."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cli.sync_client import (
    CONFIG_FILE,
    confirm_sync,
    format_plan_summary,
    has_pending_changes,
    load_config,
    login_interactive,
    save_config,
    validate_server_url,
)

if TYPE_CHECKING:
    from pathlib import Path


_EMPTY_PLAN: dict[str, Any] = {
    "to_upload": [],
    "to_download": [],
    "to_delete_local": [],
    "to_delete_remote": [],
    "conflicts": [],
}


def _plan(**overrides: Any) -> dict[str, Any]:
    return {**_EMPTY_PLAN, **overrides}


# ── Config file permissions ──────────────────────────────────────────


class TestConfigFilePermissions:
    @pytest.mark.skipif(sys.platform == "win32", reason="Unix file permissions")
    def test_save_config_sets_restrictive_permissions(self, tmp_path: Path) -> None:
        save_config(tmp_path, {"server": "https://example.com"})
        config_path = tmp_path / CONFIG_FILE
        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix file permissions")
    def test_overwrites_permissive_permissions(self, tmp_path: Path) -> None:
        config_path = tmp_path / CONFIG_FILE
        config_path.write_text("{}")
        config_path.chmod(0o644)
        save_config(tmp_path, {"server": "https://example.com"})
        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_chmod_failure_prints_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("pathlib.Path.chmod", side_effect=OSError("permission denied")):
            save_config(tmp_path, {"server": "https://example.com"})
        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "chmod" in captured.err.lower() or "permission" in captured.err.lower()


# ── Plan helpers ─────────────────────────────────────────────────────


class TestHasPendingChanges:
    def test_empty_plan(self) -> None:
        assert has_pending_changes(_plan()) is False

    def test_uploads(self) -> None:
        assert has_pending_changes(_plan(to_upload=["a.md"])) is True

    def test_downloads(self) -> None:
        assert has_pending_changes(_plan(to_download=["a.md"])) is True

    def test_local_deletes(self) -> None:
        assert has_pending_changes(_plan(to_delete_local=["a.md"])) is True

    def test_remote_deletes(self) -> None:
        assert has_pending_changes(_plan(to_delete_remote=["a.md"])) is True

    def test_conflicts(self) -> None:
        assert has_pending_changes(_plan(conflicts=[{"file_path": "a.md"}])) is True


class TestFormatPlanSummary:
    def test_upload(self) -> None:
        result = format_plan_summary(_plan(to_upload=["posts/new/index.md"]))
        assert "  + posts/new/index.md (upload)" in result

    def test_download(self) -> None:
        result = format_plan_summary(_plan(to_download=["posts/remote/index.md"]))
        assert "  < posts/remote/index.md (download)" in result

    def test_local_delete(self) -> None:
        result = format_plan_summary(_plan(to_delete_local=["posts/old/index.md"]))
        assert "  - posts/old/index.md (delete local)" in result

    def test_remote_delete(self) -> None:
        result = format_plan_summary(_plan(to_delete_remote=["posts/gone/index.md"]))
        assert "  - posts/gone/index.md (delete remote)" in result

    def test_conflict(self) -> None:
        result = format_plan_summary(_plan(conflicts=[{"file_path": "posts/c/index.md"}]))
        assert "  ! posts/c/index.md (conflict)" in result

    def test_empty_plan(self) -> None:
        assert format_plan_summary(_plan()) == ""

    def test_mixed_operations(self) -> None:
        result = format_plan_summary(
            _plan(
                to_upload=["a.md"],
                to_download=["b.md"],
                to_delete_local=["c.md"],
                to_delete_remote=["d.md"],
                conflicts=[{"file_path": "e.md"}],
            )
        )
        lines = result.strip().split("\n")
        assert len(lines) == 5


# ── Confirmation ─────────────────────────────────────────────────────


class TestConfirmSync:
    def test_yes_returns_true(self) -> None:
        with patch("builtins.input", return_value="y"):
            assert confirm_sync(_plan(to_upload=["a.md"])) is True

    def test_full_yes_returns_true(self) -> None:
        with patch("builtins.input", return_value="yes"):
            assert confirm_sync(_plan(to_upload=["a.md"])) is True

    def test_no_returns_false(self) -> None:
        with patch("builtins.input", return_value="n"):
            assert confirm_sync(_plan(to_upload=["a.md"])) is False

    def test_empty_input_returns_false(self) -> None:
        with patch("builtins.input", return_value=""):
            assert confirm_sync(_plan(to_upload=["a.md"])) is False

    def test_keyboard_interrupt_returns_false(self) -> None:
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert confirm_sync(_plan(to_upload=["a.md"])) is False

    def test_eof_returns_false(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            assert confirm_sync(_plan(to_upload=["a.md"])) is False

    def test_prints_plan_summary(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("builtins.input", return_value="n"):
            confirm_sync(_plan(to_upload=["posts/new/index.md"]))
        captured = capsys.readouterr()
        assert "posts/new/index.md" in captured.out


# ── Sync confirmation integration ───────────────────────────────────


class TestSyncConfirmationIntegration:
    def _setup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        plan: dict[str, Any],
        *,
        yes_flag: bool = False,
    ) -> MagicMock:
        save_config(tmp_path, {"server": "https://example.com"})
        argv = ["agblogger", "-d", str(tmp_path), "sync"]
        if yes_flag:
            argv.append("--yes")
        monkeypatch.setattr("sys.argv", argv)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.status.return_value = plan
        return mock_client

    def test_yes_flag_skips_confirmation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_client = self._setup(tmp_path, monkeypatch, _plan(to_upload=["a.md"]), yes_flag=True)
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
        ):
            from cli.sync_client import main

            main()
        mock_client.sync.assert_called_once()

    def test_prompts_when_changes_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_client = self._setup(tmp_path, monkeypatch, _plan(to_upload=["a.md"]))
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
            patch("cli.sync_client.confirm_sync", return_value=True) as mock_confirm,
        ):
            from cli.sync_client import main

            main()
        mock_confirm.assert_called_once()
        mock_client.sync.assert_called_once()

    def test_no_prompt_when_no_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_client = self._setup(tmp_path, monkeypatch, _plan())
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
            patch("cli.sync_client.confirm_sync") as mock_confirm,
        ):
            from cli.sync_client import main

            main()
        mock_confirm.assert_not_called()
        mock_client.sync.assert_called_once()

    def test_aborts_on_decline(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = self._setup(tmp_path, monkeypatch, _plan(to_delete_local=["a.md"]))
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
            patch("cli.sync_client.confirm_sync", return_value=False),
            pytest.raises(SystemExit),
        ):
            from cli.sync_client import main

            main()
        mock_client.sync.assert_not_called()
        captured = capsys.readouterr()
        assert "cancelled" in captured.out.lower()


# ── Login error handling ─────────────────────────────────────────────


class TestLoginInteractive:
    def _mock_client(
        self,
        *,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        side_effect: Exception | None = None,
        json_side_effect: Exception | None = None,
    ) -> MagicMock:
        mock = MagicMock()
        if side_effect:
            mock.post.side_effect = side_effect
        else:
            resp = MagicMock(status_code=status_code)
            if json_side_effect:
                resp.json.side_effect = json_side_effect
            else:
                resp.json.return_value = json_data or {"access_token": "tok"}
            mock.post.return_value = resp
        return mock

    def test_successful_login(self) -> None:
        mock = self._mock_client(json_data={"access_token": "my-token"})
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
        ):
            token = login_interactive(
                "https://example.com", cli_username="admin", config_username=None
            )
        assert token == "my-token"

    def test_401_invalid_credentials(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(status_code=401)
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="wrong"),
            pytest.raises(SystemExit),
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        captured = capsys.readouterr()
        assert "Invalid username or password" in captured.out

    def test_connection_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(side_effect=httpx.ConnectError("refused"))
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
            pytest.raises(SystemExit),
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        captured = capsys.readouterr()
        assert "Could not connect" in captured.out

    def test_timeout_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(side_effect=httpx.TimeoutException("timed out"))
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
            pytest.raises(SystemExit),
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        captured = capsys.readouterr()
        assert "timed out" in captured.out.lower()

    def test_prompts_username_when_not_provided(self) -> None:
        mock = self._mock_client()
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("builtins.input", return_value="prompted-user") as mock_input,
            patch("getpass.getpass", return_value="pass"),
        ):
            login_interactive("https://example.com", cli_username=None, config_username=None)
        mock_input.assert_called_once_with("Username: ")

    def test_cli_username_over_config(self) -> None:
        mock = self._mock_client()
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
        ):
            login_interactive(
                "https://example.com", cli_username="cli-user", config_username="cfg-user"
            )
        call_json = mock.post.call_args[1]["json"]
        assert call_json["username"] == "cli-user"

    def test_config_username_over_prompt(self) -> None:
        mock = self._mock_client()
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("builtins.input") as mock_input,
            patch("getpass.getpass", return_value="pass"),
        ):
            login_interactive("https://example.com", cli_username=None, config_username="cfg-user")
        mock_input.assert_not_called()

    def test_missing_access_token_key_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(json_data={"token": "something"})
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
            pytest.raises(SystemExit) as exc_info,
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_invalid_json_response_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(json_side_effect=ValueError("not json"))
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
            pytest.raises(SystemExit) as exc_info,
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_500_status_exits_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock = self._mock_client(status_code=500)
        with (
            patch("cli.sync_client.httpx.Client", return_value=mock),
            patch("getpass.getpass", return_value="pass"),
            pytest.raises(SystemExit) as exc_info,
        ):
            login_interactive("https://example.com", cli_username="admin", config_username=None)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "500" in captured.out


# ── validate_server_url ──────────────────────────────────────────────


class TestValidateServerUrl:
    def test_valid_https_url_passes(self) -> None:
        result = validate_server_url("https://example.com")
        assert result == "https://example.com"

    def test_http_localhost_passes(self) -> None:
        result = validate_server_url("http://localhost:8000")
        assert result == "http://localhost:8000"

    def test_http_non_localhost_raises(self) -> None:
        with pytest.raises(ValueError, match="HTTPS is required"):
            validate_server_url("http://example.com")

    def test_invalid_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="scheme and host"):
            validate_server_url("ftp://example.com")

    def test_missing_netloc_raises(self) -> None:
        with pytest.raises(ValueError, match="scheme and host"):
            validate_server_url("https://")


# ── main() error handling ────────────────────────────────────────────


class TestMainHttpErrorHandling:
    def _setup_main(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
    ) -> MagicMock:
        save_config(tmp_path, {"server": "https://example.com"})
        monkeypatch.setattr(
            "sys.argv",
            ["agblogger", "-d", str(tmp_path), command],
        )
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_status_http_error_exits_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = self._setup_main(tmp_path, monkeypatch, "status")
        request = httpx.Request("POST", "https://example.com/api/sync/status")
        response = httpx.Response(status_code=403, request=request)
        mock_client.status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=request, response=response
        )
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
            pytest.raises(SystemExit) as exc_info,
        ):
            from cli.sync_client import main

            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "403" in captured.out

    def test_sync_http_error_exits_cleanly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = self._setup_main(tmp_path, monkeypatch, "sync")
        mock_client.status.return_value = _plan()
        request = httpx.Request("POST", "https://example.com/api/sync/commit")
        response = httpx.Response(status_code=500, request=request)
        mock_client.sync.side_effect = httpx.HTTPStatusError(
            "Server Error", request=request, response=response
        )
        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
            pytest.raises(SystemExit) as exc_info,
        ):
            from cli.sync_client import main

            main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "500" in captured.out


# ── PAT env var is ignored entirely ──────────────────────────────────


class TestPATEnvIgnored:
    def test_agblogger_pat_env_produces_no_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AGBLOGGER_PAT env var is completely ignored — no warning, no output."""
        save_config(tmp_path, {"server": "https://example.com"})
        monkeypatch.setattr(
            "sys.argv",
            ["agblogger", "-d", str(tmp_path), "status"],
        )
        monkeypatch.setenv("AGBLOGGER_PAT", "some-old-token")

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.status.return_value = _plan()

        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
        ):
            from cli.sync_client import main

            main()

        captured = capsys.readouterr()
        assert "AGBLOGGER_PAT" not in captured.err
        assert "AGBLOGGER_PAT" not in captured.out


# ── Status formatting regression ─────────────────────────────────────


# ── Config load error handling ────────────────────────────────────────


class TestLoadConfigErrorHandling:
    def test_corrupted_json_exits_gracefully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config_path = tmp_path / CONFIG_FILE
        config_path.write_text("{invalid json!!", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            load_config(tmp_path)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out
        assert CONFIG_FILE in captured.out

    def test_unreadable_config_exits_gracefully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config_path = tmp_path / CONFIG_FILE
        config_path.write_bytes(b"\x80\x81\x82\x83")
        with pytest.raises(SystemExit) as exc_info:
            load_config(tmp_path)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_os_error_exits_gracefully(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config_path = tmp_path / CONFIG_FILE
        config_path.write_text("{}", encoding="utf-8")
        with (
            patch.object(type(config_path), "read_text", side_effect=OSError("disk failure")),
            pytest.raises(SystemExit) as exc_info,
        ):
            load_config(tmp_path)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.out


class TestStatusFormattingRegression:
    def test_delete_remote_line_has_space_before_count(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Regression: 'To delete remote:' was missing space before the count."""
        save_config(tmp_path, {"server": "https://example.com"})
        monkeypatch.setattr(
            "sys.argv",
            ["agblogger", "-d", str(tmp_path), "status"],
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.status.return_value = _plan(to_delete_remote=["posts/gone/index.md"])

        with (
            patch("cli.sync_client.SyncClient", return_value=mock_client),
            patch("cli.sync_client.login_interactive", return_value="token"),
        ):
            from cli.sync_client import main

            main()

        captured = capsys.readouterr()
        for line in captured.out.split("\n"):
            if "delete remote" in line.lower():
                assert "remote: " in line, f"Missing space after colon: {line!r}"
                break
        else:
            pytest.fail("'To delete remote' line not found in output")
