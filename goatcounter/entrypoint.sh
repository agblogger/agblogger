#!/bin/sh
set -eu

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter-token/token"
GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST:-stats.internal}"
GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#http://}"
GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW#https://}"
GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%/*}"
GOATCOUNTER_SITE_HOST_RAW="${GOATCOUNTER_SITE_HOST_RAW%%:*}"
GOATCOUNTER_VHOST="${GOATCOUNTER_SITE_HOST_RAW:-stats.internal}"
GOATCOUNTER_TOKEN_NAME="agblogger"
GOATCOUNTER_CREATE_PERMISSIONS="count,site_read"
# GoatCounter stores permissions as a bitmask. We need count (2), site_read (8),
# and stats (64). The current CLI build rejects "-perm stats", so we repair the
# token row with SQL after creating or locating it.
GOATCOUNTER_REQUIRED_PERMISSIONS=74

mkdir -p /data/goatcounter
mkdir -p /data/goatcounter-token

fix_token_permissions() {
    if [ -f "$TOKEN_FILE" ]; then
        chmod 644 "$TOKEN_FILE"
    fi
}

write_token_file() {
    TOKEN="$1"
    echo "$TOKEN" > "$TOKEN_FILE"
    fix_token_permissions
}

site_exists() {
    if [ ! -s "$GOATCOUNTER_DB" ]; then
        return 1
    fi

    goatcounter db show site \
        -db "sqlite+$GOATCOUNTER_DB" \
        -find "$GOATCOUNTER_VHOST" >/dev/null 2>&1
}

resolve_site_id() {
    goatcounter db query \
        -db "sqlite+$GOATCOUNTER_DB" \
        -format csv \
        "select site_id from sites where cname = '$GOATCOUNTER_VHOST' limit 1" \
        2>/dev/null |
        sed -n '2{s/\r$//;p;}'
}

resolve_user_id() {
    SITE_ID="$1"

    goatcounter db query \
        -db "sqlite+$GOATCOUNTER_DB" \
        -format csv \
        "select user_id from users where email = 'admin@example.com' and site_id = $SITE_ID order by user_id desc limit 1" \
        2>/dev/null |
        sed -n '2{s/\r$//;p;}'
}

resolve_api_token() {
    SITE_ID="$1"
    USER_ID="$2"

    goatcounter db query \
        -db "sqlite+$GOATCOUNTER_DB" \
        -format csv \
        "select token from api_tokens where site_id = $SITE_ID and user_id = $USER_ID and name = '$GOATCOUNTER_TOKEN_NAME' order by api_token_id desc limit 1" \
        2>/dev/null |
        sed -n '2{s/\r$//;p;}'
}

update_api_token_permissions() {
    TOKEN="$1"

    goatcounter db query \
        -db "sqlite+$GOATCOUNTER_DB" \
        "update api_tokens set permissions = $GOATCOUNTER_REQUIRED_PERMISSIONS where token = '$TOKEN' and permissions != $GOATCOUNTER_REQUIRED_PERMISSIONS" \
        >/dev/null 2>&1
}

ensure_api_token() {
    SITE_ID=$(resolve_site_id)
    if [ -z "$SITE_ID" ]; then
        echo "ERROR: Failed to resolve GoatCounter site id for $GOATCOUNTER_VHOST" >&2
        exit 1
    fi

    USER_ID=$(resolve_user_id "$SITE_ID")
    if [ -z "$USER_ID" ]; then
        echo "ERROR: Failed to resolve GoatCounter admin user id" >&2
        exit 1
    fi

    TOKEN=$(resolve_api_token "$SITE_ID" "$USER_ID")
    if [ -z "$TOKEN" ]; then
        goatcounter db create apitoken \
            -db "sqlite+$GOATCOUNTER_DB" \
            -user "$USER_ID" \
            -name "$GOATCOUNTER_TOKEN_NAME" \
            -perm "$GOATCOUNTER_CREATE_PERMISSIONS" >/dev/null

        TOKEN=$(resolve_api_token "$SITE_ID" "$USER_ID")

        if [ -z "$TOKEN" ]; then
            echo "ERROR: Failed to create GoatCounter API token" >&2
            exit 1
        fi
    fi

    update_api_token_permissions "$TOKEN"
    write_token_file "$TOKEN"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
}

# Re-provision if the site is missing, then always ensure the current site's token exists.
if site_exists; then
    echo "Provisioning GoatCounter: existing site detected, ensuring API token..."
else
    echo "Provisioning GoatCounter: creating site..."
    if ! output=$(goatcounter db create site \
        -createdb \
        -db "sqlite+$GOATCOUNTER_DB" \
        -vhost "$GOATCOUNTER_VHOST" \
        -user.email admin@example.com \
        -user.password "$(head -c 32 /dev/urandom | base64)" \
        2>&1); then
        case "$output" in
            *"already exists"*|*"there is already a site for the host"*|*"UNIQUE constraint"*)
                echo "GoatCounter site already exists, continuing..." ;;
            *)
                echo "ERROR: Site creation failed: $output" >&2
                exit 1 ;;
        esac
    fi
fi

echo "Provisioning GoatCounter: ensuring API token..."
ensure_api_token

echo "Starting GoatCounter server..."
unset GOATCOUNTER_SITE_HOST
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none \
    -ratelimit api:9999999/1,api-count:9999999/1
