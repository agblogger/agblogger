#!/bin/sh
set -eu

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter-token/token"

mkdir -p /data/goatcounter
mkdir -p /data/goatcounter-token

# Re-provision if either persistent volume is missing its expected state.
if [ ! -f "$TOKEN_FILE" ] || [ ! -s "$GOATCOUNTER_DB" ]; then

    echo "Provisioning GoatCounter: creating site..."
    if ! output=$(goatcounter db create-site \
        -createdb \
        -db "sqlite+$GOATCOUNTER_DB" \
        -vhost stats.internal \
        -user.email admin@localhost \
        -user.password "$(head -c 32 /dev/urandom | base64)" \
        2>&1); then
        case "$output" in
            *"already exists"*|*"UNIQUE constraint"*)
                echo "GoatCounter site already exists, continuing..." ;;
            *)
                echo "ERROR: Site creation failed: $output" >&2
                exit 1 ;;
        esac
    fi

    echo "Provisioning GoatCounter: creating API token..."
    TOKEN=$(goatcounter db create-apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -site-id 1 \
        -perm 3)  # bitmask: 1 (read stats) + 2 (record hits)

    if [ -z "$TOKEN" ]; then
        echo "ERROR: Failed to create GoatCounter API token" >&2
        exit 1
    fi

    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
fi

echo "Starting GoatCounter server..."
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
