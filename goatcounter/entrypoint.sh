#!/bin/sh
set -e

GOATCOUNTER_DB="/data/goatcounter/goatcounter.db"
TOKEN_FILE="/data/goatcounter/token"

# First-boot provisioning
if [ ! -f "$TOKEN_FILE" ]; then
    echo "First boot: creating GoatCounter site and API token..."
    mkdir -p /data/goatcounter

    # Create site with database
    goatcounter db create-site \
        -createdb \
        -db "sqlite+$GOATCOUNTER_DB" \
        -vhost stats.internal \
        -user.email admin@localhost \
        -user.password "$(head -c 32 /dev/urandom | base64)"

    # Create API token (permission level 2 = read+write)
    TOKEN=$(goatcounter db create-apitoken \
        -db "sqlite+$GOATCOUNTER_DB" \
        -site-id 1 \
        -perm 2)

    echo "$TOKEN" > "$TOKEN_FILE"
    echo "GoatCounter provisioned. Token written to $TOKEN_FILE"
fi

# Start GoatCounter server
exec goatcounter serve \
    -db "sqlite+$GOATCOUNTER_DB" \
    -listen ":8080" \
    -tls none
