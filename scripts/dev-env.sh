# Source this file in Git Bash sessions to activate the Go toolchain:
#   source scripts/dev-env.sh
# Go 1.25.1 is bundled at the path below (survived from the Codex runtime cache).
# The build cache and module cache stay on the same drives as the worktree to
# keep C: usage low.

export PATH="/c/Users/z/.cache/codex-runtimes/go/1.25.1/go/bin:$PATH"
export GOROOT="/c/Users/z/.cache/codex-runtimes/go/1.25.1/go"
export GOCACHE="/d/worktrees/commercial-mvp/.gocache"
export GOMODCACHE="/c/Users/z/go/pkg/mod"
