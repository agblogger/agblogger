"""Git service: content directory versioning via git CLI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_COMMIT_RE = re.compile(r"^[0-9a-f]{4,40}$")
GIT_TIMEOUT_SECONDS = 30
_POST_KILL_WAIT_SECONDS = 5.0


class GitService:
    """Wraps git CLI operations on the content directory."""

    def __init__(self, content_dir: Path) -> None:
        self.content_dir = content_dir
        self._write_lock = asyncio.Lock()

    async def _run(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command in the content directory."""
        return await self._run_process(
            ["git", *args],
            check=check,
            capture_output=capture_output,
            cwd=self.content_dir,
        )

    async def _run_process(
        self,
        command: list[str],
        *,
        cwd: Path | None,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a subprocess under asyncio so the event loop owns child reaping."""
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=_POST_KILL_WAIT_SECONDS)
                except TimeoutError:
                    logger.error(
                        "Process %s did not exit after SIGKILL within %ss; handle leaked",
                        " ".join(command),
                        _POST_KILL_WAIT_SECONDS,
                    )
            raise subprocess.TimeoutExpired(cmd=command, timeout=GIT_TIMEOUT_SECONDS) from exc
        except BaseException:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                # asyncio's child watcher reaps the process via SIGCHLD;
                # no explicit wait() needed here.
            raise

        if process.returncode is None:
            # Unreachable in practice: communicate() always sets returncode before returning.
            # This is a defensive assertion against a broken asyncio implementation.
            msg = f"Process {' '.join(command)} finished without a return code"
            raise RuntimeError(msg)
        stdout = stdout_bytes.decode("utf-8", errors="replace") if capture_output else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    async def init_repo(self) -> None:
        """Initialize a git repo if one doesn't exist, then commit any existing files."""
        try:
            async with self._write_lock:
                if not (self.content_dir / ".git").exists():
                    await self._run("init")
                    await self._run("config", "user.email", "agblogger@localhost")
                    await self._run("config", "user.name", "AgBlogger")
                    logger.info("Initialized git repo in %s", self.content_dir)

                # Commit any existing files so HEAD is valid
                await self._run("add", "-A")
                result = await self._run("diff", "--cached", "--quiet", check=False)
                if result.returncode != 0:
                    await self._run("commit", "-m", "Initial commit")
                    logger.info("Created initial commit for existing content")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error(
                "Failed to initialize git repo in %s: %s. "
                "Ensure 'git' is installed and the content directory is writable.",
                self.content_dir,
                exc,
            )
            raise

    async def commit_all(self, message: str) -> str | None:
        """Stage all changes and commit. Returns commit hash or None if nothing to commit."""
        async with self._write_lock:
            await self._run("add", "-A")
            result = await self._run("diff", "--cached", "--quiet", check=False)
            if result.returncode == 0:
                return None
            await self._run("commit", "-m", message)
            return await self.head_commit()

    async def try_commit(self, message: str) -> str | None:
        """Stage and commit, logging an error on failure instead of raising.

        Convenience wrapper around commit_all() for API endpoints where a git
        failure should not abort the request.
        """
        try:
            return await self.commit_all(message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            if isinstance(exc, subprocess.CalledProcessError):
                logger.error(
                    "Git commit failed (exit %d): %s — %s",
                    exc.returncode,
                    exc.stderr.strip() if exc.stderr else "no stderr",
                    message,
                )
            else:
                logger.error("Git commit timed out: %s", message)
            return None

    async def head_commit(self) -> str | None:
        """Return the current HEAD commit hash, or None if the repo has no commits."""
        result = await self._run("rev-parse", "HEAD", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    async def commit_exists(self, commit_hash: str) -> bool:
        """Check if a commit hash exists in the repo."""
        if not _COMMIT_RE.match(commit_hash):
            return False
        result = await self._run("cat-file", "-t", commit_hash, check=False)
        return result.returncode == 0 and result.stdout.strip() == "commit"

    async def show_file_at_commit(self, commit_hash: str, file_path: str) -> str | None:
        """Return file content at a specific commit, or None if file doesn't exist there.

        Raises subprocess.CalledProcessError on unexpected git errors (corrupt repo,
        permission denied, etc.) so callers can distinguish "file missing" from "git broken".
        """
        if not _COMMIT_RE.match(commit_hash):
            logger.warning("Rejected invalid commit hash %r for file %s", commit_hash, file_path)
            return None
        result = await self._run("show", f"{commit_hash}:{file_path}", check=False)
        if result.returncode == 0:
            return result.stdout
        stderr = result.stderr
        if result.returncode == 128 and ("does not exist" in stderr or "but not in" in stderr):
            return None
        raise subprocess.CalledProcessError(
            result.returncode,
            f"git show {commit_hash}:{file_path}",
            output=result.stdout,
            stderr=result.stderr,
        )

    async def merge_file_content(self, base: str, ours: str, theirs: str) -> tuple[str, bool]:
        """Three-way merge of text content using git merge-file.

        Writes base/ours/theirs to temp files, runs git merge-file with -p flag
        (print to stdout), reads back the result.

        Returns (merged_text, has_conflicts).
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            base_f = tmp / "base"
            ours_f = tmp / "ours"
            theirs_f = tmp / "theirs"
            base_f.write_text(base, encoding="utf-8")
            ours_f.write_text(ours, encoding="utf-8")
            theirs_f.write_text(theirs, encoding="utf-8")

            result = await self._run_process(
                ["git", "merge-file", "-p", str(ours_f), str(base_f), str(theirs_f)],
                check=False,
                capture_output=True,
                cwd=None,
            )
            # exit 0 = clean merge, positive exit = number of conflicts (capped at 127),
            # negative exit = signal, exit >= 128 = git error
            if result.returncode < 0 or result.returncode >= 128:
                raise subprocess.CalledProcessError(
                    result.returncode, "git merge-file", result.stdout, result.stderr
                )
            return result.stdout, result.returncode > 0
