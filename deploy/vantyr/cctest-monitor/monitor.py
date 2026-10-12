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

Env config (compose maps the CCTEST_* vars in deploy/vantyr/.env):
  GATEWAY_URL            e.g. http://vantyr-gateway:3000
  GATEWAY_TOKEN          PAT with channel operate + log read scopes
  CCTEST_BASE            default https://cctest.ai
  CCTEST_KEY             cct-... API key
  SELLER_CHANNELS        entries "name|base_url|seller_key" separated by ","
                         (pipe separator: URLs contain colons). One entry
                         per seller key: all gateway channels using that
                         same seller key share the entry (channel lookup
                         expands to every channel whose name starts with
                         the entry name). Production runs three sellers:
                         selora-*/a6-* (6 channels over 2 seller keys)
                         and mia-* (Mia Router failover channels,
                         https://miarouter.online).
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

# Verdict categories from cctest.ai/docs (full mode) plus the live-observed
# attribution-mode values (attr_match / attr_swapped, verdictKey field).
# Live observation 2026-10-12: A6 attribution check on claude-fable-5-1
# returned verdictKey attr_swapped, attribution.prediction claude-opus-4-6.
PASS_VERDICTS = {"official", "attr_match"}
SOFT_VERDICTS = {"official_flawed"}
BAD_VERDICTS = {"unofficial", "reversed", "not_claude", "attr_swapped"}

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

    def model_used_recently(self, channel_id, model, window_hours):
        since = int(time.time()) - window_hours * 3600
        query = urllib.parse.urlencode({
            "p": 1, "page_size": 1, "channel": channel_id,
            "model_name": model, "start_timestamp": since,
        })
        payload, status = self._request("GET", f"/api/log/?{query}")
        if status != 200 or not payload.get("success"):
            raise RuntimeError(f"log query failed: {status} {payload}")
        return ((payload.get("data") or {}).get("total") or 0) > 0

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
    covers every gateway channel whose name starts with it (production
    runs three sellers: selora-*/a6-* primary, fallback, and unlimited
    variants over 2 seller keys, plus mia-* failover channels from
    Mia Router)."""
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
    """Resolve one seller entry to the gateway channels it covers:
    every channel whose name starts with the entry's name."""
    matches = [ch for ch in channels if (ch.get("name") or "").startswith(seller_prefix)]
    return matches


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
        known_prefixes=("selora", "a6", "mia"),
    )
    if not sellers:
        park("SELLER_CHANNELS has no valid entries")
        return 1

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
    # same noise tolerance as a6 until live verdicts say otherwise.
    fail_threshold_prefixes = (
        ("selora", max(1, int(os.environ.get("FAIL_THRESHOLD_SELORA", "1")))),
        ("a6", max(1, int(os.environ.get("FAIL_THRESHOLD_A6", "2")))),
        ("mia", max(1, int(os.environ.get("FAIL_THRESHOLD_MIA", "2")))),
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
            )
        except Exception:
            LOG.exception("cycle failed")
        time.sleep(cycle_minutes * 60)


def run_cycle(gateway, cctest, sellers, model_prefixes, usage_window_hours,
              threshold_for, permanent_fails, enforce, discord, state):
    channels = None
    for name, base_url, seller_key in sellers:
        if channels is None:
            try:
                channels = gateway.list_channels()
            except Exception as e:
                LOG.warning("channel list failed (%s); skipping this cycle", e)
                return
        for channel in expand_seller_to_channels(channels, name, base_url, seller_key):
            process_channel(
                gateway, cctest, channel, base_url, seller_key, model_prefixes,
                usage_window_hours, threshold_for, permanent_fails, enforce,
                discord, state,
            )
            save_state(state)


def process_channel(gateway, cctest, channel, base_url, seller_key, model_prefixes,
                    usage_window_hours, threshold_for, permanent_fails, enforce,
                    discord, state):
    name = channel["name"]
    channel_id = int(channel["id"])
    ch_state = state.setdefault(
    name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    models = [m.strip() for m in (channel.get("models") or "").split(",") if m.strip()]
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

    # Traffic gate: verifying a model nobody calls burns credits.
    try:
        used = gateway.model_used_recently(channel_id, candidate, usage_window_hours)
    except Exception as e:
        LOG.warning("[%s] usage gate failed for %s (%s); testing anyway", name, candidate, e)
        used = True
    if not used:
        LOG.info("[%s] skipping %s: no usage in last %dh", name, candidate, usage_window_hours)
        save_state(state)
        return

    verdict = do_check(cctest, base_url, seller_key, candidate)
    LOG.info("[%s] check %s -> %s", name, candidate, verdict)

    if verdict in BAD_VERDICTS:
        ch_state["fails"] += 1
        threshold = threshold_for(name)
        if ch_state["fails"] >= threshold:
            if enforce:
                start_quarantine(gateway, ch_state, channel_id, name, candidate, verdict, discord)
            else:
                # Observe-only: announce every would-fire (counter keeps
                # accumulating so the observe week shows the full tally;
                # a pass resets it, same as enforcement).
                LOG.warning(
                    "[%s] OBSERVE-ONLY: would quarantine (%s -> %s, fails=%d)",
                    name, candidate, verdict, ch_state["fails"],
                )
    elif verdict in PASS_VERDICTS:
        ch_state["fails"] = 0
    elif verdict in SOFT_VERDICTS:
        now = time.time()
        soft = [t for t in ch_state.get("soft", []) if now - t < 24 * 3600]
        soft.append(now)
        ch_state["soft"] = soft
        if len(soft) >= 3 and not ch_state.get("soft_alerted"):
            discord_alert(
                discord,
                f"cctest: {name} served 3+ official_flawed verdicts in 24h — quality degraded?",
            )
            ch_state["soft_alerted"] = True
        elif len(soft) < 3:
            ch_state["soft_alerted"] = False
    # Inconclusive (None): no state change — fail open.
    save_state(state)


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
