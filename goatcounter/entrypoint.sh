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

mkdir -p /data/goatcounter
mkdir -p /data/goatcounter-token

site_exists() {
    if [ ! -s "$GOATCOUNTER_DB" ]; then
        return 1
    fi

    goatcounter db show site \
        -db "sqlite+$GOATCOUNTER_DB" \
        -find "$GOATCOUNTER_VHOST" >/dev/null 2>&1
}

resolve_user_id() {
    goatcounter db show user \
        -db "sqlite+$GOATCOUNTER_DB" \
        -find "admin@example.com" \
        -format json 2>/dev/null |
        sed -n 's/.*"user_id":[[:space:]]*\([0-9][0-9]*\).*/\1/p' |
        head -n 1
}

resolve_api_token() {
    USER_ID="$1"

    goatcounter db query \
        -db "sqlite+$GOATCOUNTER_DB" \
        -format csv \
        "select token from api_tokens where user_id = $USER_ID and name = '$GOATCOUNTER_TOKEN_NAME' order by api_token_id desc limit 1" \
        2>/dev/null |
        sed -n '2{s/\r$//;p;}'
}

create_api_token() {
    USER_ID=$(resolve_user_id)
    if [ -z "$USER_ID" ]; then
        echo "ERROR: Failed to resolve GoatCounter admin user id" >&2
        exit 1
    fi

    goatcounter db create apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -user "$USER_ID" \
        -name "$GOATCOUNTER_TOKEN_NAME" \
        -perm count,site_read >/dev/null

    TOKEN=$(resolve_api_token "$USER_ID")

    if [ -z "$TOKEN" ]; then
        echo "ERROR: Failed to create GoatCounter API token" >&2
        exit 1
    fi

    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
}

# Re-provision if either persistent volume is missing its expected state.
if [ ! -f "$TOKEN_FILE" ] || [ ! -s "$GOATCOUNTER_DB" ]; then
    if site_exists; then
        echo "Provisioning GoatCounter: existing site detected, creating API token..."
        create_api_token
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

        echo "Provisioning GoatCounter: creating API token..."
        create_api_token
    fi
fi

echo "Starting GoatCounter server..."
unset GOATCOUNTER_SITE_HOST
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
