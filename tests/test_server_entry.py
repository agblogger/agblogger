"""Tests for backend/__main__.py server entry point."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestMainPortValidation:
    """C3: PORT environment variable must be validated."""

    def test_invalid_port_exits_cleanly(self) -> None:
        """main() should exit cleanly with an error when PORT is non-numeric."""
        from backend.__main__ import main

        with patch.dict("os.environ", {"PORT": "not-a-number"}):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code != 0

    def test_valid_port_is_accepted(self) -> None:
        """main() should convert a valid PORT string and pass it to uvicorn.run."""
        from backend.__main__ import main

        with patch.dict("os.environ", {"PORT": "9000"}), patch("uvicorn.run") as mock_run:
            main()

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("port") == 9000

    def test_default_port_when_not_set(self) -> None:
        """main() should use port 8000 when PORT is not set."""
        import os

        from backend.__main__ import main

        env_copy = os.environ.copy()
        env_copy.pop("PORT", None)
        with patch.dict("os.environ", env_copy, clear=True), patch("uvicorn.run") as mock_run:
            main()

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("port") == 8000
