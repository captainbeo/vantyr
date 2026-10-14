#!/bin/bash
# Daily EUR price sync for Vantyr Stripe checkout (Option A live rates).
#
# The wallet credits USD-denominated units ($1 = 500,000 quota). The EUR
# Stripe price is the euro-equivalent of ONE dollar unit:
#   cents = ceil(100 / ECB EUR->USD rate)
# e.g. rate 1.1188 -> 100/1.1188 = 89.38 -> 90 cents, so a customer pays
# €0.90 for exactly $1.00 of credit; per euro spent ≈ rate dollars of
# credit (€1.00 -> ~$1.11). Ceil errs ≤1 cent in the owner's favor.
# Stripe prices are immutable — the script creates a NEW price each day the
# rounded cents value changes, points the New API option at it, archives the
# previous one, and switches the product's default price (required before
# archiving a default).
#
# Idempotent: same cents value -> no Stripe calls, no option write.
# Runs as root cron: 15 3 * * * /opt/vantyr/scripts/stripe-eur-rate-sync.sh
set -euo pipefail

KEY=$(docker exec vantyr-postgres-1 psql -U vantyr -d vantyr -t -A -c \
    "SELECT value FROM options WHERE key = 'StripeApiSecret'")
PRODUCT=$(docker exec vantyr-postgres-1 psql -U vantyr -d vantyr -t -A -c \
    "SELECT value FROM options WHERE key = 'StripePriceId'")
CURRENT_PRICE=$(docker exec vantyr-postgres-1 psql -U vantyr -d vantyr -t -A -c \
    "SELECT value FROM options WHERE key = 'StripePriceId'")
if [ -z "$KEY" ] || [ -z "$CURRENT_PRICE" ]; then
    echo "stripe options not configured" >&2
    exit 1
fi

# Current rate (ECB reference via frankfurter; fallback open.er-api.com).
RATE=$(curl -sf --max-time 20 "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=USD" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["rates"]["USD"])' 2>/dev/null) || \
RATE=$(curl -sf --max-time 20 "https://open.er-api.com/v6/latest/EUR" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["rates"]["USD"])' 2>/dev/null) || \
RATE=""
if [ -z "$RATE" ]; then
    echo "rate fetch failed — keeping current price" >&2
    exit 0
fi

TARGET_CENTS=$(python3 -c "import math; print(math.ceil(100 / float('$RATE')))")

CURRENT_CENTS=$(curl -sf --max-time 20 "https://api.stripe.com/v1/prices/$CURRENT_PRICE" \
    -u "$KEY:" | python3 -c 'import json,sys; print(json.load(sys.stdin)["unit_amount"])')
if [ "$CURRENT_CENTS" = "$TARGET_CENTS" ]; then
    echo "rate unchanged (EUR $RATE -> $TARGET_CENTS cents == current $CURRENT_CENTS)"
    exit 0
fi

# Create the new price (immutable amounts -> new object per change).
PROD_ID=$(curl -sf --max-time 20 "https://api.stripe.com/v1/prices/$CURRENT_PRICE" \
    -u "$KEY:" | python3 -c 'import json,sys; print(json.load(sys.stdin)["product"])')
NEW_PRICE=$(curl -sf --max-time 30 -X POST "https://api.stripe.com/v1/prices" \
    -u "$KEY:" -d "product=$PROD_ID" -d "unit_amount=$TARGET_CENTS" -d "currency=eur" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
if [ -z "$NEW_PRICE" ]; then
    echo "stripe price creation failed" >&2
    exit 1
fi

# Point New API at the new price, make it the product default, archive old.
echo "UPDATE options SET value = '$NEW_PRICE' WHERE key = 'StripePriceId';" \
    | docker exec -i vantyr-postgres-1 psql -U vantyr -d vantyr -f - >/dev/null
curl -sf --max-time 20 -X POST "https://api.stripe.com/v1/products/$PROD_ID" \
    -u "$KEY:" -d "default_price=$NEW_PRICE" >/dev/null
curl -sf --max-time 20 -X POST "https://api.stripe.com/v1/prices/$CURRENT_PRICE" \
    -u "$KEY:" -d "active=false" >/dev/null || true
# Options cache reloads on the 60s sync; no restart needed.
echo "$(date -u +%FT%TZ) EUR $RATE -> $NEW_PRICE ($TARGET_CENTS cents), archived $CURRENT_PRICE"
