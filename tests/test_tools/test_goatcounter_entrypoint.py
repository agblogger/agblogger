from pathlib import Path


def test_entrypoint_always_ensures_the_current_site_token() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    existing_site_message = (
        'echo "Provisioning GoatCounter: existing site detected, ensuring API token..."'
    )

    assert "if site_exists; then" in entrypoint
    assert existing_site_message in entrypoint
    assert 'echo "Provisioning GoatCounter: ensuring API token..."' in entrypoint
    assert "ensure_api_token" in entrypoint


def test_entrypoint_checks_existing_site_before_creating_one() -> None:
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert "site_exists()" in entrypoint
    assert "goatcounter db show site \\" in entrypoint
    assert '-find "$GOATCOUNTER_VHOST"' in entrypoint
    assert entrypoint.index("site_exists; then") < entrypoint.index("goatcounter db create site")


def test_entrypoint_has_fail_fast_mode() -> None:
    """The entrypoint must use set -eu to fail fast on errors."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "set -eu" in entrypoint


def test_entrypoint_uses_exec_for_final_command() -> None:
    """The final goatcounter serve must use exec to avoid zombie parent process."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "exec goatcounter serve" in entrypoint


def test_entrypoint_clears_custom_host_env_before_serving() -> None:
    """The final GoatCounter serve process must not inherit AgBlogger-only env vars."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()
    assert "unset GOATCOUNTER_SITE_HOST" in entrypoint
    unset_index = entrypoint.index("unset GOATCOUNTER_SITE_HOST")
    serve_index = entrypoint.index("exec goatcounter serve")
    assert unset_index < serve_index


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
    # count(2) + export(4) + site_read(8) + stats(64) = 78
    assert 'GOATCOUNTER_CREATE_PERMISSIONS="count,export,site_read"' in entrypoint
    assert "GOATCOUNTER_REQUIRED_PERMISSIONS=78" in entrypoint
    assert "update api_tokens set permissions = $GOATCOUNTER_REQUIRED_PERMISSIONS" in entrypoint
    assert "where token = '$TOKEN'" in entrypoint
    assert '-user "$USER_ID"' in entrypoint
    assert "-site-id 1" not in entrypoint


def test_entrypoint_makes_existing_token_readable_to_agblogger() -> None:
    """Existing token volumes must be fixed on restart so AgBlogger can read the token."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'if [ -f "$TOKEN_FILE" ]; then' in entrypoint
    assert 'chmod 644 "$TOKEN_FILE"' in entrypoint


def test_entrypoint_looks_up_site_specific_user_id_before_creating_token() -> None:
    """Token creation should resolve the admin user for the current GoatCounter site."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert "resolve_site_id()" in entrypoint
    assert "select site_id from sites" in entrypoint
    assert "where cname = '$GOATCOUNTER_VHOST'" in entrypoint
    assert "select user_id from users" in entrypoint
    assert "email = 'admin@example.com' and site_id = $SITE_ID" in entrypoint
    assert 'GOATCOUNTER_TOKEN_NAME="agblogger"' in entrypoint
    assert '-name "$GOATCOUNTER_TOKEN_NAME"' in entrypoint
    assert "site_id = $SITE_ID and user_id = $USER_ID" in entrypoint
    assert "update_api_token_permissions" in entrypoint


def test_entrypoint_uses_configured_site_host_with_safe_normalization() -> None:
    """The sidecar should accept a configured host and strip URL/port parts safely."""
    entrypoint = Path("goatcounter/entrypoint.sh").read_text()

    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST:-stats.internal}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#http://}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#https://}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%/*}"' in entrypoint
    assert 'GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%:*}"' in entrypoint
    assert 'GOATCOUNTER_VHOST="${GOATCOUNTER_SITE_HOST_RAW:-stats.internal}"' in entrypoint
