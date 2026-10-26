# Commercial MVP Compose

This Compose project is a local Phase 0 foundation. It does not authorize a
deployment or claim that the Corresponding Source URL is public.

From WSL, prepare an immutable gateway build context and a temporary non-secret
Compose env file:

```sh
deploy/mvp/prepare-gateway-context.sh /tmp/commercial-mvp-build.env
```

Set fresh URL-safe values of 32 to 128 characters in
`MVP_POSTGRES_PASSWORD`, `MVP_REDIS_PASSWORD`, `MVP_SESSION_SECRET`,
`MVP_GATEWAY_KEY_PEPPER`,
`MVP_MOCK_PRIMARY_CONTROL_TOKEN`, and `MVP_MOCK_SECONDARY_CONTROL_TOKEN`.
Also set distinct `MVP_MOCK_PRIMARY_RELAY_CREDENTIAL` and
`MVP_MOCK_SECONDARY_RELAY_CREDENTIAL` values.
Compose reads them into in-memory deployment secrets; they do not belong in the
env file, repository, command line, or rendered configuration.

`MVP_GATEWAY_KEY_PEPPER` is the stable high-entropy verifier secret used to
authenticate commercial gateway keys. Keep it private and unchanged across
gateway restarts; changing it makes existing commercial keys unverifiable.

Then run:

```sh
docker compose --env-file /tmp/commercial-mvp-build.env -f deploy/mvp/compose.yaml config
docker compose --env-file /tmp/commercial-mvp-build.env -f deploy/mvp/compose.yaml up --build --wait
docker compose --env-file /tmp/commercial-mvp-build.env -f deploy/mvp/compose.yaml down
```

The disposable proof helper generates its own ephemeral test secrets, verifies
that rendered configuration contains none of their values, uses a unique
Compose project, and removes only that project's test containers and volumes:

```sh
bash deploy/mvp/verify-compose.sh config
bash deploy/mvp/verify-compose.sh up
```

The gateway and mock control ports bind only to host loopback. The database,
Redis, mock relay ports, and backend network are not externally published.

Each mock control listener accepts authenticated
`PUT /control/mode` with an exact `application/json` body whose `mode` is
`normal` or `unavailable`. Port `18081` uses
`MVP_MOCK_PRIMARY_CONTROL_TOKEN`; port `18082` uses
`MVP_MOCK_SECONDARY_CONTROL_TOKEN`. Clients should load the bearer header from
a protected input or credential file rather than exposing the token in a
command argument. Every relay/control result returns the non-secret
`X-Mock-Station-ID` header; `/healthz` deliberately returns no identifying
detail.

The gateway seeds the two mock channel rows from `mock-channels.json`. A first
start that installs the commercial migration leaves them disabled; restart the
gateway after migration completion to cross the existing activation fence and
enable them. The fixture explicitly sets `PRIVATE_MVP_MODE=1`; private mode is
never inferred from the channel seed-file marker. Both rows declare the shared `compose-mock-provider` failure
domain because they run inside the same local fixture environment.

## Trusted epoch operations

Commercial epoch activation and recovery are operator-run, fail-closed
operations. The committed `cmd/commercial-recovery` command does not migrate
the database or expose an HTTP administration route. Build it from the trusted
revision and provide `SQL_DSN` and `REDIS_CONN_STRING` through the operator
environment; the command never prints their values:

```sh
go build -o commercial-recovery ./cmd/commercial-recovery
./commercial-recovery -operation readiness
./commercial-recovery -operation activate -expected-epoch 1
./commercial-recovery -operation recover -expected-epoch 1 -drain 10m
```

The first recovery invocation fences Redis and normally reports
`class=drain_incomplete`; rerun it with the same expected epoch after the full
10-minute maximum lease duration, then confirm `-operation readiness`. A
different present Redis epoch is preserved and reports `class=epoch_stale`
rather than being overwritten by an older operator command. The command emits
only stable pass/fail markers and exits nonzero on unavailable, stale, invalid,
or incomplete state. Activation is for a closed epoch; use readiness to verify
an already-active epoch. If the process stops after the PostgreSQL epoch bump
but before Redis initialization, inspect the singleton row with a trusted
database client and run `-operation activate` for that new closed epoch;
do not retry recovery against the old epoch after it has advanced. If a trusted
inspection instead confirms that the Redis projection is stale or malformed,
use protected Redis administration to delete only the epoch projection, then
run `-operation activate` for the authoritative closed PostgreSQL epoch. Never
delete or overwrite a present newer epoch based only on an older operator input.
