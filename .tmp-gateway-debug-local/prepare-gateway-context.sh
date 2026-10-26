#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <new-env-file>" >&2
  exit 64
fi

env_file=$1
if [ -e "$env_file" ]; then
  echo "refusing to overwrite existing env file" >&2
  exit 65
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=/mnt/c/Users/z/Documents/worktrees/commercial-mvp
if source_revision=$(git -C "$repository_root" rev-parse HEAD 2>/dev/null); then
  archive_source() {
    git -C "$repository_root" archive "$source_revision"
  }
elif command -v git.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
  windows_root=$(wslpath -w "$repository_root")
  source_revision=$(git.exe -C "$windows_root" rev-parse HEAD | tr -d '\r')
  archive_source() {
    git.exe -C "$windows_root" archive "$source_revision"
  }
else
  echo "git cannot read the linked worktree" >&2
  exit 69
fi
repository_url=${MVP_SOURCE_REPOSITORY_URL:-https://github.com/captainbeo/proxy-server}

if ! printf '%s' "$repository_url" | grep -Eq '^https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$'; then
  echo "MVP_SOURCE_REPOSITORY_URL must be a canonical HTTPS GitHub repository URL" >&2
  exit 64
fi

context_dir=$(mktemp -d "${TMPDIR:-/tmp}/commercial-mvp-gateway.XXXXXX")
archive_source | tar -xf - -C "$context_dir"
printf '%s' "$source_revision" > "$context_dir/.release-source-revision"

umask 077
{
  printf 'MVP_GATEWAY_BUILD_CONTEXT=%s\n' "$context_dir"
  printf 'MVP_SOURCE_REVISION=%s\n' "$source_revision"
  printf 'MVP_CORRESPONDING_SOURCE_URL=%s/tree/%s\n' "$repository_url" "$source_revision"
} > "$env_file"

printf 'Prepared immutable gateway context %s and Compose env file %s\n' "$context_dir" "$env_file"
printf 'This local preparation does not prove that the source URL resolves publicly.\n'
