from pathlib import Path


def test_entrypoint_reprovisions_when_db_volume_is_replaced_but_token_volume_remains() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'if [ ! -f "$TOKEN_FILE" ] || [ ! -s "$GOATCOUNTER_DB" ]; then' in entrypoint


def test_entrypoint_checks_existing_site_before_creating_one() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert "site_exists()" in entrypoint
    assert "command -v sqlite3" in entrypoint
    assert "SELECT 1 FROM sites WHERE cname='$GOATCOUNTER_VHOST' LIMIT 1;" in entrypoint
    assert "SELECT 1 FROM site WHERE cname='$GOATCOUNTER_VHOST' LIMIT 1;" in entrypoint
    assert entrypoint.index("site_exists; then") < entrypoint.index("goatcounter db create site")


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
    assert "there is already a site for the host" in entrypoint
    assert '"UNIQUE constraint"' in entrypoint
    # Must exit 1 on unexpected failures
    assert "exit 1" in entrypoint


def test_entrypoint_perm_flag_has_bitmask_comment() -> None:
    """The API token must request the explicit GoatCounter permissions it needs."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "-perm count,site_read" in entrypoint
    assert "-site-id 1" not in entrypoint
    assert "-user admin@example.com" in entrypoint


def test_entrypoint_uses_configured_site_host_with_safe_normalization() -> None:
    """The sidecar should accept a configured host and strip URL/port parts safely."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST:-stats.internal}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#http://}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#https://}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%/*}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%:*}"' in entrypoint
    assert 'GOATCOUNTER_VHOST="${GOATCOUNTER_SITE_HOST_RAW:-stats.internal}"' in entrypoint
