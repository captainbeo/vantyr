#!/bin/sh
set -eu

secret_path=/run/secrets/redis_password
if [ ! -f "$secret_path" ]; then
  echo "required deployment secret is unavailable" >&2
  exit 64
fi

redis_password=$(cat "$secret_path")
case "$redis_password" in
  *[!A-Za-z0-9._~-]*|'')
    echo "deployment secret must use URL-safe characters" >&2
    exit 64
    ;;
esac
if [ "${#redis_password}" -lt 32 ] || [ "${#redis_password}" -gt 128 ]; then
  echo "deployment secret length is outside the allowed range" >&2
  exit 64
fi

umask 077
{
  printf 'bind 0.0.0.0\n'
  printf 'protected-mode yes\n'
  printf 'port 6379\n'
  printf 'appendonly yes\n'
  printf 'dir /data\n'
  printf 'requirepass %s\n' "$redis_password"
} > /run/mvp/redis.conf
unset redis_password

exec redis-server /run/mvp/redis.conf
