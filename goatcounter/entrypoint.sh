#!/bin/sh
set -eu

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter/token"

# First-boot provisioning
if [ ! -f "$TOKEN_FILE" ]; then
    echo "First boot: creating GoatCounter site and API token..."
    mkdir -p /data/goatcounter

    # Create site only if the database does not already exist
    if [ ! -f "$GOATCOUNTER_DB" ]; then
        goatcounter db create-site \
            -createdb \
            -db "sqlite+$GOATCOUNTER_DB" \
            -vhost stats.internal \
            -user.email admin@localhost \
            -user.password "$(head -c 32 /dev/urandom | base64)"
    fi

    # Create API token (permission bitmask: 1=read + 2=count = 3)
    TOKEN=$(goatcounter db create-apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -site-id 1 \
        -perm 3)

    if [ -z "$TOKEN" ]; then
        echo "ERROR: Failed to create GoatCounter API token" >&2
        exit 1
    fi

    echo "$TOKEN" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
fi

# Start GoatCounter server
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
