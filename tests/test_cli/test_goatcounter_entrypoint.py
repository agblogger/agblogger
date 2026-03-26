from pathlib import Path


def test_entrypoint_reprovisions_when_db_volume_is_replaced_but_token_volume_remains() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'if [ ! -f "$TOKEN_FILE" ] || [ ! -s "$GOATCOUNTER_DB" ]; then' in entrypoint


def test_entrypoint_has_fail_fast_mode() -> None:
    """The entrypoint must use set -eu to fail fast on errors."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "set -eu" in entrypoint


def test_entrypoint_uses_exec_for_final_command() -> None:
    """The final goatcounter serve must use exec to avoid zombie parent process."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "exec goatcounter serve" in entrypoint


def test_entrypoint_site_creation_does_not_silently_ignore_errors() -> None:
    """Site creation must not use '|| echo' to silently ignore all failures."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    # The old pattern '|| echo "..."' hides real failures behind a misleading message
    assert '|| echo "Site creation skipped' not in entrypoint


def test_entrypoint_site_creation_exits_on_unexpected_failure() -> None:
    """Site creation must exit with error for unexpected (non-idempotent) failures."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    # Must capture output and check for known-safe patterns
    assert "output=$(" in entrypoint
    assert '"already exists"' in entrypoint
    assert '"UNIQUE constraint"' in entrypoint
    # Must exit 1 on unexpected failures
    assert "exit 1" in entrypoint


def test_entrypoint_perm_flag_has_bitmask_comment() -> None:
    """The -perm 3 flag must have a comment explaining the bitmask value."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "-perm 3)  # bitmask:" in entrypoint
