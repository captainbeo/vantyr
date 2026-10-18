#!/usr/bin/env python3
"""Vantyr CCTest model-authenticity monitor.

Round-robins one claude-*/gpt-* model per channel per cycle through
cctest.ai's check API. Bad verdicts (unofficial / reversed / not_claude)
quarantine the channel via the gateway's admin channel-status API
(status 2 = manually disabled); the native New API test loop skips
status-2 channels, so quarantine release is exclusively ours.
Fail-open: cctest API errors and inconclusive results never quarantine.

Channels are looked up by name every cycle (never by id — VANTYR.md
records conflicting A6 channel ids). Channels disabled by the owner
(status != 1) are never tested or re-enabled; the monitor only manages
channels it quarantined itself. State lives in a volume-mounted JSON
file (/data/state.json); if it is lost, quarantined channels stay
disabled (fail-safe — nothing is re-enabled without state).

Observe-only until ENFORCE=true: verdicts are logged and would-be
actions are announced, but nothing is written to the gateway.

Failover (ENFORCE=true): on a confirmed bad verdict for model X on
seller S, the monitor removes X from S's channels (models field edit;
the PUT preserves the channel key because absent fields are not
zeroed). New API's priority routing then shifts X's traffic to the
remaining providers in the same group (e.g. Selora -> Mia/A6). A
coverage gate blocks removal when no other enabled channel in the
group would still serve X. Channel-status quarantine (disable) remains
the action only for a seller-wide failure (all eligible models bad).

Env config (compose maps the CCTEST_* vars in deploy/vantyr/.env):
  GATEWAY_URL            e.g. http://vantyr-gateway:3000
  GATEWAY_TOKEN          PAT with channel operate + write + log read scopes
  CCTEST_BASE            default https://cctest.ai
  CCTEST_KEY             cct-... API key
  SELLER_CHANNELS        entries "name|base_url|seller_key" separated by ","
                         (pipe separator: URLs contain colons). One entry
                         per seller key: all gateway channels using that
                         same seller key share the entry (channel lookup
                         expands to every channel whose name starts with
                         the entry name). Production runs four sellers:
                         selora-*/a6-*/yingz-* plus mia-* (Mia Router
                         failover channels, https://miarouter.online).
                         Pinned A6 keys (one merchant+model per key) use
                         the entry name "a6pin-<model>" (e.g.
                         a6pin-fable-5): the prefix routes them to the
                         deterministic threshold (FAIL_THRESHOLD_A6PIN=1)
                         and the channel-name suffix carries the model
                         family, so the backend's grouping is the channel
                         record itself — a pinned channel lists exactly
                         one model, its name says which, and the monitor
                         checks that one path deterministically.
                         Selora's sk-gw- key only authenticates from our
                         gateway's Go client (TLS-fingerprint-gated) — for
                         selora, point the URL at the gateway itself
                         (https://vantyr.xyz) with a Vantyr relay token;
                         checks then ride the real customer path and
                         channel attribution comes from the usage log.
  MODEL_PREFIXES         comma list, default "claude,gpt"
  USAGE_WINDOW_HOURS     traffic gate, default 168 (7 days)
  CYCLE_MINUTES          default 10
  ENFORCE                false (observe-only) / true
  FAIL_THRESHOLD         consecutive fails before quarantine: default 1
                         for selora-* channels, 2 for a6-*/mia-* channels
  PERMANENT_FAILS        consecutive fails before credit spend stops, default 3
  DISCORD_WEBHOOK        optional alerts
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

LOG = logging.getLogger("cctest-monitor")

STATE_PATH = os.environ.get("STATE_PATH", "/data/state.json")

# Name of the sidecar user's relay token in usage logs — used to exclude
# the monitor's own gateway-routed traffic from the usage gate.
MONITOR_TOKEN_NAME = os.environ.get("MONITOR_TOKEN_NAME", "cctest-monitor")

# Verdict categories from cctest.ai/docs (full mode) plus the live-observed
# attribution-mode values (attr_match / attr_swapped, verdictKey field).
# Live observation 2026-10-12: A6 attribution check on claude-fable-5-1
# returned verdictKey attr_swapped, attribution.prediction claude-opus-4-6.
PASS_VERDICTS = {"official", "attr_match"}
SOFT_VERDICTS = {"official_flawed", "reversed"}
BAD_VERDICTS = {"unofficial", "not_claude", "attr_swapped"}
# attr_uncertain (live-observed 2026-10-13): attribution could not decide
# (e.g. a 60/40 split). Neither pass nor fail — no state change. Listed
# only for documentation; unknown verdicts already fall through as
# inconclusive.
INCONCLUSIVE_VERDICTS = {"attr_uncertain"}

CHANNEL_ENABLED = 1
CHANNEL_MANUALLY_DISABLED = 2


def http_json(method, url, token=None, body=None, timeout=30.0):
    """Returns (parsed_payload, http_status); status 0 = transport error."""
    data = None
    headers = {
        # Cloudflare blocks the default Python-urllib UA (error 1010).
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {"raw": str(e)}
        return payload, e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"error": str(e)}, 0


def load_state():
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
            return state if isinstance(state, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


class Gateway:
    """Gateway admin API client (Authorization: Bearer PAT)."""

    def __init__(self, base, token):
        self.base = base.rstrip("/")
        self.token = token

    def _request(self, method, path, body=None):
        return http_json(method, self.base + path, self.token, body)

    def list_channels(self):
        channels = []
        page = 1
        while True:
            query = urllib.parse.urlencode({"p": page, "page_size": 100})
            payload, status = self._request("GET", f"/api/channel/?{query}")
            if status != 200 or not payload.get("success"):
                raise RuntimeError(f"channel list failed: {status} {payload}")
            data = payload.get("data") or {}
            items = data.get("items") or []
            channels.extend(items)
            total = data.get("total") or 0
            if len(channels) >= total or not items:
                return channels
            page += 1

    def find_channel(self, name):
        """Returns (id, models, status) for the channel with this exact name."""
        for ch in self.list_channels():
            if ch.get("name") == name:
                models = [m.strip() for m in (ch.get("models") or "").split(",") if m.strip()]
                return int(ch["id"]), models, int(ch.get("status") or 0)
        raise RuntimeError(f"channel {name!r} not found")

    def set_status(self, channel_id, status):
        # isManageableChannelStatus accepts only 1 (enable) / 2 (disable).
        payload, http_status = self._request(
            "POST", f"/api/channel/{channel_id}/status", {"status": status}
        )
        if http_status != 200 or not payload.get("success"):
            raise RuntimeError(f"status flip to {status} failed: {http_status} {payload}")
        return bool(payload.get("data"))

    def update_channel_models(self, channel_id, models):
        """Edit only the channel's models list via PUT /api/channel/.
        Safety: the request body contains only id + models. controller/
        channel.go's update path classifies "models" as non-sensitive and
        GORM's struct Updates() skips zero-valued fields, so the channel
        key, base_url, and every other field are preserved untouched."""
        payload, http_status = self._request(
            "PUT", "/api/channel/",
            {"id": channel_id, "models": ",".join(models)},
        )
        if http_status != 200 or not payload.get("success"):
            raise RuntimeError(f"channel models update failed: {http_status} {payload}")
        return True

    def model_used_recently(self, channel_id, model, window_hours, exclude_token=None):
        """Traffic gate: did anyone other than the monitor's own token use
        this model on this channel recently? Without the exclusion the
        monitor's own gateway-routed checks satisfy the gate and keep dead
        SKUs in the rotation forever (self-sustaining credit burn)."""
        since = int(time.time()) - window_hours * 3600
        base = {
            "p": 1, "page_size": 1, "channel": channel_id,
            "model_name": model, "start_timestamp": since,
        }
        payload, status = self._request("GET", f"/api/log/?{urllib.parse.urlencode(base)}")
        if status != 200 or not payload.get("success"):
            raise RuntimeError(f"log query failed: {status} {payload}")
        total = (payload.get("data") or {}).get("total") or 0
        if total == 0 or not exclude_token:
            return total > 0
        own = dict(base)
        own["token_name"] = exclude_token
        payload, status = self._request("GET", f"/api/log/?{urllib.parse.urlencode(own)}")
        if status != 200 or not payload.get("success"):
            # Can't subtract our own usage: assume used (fail toward
            # checking, not toward silently dropping coverage).
            return True
        own_count = (payload.get("data") or {}).get("total") or 0
        return total > own_count

    def last_channel_for_model(self, model, window_minutes=10):
        """For gateway-routed checks: find which channel recently served
        this model (usage log lookup, newest first). Returns channel_id
        or None."""
        since = int(time.time()) - window_minutes * 60
        query = urllib.parse.urlencode({
            "p": 1, "page_size": 20, "type": 2,
            "model_name": model, "start_timestamp": since,
        })
        payload, status = self._request("GET", f"/api/log/?{query}")
        if status != 200 or not payload.get("success"):
            raise RuntimeError(f"log query failed: {status} {payload}")
        for entry in (payload.get("data") or {}).get("items") or []:
            # The log's channel field serializes as "channel" (model/log.go).
            cid = entry.get("channel")
            if cid:
                return int(cid)
        return None


class CCTest:
    def __init__(self, base, key, full_check=False, http_client=None):
        self.base = base.rstrip("/")
        self.key = key
        self.full_check = full_check
        self.http = http_client or http_json

    def check(self, base_url, seller_key, model):
        """Submit one check and poll for its result.
        Returns the result dict, or None when inconclusive (submit error,
        task failure, timeout) — never quarantines on its own errors.

        Request schema recovered from cctest's web bundle (their docs page
        renders from embedded i18n strings): POST /api/v1/check with
        {url, apiKey, model, provider, attributionOnly, concurrency}.
        url auto-appends the provider's path (/v1/messages for claude,
        /v1/responses for codex). attributionOnly=true is the cheap mode:
        3 requests, fingerprint-swap detection, no full scoring."""
        payload, status = self.http(
            "POST",
            self.base + "/api/v1/check",
            self.key,
            {
                "url": base_url,
                "apiKey": seller_key,
                "model": model,
                "provider": provider_for(model),
                "attributionOnly": not self.full_check,
                "concurrency": 1,
            },
        )
        if status != 200:
            LOG.warning("cctest submit failed: http=%s %s", status, payload)
            return None
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            LOG.warning("cctest submit response has no task id: %s", payload)
            return None
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(5)
            result, status = self.http("GET", f"{self.base}/api/v1/check/{task_id}", self.key)
            if status != 200:
                LOG.warning("cctest poll failed: http=%s %s", status, result)
                return None
            polled = result.get("data") if isinstance(result.get("data"), dict) else result
            state = polled.get("status") or polled.get("state")
            if state in ("done", "completed", "finished", "success"):
                return polled
            if state in ("failed", "error", "cancelled"):
                LOG.warning("cctest task %s ended with error: %s", task_id, (polled.get("error") or "")[:200])
                return None
        LOG.warning("cctest task %s timed out", task_id)
        return None

    @staticmethod
    def verdict_category(result):
        # attributionOnly mode returns verdictKey (attr_match / attr_swapped);
        # full mode returns verdict (official / official_flawed / unofficial /
        # reversed / not_claude).
        for key in ("verdict", "verdictKey", "category", "result", "level"):
            value = result.get(key)
            if isinstance(value, str) and value:
                return value.lower()
        return None


def provider_for(model):
    """cctest detection line: claude → Anthropic /v1/messages, codex →
    OpenAI /v1/responses. GPT-family models ride the codex line."""
    return "codex" if model.lower().startswith("gpt-") else "claude"


def parse_model_mapping(raw):
    """Channel model_mapping comes as a JSON object string (or empty).
    Returns a dict customer-name -> upstream-name."""
    if not raw or not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def discord_alert(webhook, text):
    if not webhook:
        return
    payload, status = http_json("POST", webhook, None, {"content": text})
    if status not in (200, 204):
        LOG.warning("discord alert failed: %s %s", status, payload)


def park(reason):
    """Config incomplete: log once and idle instead of crash-looping, so a
    partially-configured .env does not turn into a restart storm."""
    LOG.error("parked: %s", reason)
    while True:
        time.sleep(3600)


def parse_seller_channels(raw, known_prefixes):
    """Parse SELLER_CHANNELS entries "name|base_url|seller_key". The name is
    a prefix matched against gateway channel names at runtime: one entry
    covers every gateway channel whose name starts with it. Pinned A6
    keys use "a6pin-<model>" names (one merchant+model per key — see the
    module docstring)."""
    sellers = []
    for entry in raw.split(","):
        parts = [p.strip() for p in entry.split("|") if p.strip()]
        if not parts:
            continue
        if len(parts) != 3:
            LOG.warning("ignoring malformed SELLER_CHANNELS entry %r (want name|base_url|key)", entry)
            continue
        name, base_url, seller_key = parts
        if not name.startswith(known_prefixes):
            LOG.warning("ignoring SELLER_CHANNELS entry %r: name must start with %s", entry, known_prefixes)
            continue
        sellers.append((name, base_url, seller_key))
    return sellers


def expand_seller_to_channels(channels, seller_prefix, base_url, seller_key):
    """Resolve one seller entry to the gateway channels it covers.
    General sellers: every channel whose name starts with the entry name.
    Pinned entries ("a6pin-<model>", one key per merchant+model): EXACT
    name match — "a6pin-fable-5" must not also grab "a6pin-fable-5-1"."""
    if seller_prefix.startswith("a6pin"):
        return [ch for ch in channels if (ch.get("name") or "") == seller_prefix]
    return [ch for ch in channels if (ch.get("name") or "").startswith(seller_prefix)]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    gateway_url = os.environ.get("GATEWAY_URL")
    gateway_token = os.environ.get("GATEWAY_TOKEN")
    cctest_key = os.environ.get("CCTEST_KEY")
    if not (gateway_url and gateway_token and cctest_key):
        park("GATEWAY_URL, GATEWAY_TOKEN, and CCTEST_KEY must all be set")
        return 1
    sellers = parse_seller_channels(
        os.environ.get("SELLER_CHANNELS", ""),
        known_prefixes=("selora", "a6", "a6pin", "mia", "yingz"),
    )
    if not sellers:
        park("SELLER_CHANNELS has no valid entries")
        return 1
    # Optional per-seller model restriction, "prefix|models" entries:
    # a6|gpt-6-astra,gpt-6-sol — lets a dedicated monitoring key with
    # limited model permissions check only what it can call.
    seller_model_filter = {}
    for entry in os.environ.get("SELLER_MODEL_FILTERS", "").split(","):
        parts = [p.strip() for p in entry.split("|") if p.strip()]
        if len(parts) == 2:
            seller_model_filter[parts[0]] = [
                m.strip() for m in parts[1].split(";") if m.strip()
            ]

    enforce = os.environ.get("ENFORCE", "false").lower() in ("1", "true", "yes")
    cycle_minutes = max(1, int(os.environ.get("CYCLE_MINUTES", "10")))
    model_prefixes = tuple(
        p.strip().lower()
        for p in os.environ.get("MODEL_PREFIXES", "claude,gpt").split(",")
        if p.strip()
    )
    usage_window_hours = max(1, int(os.environ.get("USAGE_WINDOW_HOURS", "168")))
    permanent_fails = max(2, int(os.environ.get("PERMANENT_FAILS", "3")))
    # Threshold by channel-name prefix: selora-* = dedicated upstream (a
    # single bad verdict is unambiguous), a6-* = merchant lottery (noise
    # tolerant), mia-* = flat-priced seller, unknown routing depth —
    # yingz-* = cheap prepaid seller, unverified — same noise tolerance
    # as a6/mia until live verdicts say otherwise.
    fail_threshold_prefixes = (
        # Pinned (merchant/model) A6 keys are deterministic: a bad verdict
        # IS the merchant serving a fake, no lottery noise to average out.
        # Threshold 1 → one confirmed swap quarantines exactly that
        # merchant's channel; traffic shifts to the next ladder step and
        # the owner re-pins the key to a fresh merchant.
        ("a6pin", max(1, int(os.environ.get("FAIL_THRESHOLD_A6PIN", "1")))),
        ("selora", max(1, int(os.environ.get("FAIL_THRESHOLD_SELORA", "1")))),
        ("a6", max(1, int(os.environ.get("FAIL_THRESHOLD_A6", "2")))),
        ("mia", max(1, int(os.environ.get("FAIL_THRESHOLD_MIA", "2")))),
        ("yingz", max(1, int(os.environ.get("FAIL_THRESHOLD_YINGZ", "2")))),
    )

    def threshold_for(channel_name):
        for prefix, threshold in fail_threshold_prefixes:
            if channel_name.startswith(prefix):
                return threshold
        return permanent_fails

    gateway = Gateway(gateway_url, gateway_token)
    cctest = CCTest(
        os.environ.get("CCTEST_BASE", "https://cctest.ai"),
        cctest_key,
        full_check=os.environ.get("CCTEST_FULL_CHECK", "false").lower() in ("1", "true", "yes"),
    )
    discord = os.environ.get("DISCORD_WEBHOOK") or None

    LOG.info(
        "cctest-monitor starting: enforce=%s cycle=%dm prefixes=%s sellers=%s thresholds(prefix)=%s",
        enforce, cycle_minutes, model_prefixes,
        [s[0] for s in sellers], fail_threshold_prefixes,
    )

    state = load_state()
    while True:
        try:
            run_cycle(
                gateway, cctest, sellers, model_prefixes, usage_window_hours,
                threshold_for, permanent_fails, enforce, discord, state,
                seller_model_filter,
            )
        except Exception:
            LOG.exception("cycle failed")
        time.sleep(cycle_minutes * 60)


def run_cycle(gateway, cctest, sellers, model_prefixes, usage_window_hours,
              threshold_for, permanent_fails, enforce, discord, state,
              seller_model_filter=None):
    seller_model_filter = seller_model_filter or {}
    channels = None
    for name, base_url, seller_key in sellers:
        if channels is None:
            try:
                channels = gateway.list_channels()
            except Exception as e:
                LOG.warning("channel list failed (%s); skipping this cycle", e)
                return
        allowed = seller_model_filter.get(name)
        for channel in expand_seller_to_channels(channels, name, base_url, seller_key):
            process_channel(
                gateway, cctest, channel, base_url, seller_key, model_prefixes,
                usage_window_hours, threshold_for, permanent_fails, enforce,
                discord, state, channels, allowed,
            )
            save_state(state)


def is_gateway_routed(base_url):
    """True when the seller entry points at our own gateway (Selora's
    fingerprint-gated key requires the Go client, so checks ride the
    gateway and land on whatever channel the router picks)."""
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host in ("vantyr.xyz", "gateway", "localhost", "127.0.0.1") or host.endswith(".vantyr.xyz")


def process_verdict(gateway, cctest, channel, base_url, seller_key, model,
                    verdict, threshold_for, enforce, discord, state, channels_snapshot):
    """Apply a verdict to (channel, model): per-model fail counting and
    failover escalation. Shared by the nominal path and the
    serving-channel attribution path."""
    name = channel["name"]
    channel_id = int(channel["id"])
    ch_state = state.setdefault(
        name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    if verdict in BAD_VERDICTS:
        ch_state["fails"] += 1
        model_fails = ch_state.setdefault("model_fails", {})
        model_fails[model] = model_fails.get(model, 0) + 1
        threshold = threshold_for(name)
        if model_fails[model] >= threshold:
            failover_model(
                gateway, channel, ch_state, name, model, verdict,
                enforce, discord, channels_snapshot,
            )
    elif verdict in PASS_VERDICTS:
        ch_state["fails"] = 0
        ch_state.setdefault("model_fails", {}).pop(model, None)


def process_channel(gateway, cctest, channel, base_url, seller_key, model_prefixes,
                    usage_window_hours, threshold_for, permanent_fails, enforce,
                    discord, state, channels_snapshot, model_allowlist=None):
    name = channel["name"]
    channel_id = int(channel["id"])
    ch_state = state.setdefault(
    name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    models = [m.strip() for m in (channel.get("models") or "").split(",") if m.strip()]
    if model_allowlist is not None:
        # Restrict to the models this seller entry's key may call (a
        # dedicated monitoring key with limited model permissions).
        models = [m for m in models if m in model_allowlist]
    status = int(channel.get("status") or 0)

    if ch_state.get("quarantined") and status != CHANNEL_MANUALLY_DISABLED:
        # Our quarantine only holds while status == 2. Status 1 means the
        # owner re-enabled (their call wins); status 3 means New API
        # auto-disabled it since — in both cases our state is stale and
        # the native system / owner owns the channel now.
        LOG.info("[%s] quarantined by us but status=%s (owner override or native auto-disable); clearing state", name, status)
        ch_state.update({"quarantined": False, "fails": 0, "permanent": False,
                         "alerted": False, "model": ""})
        save_state(state)

    eligible = [m for m in models if m.lower().startswith(model_prefixes)]

    if ch_state.get("quarantined"):
        if ch_state.get("permanent"):
            # Credit spend stopped after too many consecutive fails;
            # manual re-enable (owner clears state or re-enables + we
            # notice via the owner-override branch above).
            return
        candidate = ch_state.get("model") or (eligible[0] if eligible else None)
        if candidate is None:
            LOG.warning("[%s] quarantined but no eligible model to re-test", name)
            return
        verdict = do_check(cctest, base_url, seller_key, candidate)
        LOG.info("[%s] quarantine re-test %s -> %s", name, candidate, verdict)
        if verdict in PASS_VERDICTS:
            release_quarantine(gateway, ch_state, channel_id, name, enforce, discord)
        elif verdict in BAD_VERDICTS:
            ch_state["fails"] += 1
            if ch_state["fails"] >= permanent_fails:
                ch_state["permanent"] = True
                if not ch_state.get("alerted"):
                    discord_alert(
                        discord,
                        f"cctest: {name} permanently quarantined "
                        f"({candidate}, {ch_state['fails']} consecutive bad verdicts) "
                        f"— manual re-enable required",
                    )
                    ch_state["alerted"] = True
                LOG.warning("[%s] PERMANENT quarantine (%s)", name, candidate)
        else:
            LOG.info("[%s] inconclusive re-test; quarantine unchanged", name)
        save_state(state)
        return

    if status != CHANNEL_ENABLED:
        # Not ours (owner-disabled or auto-disabled): never touch.
        LOG.info("[%s] status=%s (not enabled, not our quarantine); skipping", name, status)
        return

    # Recovery loop: re-check models we removed earlier. A pass means the
    # seller fixed the substitution — re-add the model so traffic can
    # return. Rotate one removed model per cycle. Uses the mapped
    # (upstream) name like the main check.
    removed = ch_state.get("removed_models") or {}
    if removed:
        removed_candidate = sorted(removed.keys())[0]
        mapping = parse_model_mapping(channel.get("model_mapping"))
        verdict = do_check(
            cctest, base_url, seller_key,
            mapping.get(removed_candidate, removed_candidate),
        )
        LOG.info("[%s] removed-model re-test %s -> %s", name, removed_candidate, verdict)
        if verdict in PASS_VERDICTS:
            restore_model(gateway, channel, ch_state, name, removed_candidate, enforce, discord)
        elif verdict in BAD_VERDICTS:
            removed[removed_candidate]["last_bad"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        return

    # Refresh the rotation to track model-list changes.
    if eligible != ch_state.get("rotation"):
        ch_state["rotation"] = eligible
        if eligible:
            ch_state["idx"] %= len(eligible)
    rotation = ch_state["rotation"]
    if not rotation:
        return
    candidate = rotation[ch_state["idx"] % len(rotation)]
    ch_state["idx"] = (ch_state["idx"] + 1) % len(rotation)

    # Traffic gate: verifying a model nobody calls burns credits. Our own
    # gateway-routed checks create usage entries — exclude them, else the
    # gate self-sustains dead SKUs in the rotation forever.
    try:
        used = gateway.model_used_recently(
            channel_id, candidate, usage_window_hours,
            exclude_token=MONITOR_TOKEN_NAME,
        )
    except Exception as e:
        LOG.warning("[%s] usage gate failed for %s (%s); testing anyway", name, candidate, e)
        used = True
    if not used:
        LOG.info("[%s] skipping %s: no usage in last %dh", name, candidate, usage_window_hours)
        save_state(state)
        return

    # Check the model under its UPSTREAM name: the channel may rename
    # SKUs via model_mapping (e.g. gpt-6-1-sol -> gpt-6.1-sol on A6;
    # gpt-6-sol -> gpt-5-6-sol on Selora). Sending the customer-facing
    # name to the seller directly gets model_not_allowed errors.
    mapping = parse_model_mapping(channel.get("model_mapping"))
    upstream_candidate = mapping.get(candidate, candidate)
    verdict = do_check(cctest, base_url, seller_key, upstream_candidate)
    LOG.info("[%s] check %s (upstream %s) -> %s", name, candidate, upstream_candidate, verdict)

    # Gateway-routed attribution: a check labeled for this channel may
    # have been served by a DIFFERENT channel (the gateway routes by its
    # own priorities). Look up which channel actually served the model in
    # the last few minutes and attribute the verdict there. Without this,
    # failover actions would be taken against channels that never served
    # the checked request (audit 2026-10-13 defect #1).
    actual_channel = None
    if is_gateway_routed(base_url):
        try:
            actual_channel = gateway.last_channel_for_model(upstream_candidate, window_minutes=15)
        except Exception as e:
            LOG.warning("[%s] serving-channel lookup failed (%s); attributing nominally", name, e)
    if actual_channel is not None and actual_channel != channel_id:
        actual_ch = next(
            (c for c in (channels_snapshot or []) if int(c.get("id") or 0) == actual_channel),
            None,
        )
        if actual_ch:
            LOG.info(
                "[%s] verdict actually served by %s (ch %d) — attributing there",
                name, actual_ch.get("name"), actual_channel,
            )
            process_verdict(
                gateway, cctest, actual_ch, base_url, seller_key, candidate,
                verdict, threshold_for, enforce, discord, state, channels_snapshot,
            )
            # Nominal channel's counters stay untouched (no attribution).
            save_state(state)
            return
        # Serving channel not in the seller set (e.g. a6 while we check
        # selora): still log the cross-attribution for observability.
        LOG.warning(
            "[%s] check routed to non-seller channel %d — verdict not attributed",
            name, actual_channel,
        )

    process_verdict(
        gateway, cctest, channel, base_url, seller_key, candidate,
        verdict, threshold_for, enforce, discord, state, channels_snapshot,
    )
    if verdict in SOFT_VERDICTS:
        now = time.time()
        soft = [t for t in ch_state.get("soft", []) if now - t < 24 * 3600]
        soft.append(now)
        ch_state["soft"] = soft
        if len(soft) >= 3 and not ch_state.get("soft_alerted"):
            discord_alert(
                discord,
                f"cctest: {name} served 3+ soft verdicts (flawed/reversed) in 24h — quality degraded?",
            )
            ch_state["soft_alerted"] = True
        elif len(soft) < 3:
            ch_state["soft_alerted"] = False
    # Inconclusive (None): no state change — fail open.
    save_state(state)


def failover_model(gateway, ch, ch_state, name, model, verdict, enforce, discord, channels_snapshot):
    """Confirmed bad verdict for `model` on this channel: remove the model
    from the channel's list so New API re-routes it to another provider.
    Coverage gate: if no other enabled channel in the same group still
    serves the model, do NOT remove it (a wrong model is still better
    than no model) — alert instead.

    Race safety: the coverage check re-fetches the LIVE channel list at
    removal time. A cycle-start snapshot can be stale — if two channels
    cross their fail threshold for the same model in one cycle, both
    removals would pass a snapshot-based gate (each still "sees" the
    other serving it) and the model would end up with zero providers.
    The live re-fetch closes that window: the second removal sees the
    first one's effect and is blocked. Enforce mode only (observe mode
    never mutates, so the race cannot occur)."""
    remaining = [m for m in (ch.get("models") or "").split(",") if m.strip() and m.strip() != model]
    if not remaining:
        LOG.info("[%s] model %s is the only entry; escalating to channel quarantine instead", name, model)
        if enforce:
            start_quarantine(gateway, ch_state, int(ch["id"]), name, model, verdict, discord)
        else:
            LOG.warning("[%s] OBSERVE-ONLY: would quarantine channel (%s -> %s)", name, model, verdict)
        return
    groups = [g.strip() for g in (ch.get("group") or "").split(",") if g.strip()]
    if enforce:
        # Live list: mutations (ours or the owner's) are visible immediately.
        try:
            live_channels = gateway.list_channels()
        except Exception as e:
            LOG.error("[%s] coverage re-check failed (%s); aborting removal to be safe", name, e)
            return
    else:
        live_channels = channels_snapshot
    covered = any(
        other.get("id") != ch.get("id")
        and int(other.get("status") or 0) == CHANNEL_ENABLED
        and any(g in [og.strip() for og in (other.get("group") or "").split(",")] for g in groups)
        and model in [m.strip() for m in (other.get("models") or "").split(",")]
        for other in live_channels
    )
    if not covered:
        LOG.warning(
            "[%s] FAILOVER BLOCKED for %s: no other enabled channel in %s serves it — keeping the (bad) provider",
            name, model, groups,
        )
        discord_alert(
            discord,
            f"cctest: {name} bad verdict on {model} ({verdict}) but no failover target in {groups} — manual review needed",
        )
        return
    if not enforce:
        LOG.warning("[%s] OBSERVE-ONLY: would remove %s (bad verdict %s) and fail over to another provider", name, model, verdict)
        return
    try:
        gateway.update_channel_models(int(ch["id"]), remaining)
    except Exception as e:
        LOG.error("[%s] model removal FAILED (%s stays listed): %s", name, model, e)
        return
    ch["models"] = ",".join(remaining)
    ch_state.setdefault("removed_models", {})[model] = {
        "verdict": verdict, "removed_at": datetime.now(timezone.utc).isoformat(),
    }
    ch_state.setdefault("model_fails", {}).pop(model, None)
    LOG.warning("[%s] REMOVED %s (verdict %s) — traffic fails over to another provider", name, model, verdict)
    discord_alert(discord, f"cctest: {name} removed model {model} (verdict {verdict}) — traffic now served by another provider")


def restore_model(gateway, ch, ch_state, name, model, enforce, discord):
    """A removed model passes again: re-add it to the channel's list."""
    current = [m.strip() for m in (ch.get("models") or "").split(",") if m.strip()]
    if model in current:
        ch_state.get("removed_models", {}).pop(model, None)
        return
    if not enforce:
        LOG.info("[%s] OBSERVE-ONLY: would re-add %s (passing again)", name, model)
        return
    restored = current + [model]
    try:
        gateway.update_channel_models(int(ch["id"]), restored)
    except Exception as e:
        LOG.error("[%s] model restore FAILED: %s", name, e)
        return
    ch["models"] = ",".join(restored)
    ch_state.get("removed_models", {}).pop(model, None)
    ch_state.get("model_fails", {}).pop(model, None)
    LOG.info("[%s] RESTORED %s (verdict official)", name, model)
    discord_alert(discord, f"cctest: {name} re-added model {model} (verdict official)")


def do_check(cctest, base_url, seller_key, model):
    result = cctest.check(base_url, seller_key, model)
    if result is None:
        return None
    return cctest.verdict_category(result)


def start_quarantine(gateway, ch_state, channel_id, name, model, verdict, discord):
    try:
        gateway.set_status(channel_id, CHANNEL_MANUALLY_DISABLED)
    except Exception as e:
        LOG.error("[%s] quarantine FAILED (channel stays live): %s", name, e)
        return
    ch_state["quarantined"] = True
    ch_state["quarantined_since"] = datetime.now(timezone.utc).isoformat()
    ch_state["model"] = model
    LOG.warning("[%s] QUARANTINED (%s -> %s)", name, model, verdict)
    discord_alert(discord, f"cctest: {name} quarantined ({model}, verdict {verdict})")


def release_quarantine(gateway, ch_state, channel_id, name, enforce, discord):
    if not enforce:
        LOG.info("[%s] OBSERVE-ONLY: would release from quarantine", name)
        return
    try:
        gateway.set_status(channel_id, CHANNEL_ENABLED)
    except Exception as e:
        LOG.error("[%s] release FAILED (channel stays disabled): %s", name, e)
        return
    ch_state.update({"quarantined": False, "fails": 0, "permanent": False,
                     "alerted": False, "model": ""})
    LOG.info("[%s] released from quarantine", name)
    discord_alert(discord, f"cctest: {name} released from quarantine (verdict official)")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
