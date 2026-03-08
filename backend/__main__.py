from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    """Production entry point for Docker. Dev server uses ``just start``."""
    host = os.environ.get("HOST", "127.0.0.1")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        sys.stderr.write(f"Error: invalid PORT value: {port_str!r} (must be a number)\n")
        sys.exit(1)
    uvicorn.run("backend.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
