#!/bin/sh
set -eu

read_secret() {
  secret_path=$1
  if [ ! -f "$secret_path" ]; then
    echo "required deployment secret is unavailable" >&2
    exit 64
  fi
  secret_value=$(cat "$secret_path")
  case "$secret_value" in
    *[!A-Za-z0-9._~-]*|'')
      echo "deployment secret must use URL-safe characters" >&2
      exit 64
      ;;
  esac
  if [ "${#secret_value}" -lt 32 ] || [ "${#secret_value}" -gt 128 ]; then
    echo "deployment secret length is outside the allowed range" >&2
    exit 64
  fi
  printf '%s' "$secret_value"
}

postgres_password=$(read_secret /run/secrets/postgres_password)
redis_password=$(read_secret /run/secrets/redis_password)
session_secret=$(read_secret /run/secrets/session_secret)
gateway_key_pepper=$(read_secret /run/secrets/gateway_key_pepper)
mock_primary_relay_credential=$(read_secret /run/secrets/mock_primary_relay_credential)
mock_secondary_relay_credential=$(read_secret /run/secrets/mock_secondary_relay_credential)

case "${POSTGRES_USER:-}" in *[!A-Za-z0-9_]*|'') exit 64 ;; esac
case "${POSTGRES_DB:-}" in *[!A-Za-z0-9_]*|'') exit 64 ;; esac
case "${POSTGRES_HOST:-}" in *[!A-Za-z0-9.-]*|'') exit 64 ;; esac
case "${POSTGRES_PORT:-}" in *[!0-9]*|'') exit 64 ;; esac
case "${REDIS_HOST:-}" in *[!A-Za-z0-9.-]*|'') exit 64 ;; esac
case "${REDIS_PORT:-}" in *[!0-9]*|'') exit 64 ;; esac

export SQL_DSN="postgresql://${POSTGRES_USER}:${postgres_password}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}?sslmode=disable"
export REDIS_CONN_STRING="redis://:${redis_password}@${REDIS_HOST}:${REDIS_PORT}/0"
export SESSION_SECRET="$session_secret"
export GATEWAY_KEY_PEPPER="$gateway_key_pepper"
export MVP_MOCK_PRIMARY_RELAY_CREDENTIAL="$mock_primary_relay_credential"
export MVP_MOCK_SECONDARY_RELAY_CREDENTIAL="$mock_secondary_relay_credential"

unset postgres_password redis_password session_secret gateway_key_pepper mock_primary_relay_credential mock_secondary_relay_credential
exec /new-api "$@"
