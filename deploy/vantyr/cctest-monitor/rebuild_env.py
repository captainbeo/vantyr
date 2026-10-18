#!/usr/bin/env python3
"""One-shot recovery: rebuild /opt/vantyr/deploy/vantyr/.env from live sources.

Values come from: postgres env (user/db), local-socket psql (relay token,
pin channel names), /tmp/new-pw.txt + /tmp/redis-pw.txt (fresh secrets set
during recovery), constants for PAT and cctest key.

Run ON THE VPS: sudo python3 rebuild_env.py
"""
import subprocess

def docker(*args, input_text=None):
    r = subprocess.run(["sudo", "docker", *args], capture_output=True, text=True, input=input_text)
    if r.returncode != 0:
        raise RuntimeError(f"docker {args} failed: {r.stderr[:200]}")
    return r.stdout

def psql(query):
    u = docker("exec", "vantyr-postgres-1", "printenv", "POSTGRES_USER").strip()
    d = docker("exec", "vantyr-postgres-1", "printenv", "POSTGRES_DB").strip()
    return docker("exec", "-i", "vantyr-postgres-1", "psql", "-U", u, "-d", d, "-t", "-A", "-c", query).strip()

pgu = docker("exec", "vantyr-postgres-1", "printenv", "POSTGRES_USER").strip()
pgd = docker("exec", "vantyr-postgres-1", "printenv", "POSTGRES_DB").strip()
relay = psql("SELECT key FROM tokens WHERE id=19;")
# New API stores relay tokens without the sk- prefix; the API expects it.
if not relay.startswith("sk-"):
    relay = "sk-" + relay
pins = [p for p in psql("SELECT name FROM channels WHERE name LIKE 'a6pin%' ORDER BY id;").split() if p]
newpw = open("/tmp/new-pw.txt").read().strip().split("=", 1)[1]
redispw = open("/tmp/redis-pw.txt").read().strip().split("=", 1)[1]

assert relay.startswith("sk-") and len(relay) > 40, f"bad relay token: {relay[:8]}..."
assert len(pins) == 32, f"expected 32 pins, got {len(pins)}"
assert len(newpw) >= 16 and len(redispw) >= 16

pin_entries = ",".join(f"{n}|https://vantyr.xyz|{relay}" for n in pins)
lines = [
    f"POSTGRES_USER={pgu}",
    f"POSTGRES_PASSWORD={newpw}",
    f"POSTGRES_DB={pgd}",
    f"REDIS_PASSWORD={redispw}",
    "TZ=UTC",
    "CCTEST_GATEWAY_TOKEN=nap_mOKxhlh48e4ux4tY9v3iPy3G4A4e1fCWOQM2ZeBuTa9",
    "CCTEST_KEY=cct-d511a09437b10ee0fb2c1a668c70b85102aaf0f5a7bc1c4f3422b8c84ef4d50f",
    f"CCTEST_SELLER_CHANNELS={pin_entries}",
    "CCTEST_CYCLE_MINUTES=60",
    "CCTEST_SELLER_MODEL_FILTERS=",
    "CCTEST_ENFORCE=true",
]
with open("/opt/vantyr/deploy/vantyr/.env", "w") as f:
    f.write("\n".join(lines) + "\n")
import os
os.chmod("/opt/vantyr/deploy/vantyr/.env", 0o600)
print(f"env rebuilt: {len(lines)} lines, {len(pins)} pin entries")
