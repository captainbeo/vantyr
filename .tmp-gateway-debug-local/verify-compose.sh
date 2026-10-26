#!/usr/bin/env bash
set -euo pipefail

mode=${1:-config}
if [[ "$mode" != "config" && "$mode" != "up" ]]; then
  echo "usage: $0 [config|up]" >&2
  exit 64
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
proof_dir=$(mktemp -d /tmp/commercial-mvp-proof.XXXXXX)
env_file=$proof_dir/build.env
project_name="commercial-mvp-proof-$$"
started=false

cleanup() {
  if [[ "$started" == true && "$project_name" == commercial-mvp-proof-* ]]; then
    docker compose -p "$project_name" --env-file "$env_file" -f "$script_dir/compose.yaml" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ "${MVP_GATEWAY_BUILD_CONTEXT:-}" == /tmp/commercial-mvp-gateway.* ]]; then
    rm -rf -- "$MVP_GATEWAY_BUILD_CONTEXT"
  fi
  if [[ "$proof_dir" == /tmp/commercial-mvp-proof.* ]]; then
    rm -rf -- "$proof_dir"
  fi
}
trap cleanup EXIT INT TERM

sh "$script_dir/prepare-gateway-context.sh" "$env_file"
set -a
. "$env_file"
set +a

export MVP_POSTGRES_PASSWORD=$(openssl rand -hex 32)
export MVP_REDIS_PASSWORD=$(openssl rand -hex 32)
export MVP_SESSION_SECRET=$(openssl rand -hex 32)
export MVP_GATEWAY_KEY_PEPPER=$(openssl rand -hex 32)
export MVP_MOCK_PRIMARY_CONTROL_TOKEN=$(openssl rand -hex 32)
export MVP_MOCK_SECONDARY_CONTROL_TOKEN=$(openssl rand -hex 32)
export MVP_MOCK_PRIMARY_RELAY_CREDENTIAL=$(openssl rand -hex 32)
export MVP_MOCK_SECONDARY_RELAY_CREDENTIAL=$(openssl rand -hex 32)

compose=(docker compose -p "$project_name" --env-file "$env_file" -f "$script_dir/compose.yaml")
rendered=$proof_dir/rendered.yaml
rendered_json=$proof_dir/rendered.json
"${compose[@]}" config > "$rendered"
"${compose[@]}" config --format json > "$rendered_json"

for secret in \
  "$MVP_POSTGRES_PASSWORD" \
  "$MVP_REDIS_PASSWORD" \
  "$MVP_SESSION_SECRET" \
  "$MVP_GATEWAY_KEY_PEPPER" \
  "$MVP_MOCK_PRIMARY_CONTROL_TOKEN" \
  "$MVP_MOCK_SECONDARY_CONTROL_TOKEN" \
  "$MVP_MOCK_PRIMARY_RELAY_CREDENTIAL" \
  "$MVP_MOCK_SECONDARY_RELAY_CREDENTIAL"; do
  if grep -Fq "$secret" "$rendered"; then
    echo "rendered Compose configuration exposed a secret" >&2
    exit 1
  fi
done

python3 - "$rendered_json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    services = json.load(source)["services"]

expected = {
    "gateway": ("127.0.0.1", "3000", 3000),
    "mock-primary": ("127.0.0.1", "18081", 8081),
    "mock-secondary": ("127.0.0.1", "18082", 8081),
}
for service_name, binding in expected.items():
    ports = services[service_name].get("ports", [])
    actual = {
        (port.get("host_ip"), str(port.get("published")), port.get("target"))
        for port in ports
    }
    if binding not in actual:
        raise SystemExit(f"{service_name} loopback port binding missing: {ports!r}")
print("config_port_bindings=passed")
PY

"${compose[@]}" config --services
printf 'rendered_bytes=%s secret_value_hits=0\n' "$(wc -c < "$rendered")"

if [[ "$mode" == "up" ]]; then
  started=true
  "${compose[@]}" up --build --wait
  running=$("${compose[@]}" ps --status running --services | sort)
  expected=$(printf '%s\n' gateway mock-primary mock-secondary postgres redis | sort)
  if [[ "$running" != "$expected" ]]; then
    echo "not all MVP services are running" >&2
    "${compose[@]}" ps >&2
    exit 1
  fi

	seeded_disabled=$("${compose[@]}" exec -T postgres \
		psql -U new_api -d new_api -At -v ON_ERROR_STOP=1 \
		-c "SELECT count(*) FROM channels WHERE id IN (910001, 910002) AND commercial_channel IS TRUE AND status = 2")
	if [[ "$seeded_disabled" != "2" ]]; then
		echo "first-start mock channels did not remain behind the restart activation fence" >&2
		exit 1
	fi
	"${compose[@]}" restart gateway >/dev/null
	"${compose[@]}" up --wait gateway >/dev/null
	seed_counts=$("${compose[@]}" exec -T postgres \
		psql -U new_api -d new_api -At -v ON_ERROR_STOP=1 \
		-c "SELECT
		  (SELECT count(*) FROM channels WHERE id IN (910001, 910002) AND commercial_channel IS TRUE AND status = 1 AND key IS NULL),
		  (SELECT count(*) FROM abilities WHERE channel_id IN (910001, 910002) AND enabled IS TRUE AND model = 'gpt-5.4'),
		  (SELECT count(*) FROM channel_reliability_policies WHERE channel_id IN (910001, 910002)),
		  (SELECT count(*) FROM channel_cost_rates WHERE cost_profile_id IN (930001, 930002))")
	if [[ "$seed_counts" != "2|2|2|8" ]]; then
		echo "commercial mock channel seed verification failed: $seed_counts" >&2
		exit 1
	fi
	printf 'mock_channel_seed=passed counts=%s\n' "$seed_counts"

	fetch_mock() {
		local station=$1
		local credential_file=$2
		local model=$3
		local stream=$4
		local output=$5
		"${compose[@]}" exec -T gateway /bin/sh -c '
			set -eu
			umask 077
			auth_config=$(mktemp /tmp/mock-relay-auth.XXXXXX)
			trap "rm -f -- \$auth_config" EXIT
			credential=$(cat "/run/secrets/$1")
			printf "header = Authorization: Bearer %s\n" "$credential" > "$auth_config"
			unset credential
			wget --quiet --config="$auth_config" --output-document=- \
				--header="Content-Type: application/json" \
				--post-data="{\"model\":\"$2\",\"input\":\"fixture\",\"stream\":$4}" \
				"http://$3:8080/v1/responses"
		' sh "$credential_file" "$model" "$station" "$stream" > "$output"
	}

	exercise_mock() {
		local station=$1
		local credential_file=$2
		local model=$3
		local json_output=$proof_dir/mock-relay-$station.json
		local sse_output=$proof_dir/mock-relay-$station.sse
		fetch_mock "$station" "$credential_file" "$model" false "$json_output"
		fetch_mock "$station" "$credential_file" "$model" true "$sse_output"
		python3 - "$json_output" "$sse_output" "$model" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    response = json.load(source)
if response.get("model") != sys.argv[3] or response.get("status") != "completed":
    raise SystemExit(f"unexpected mock relay response: {response!r}")

with open(sys.argv[2], encoding="utf-8") as source:
    blocks = [block for block in source.read().strip().split("\n\n") if block]
frames = []
for block in blocks:
    lines = block.splitlines()
    if len(lines) != 1 or not lines[0].startswith("data: "):
        raise SystemExit(f"unexpected mock SSE block: {block!r}")
    frames.append(json.loads(lines[0][6:]))
if [frame.get("type") for frame in frames] != ["response.created", "response.completed"]:
    raise SystemExit(f"unexpected mock SSE event order: {frames!r}")
for frame in frames:
    if (frame.get("response") or {}).get("model") != sys.argv[3]:
        raise SystemExit(f"unexpected mock SSE model: {frame!r}")
if frames[-1]["response"].get("status") != "completed":
    raise SystemExit(f"unexpected mock SSE terminal frame: {frames[-1]!r}")
PY
	}

	reject_cross_credential() {
		local station=$1
		local credential_file=$2
		local model=$3
		if "${compose[@]}" exec -T gateway /bin/sh -c '
			set -eu
			umask 077
			auth_config=$(mktemp /tmp/mock-relay-auth.XXXXXX)
			trap "rm -f -- \$auth_config" EXIT
			credential=$(cat "/run/secrets/$1")
			printf "header = Authorization: Bearer %s\n" "$credential" > "$auth_config"
			unset credential
			wget --quiet --config="$auth_config" --output-document=/dev/null \
				--header="Content-Type: application/json" \
				--post-data="{\"model\":\"$2\"}" \
				"http://$3:8080/v1/responses"
		' sh "$credential_file" "$model" "$station" 2>/dev/null; then
			echo "$station accepted the other station credential" >&2
			exit 1
		fi
	}

	reject_cross_credential mock-primary mock_secondary_relay_credential primary-fixture-model
	reject_cross_credential mock-secondary mock_primary_relay_credential secondary-fixture-model
	exercise_mock mock-primary mock_primary_relay_credential primary-fixture-model
	exercise_mock mock-secondary mock_secondary_relay_credential secondary-fixture-model

  set_mock_mode() {
    local port=$1
    local token=$2
    local expected_id=$3
    local selected_mode=$4
    local headers=$proof_dir/mock-control-headers
    printf 'header = "Authorization: Bearer %s"\n' "$token" |
      curl --silent --show-error --fail --config - \
        --request PUT \
        --header 'Content-Type: application/json' \
        --data "{\"mode\":\"$selected_mode\"}" \
        --dump-header "$headers" \
        --output /dev/null \
        "http://127.0.0.1:$port/control/mode"
    if ! tr -d '\r' < "$headers" | grep -Fqi "X-Mock-Station-ID: $expected_id"; then
      echo "mock control response did not identify $expected_id" >&2
      exit 1
    fi
  }

  set_mock_mode 18081 "$MVP_MOCK_PRIMARY_CONTROL_TOKEN" primary unavailable
  set_mock_mode 18082 "$MVP_MOCK_SECONDARY_CONTROL_TOKEN" secondary unavailable
  set_mock_mode 18081 "$MVP_MOCK_PRIMARY_CONTROL_TOKEN" primary normal
  set_mock_mode 18082 "$MVP_MOCK_SECONDARY_CONTROL_TOKEN" secondary normal
  printf 'mock_control_identity=passed\n'

	read_attempts() {
		local port=$1
		local token=$2
		local expected_id=$3
		local expected_model=$4
		local output=$proof_dir/mock-attempts-$expected_id.json
		printf 'header = "Authorization: Bearer %s"\n' "$token" |
			curl --silent --show-error --fail --config - \
				--output "$output" \
				"http://127.0.0.1:$port/control/attempts"
		python3 - "$output" "$expected_id" "$expected_model" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    capture = json.load(source)
expected = {
    "station_id": sys.argv[2],
    "total_attempts": 3,
    "authorized_attempts": 2,
    "rejected_attempts": 1,
}
for key, value in expected.items():
    if capture.get(key) != value:
        raise SystemExit(f"unexpected {sys.argv[2]} attempt capture: {capture!r}")
last = capture.get("last_attempt") or {}
if last.get("path") != "/v1/responses" or last.get("model") != sys.argv[3] or last.get("credential_valid") is not True or last.get("stream") is not True:
    raise SystemExit(f"unexpected {sys.argv[2]} last attempt: {last!r}")
PY
	}

	read_attempts 18081 "$MVP_MOCK_PRIMARY_CONTROL_TOKEN" primary primary-fixture-model
	read_attempts 18082 "$MVP_MOCK_SECONDARY_CONTROL_TOKEN" secondary secondary-fixture-model
	printf 'mock_relay_isolation=passed\n'
  "${compose[@]}" ps
fi

printf 'compose_%s_proof=passed source_revision=%s\n' "$mode" "$MVP_SOURCE_REVISION"
