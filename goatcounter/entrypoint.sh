#!/bin/sh
set -eu

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter-token/token"
GOATCOUNTER_VHOST="stats.internal"

mkdir -p /data/goatcounter
mkdir -p /data/goatcounter-token

site_exists() {
    if ! command -v sqlite3 >/dev/null 2>&1 || [ ! -s "$GOATCOUNTER_DB" ]; then
        return 1
    fi

    sqlite3 "$GOATCOUNTER_DB" \
        "SELECT 1 FROM sites WHERE cname='$GOATCOUNTER_VHOST' LIMIT 1;" >/dev/null 2>&1 ||
        sqlite3 "$GOATCOUNTER_DB" \
            "SELECT 1 FROM site WHERE cname='$GOATCOUNTER_VHOST' LIMIT 1;" >/dev/null 2>&1
}

create_api_token() {
    TOKEN=$(goatcounter db create apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -user admin@example.com \
        -perm count,site_read)

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
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
