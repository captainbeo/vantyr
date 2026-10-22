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

Pinned-key tiers (owner rule 2026-10-18): exactly ONE active (enabled)
pin channel per model — spare pins stay disabled as standbys, so only
the key actually serving traffic is ever checked (the traffic gate
enforces this) and New API's router has a single deterministic path.
When the active pin is caught fake (quarantined), the next standby is
TESTED via cctest BEFORE being enabled (promotion); a failing standby
is marked and the next one is tried the following cycle. Pin channels
never re-test their own fake merchant — balance is only spent on
active keys (one per model per cycle) and one test per swap event.

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
                         channel names a6pin-<model> (the ONE active pin
                         for that model — enabled) and a6pin-<model>-
                         <merchant> (standbys — created disabled). Only
                         the active pin serves and is checked (owner rule
                         2026-10-18: only test what is actually used;
                         balance conservation). The single entry
                         "a6pin|<gateway>|<relay>" covers the WHOLE pin
                         pool (pool auto-discovery, owner rule 2026-10-19):
                         every a6pin-* channel in the gateway is in the
                         pool, and daily keys created by sync_a6_keys (or
                         by hand) get cycle coverage with no .env change.
                         Legacy exact-name entries (a6pin-<model>) still
                         match exactly.
                         Selora's sk-gw- key only authenticates from our
                         gateway's Go client (TLS-fingerprint-gated) — for
                         selora, point the URL at the gateway itself
                         (https://vantyr.xyz) with a Vantyr relay token;
                         checks then ride the real customer path and
                         channel attribution comes from the usage log.
  A6_MANAGE_TOKEN        optional: A6 dashboard token for the key-sync job
  A6_MANAGE_USER         optional: A6 user id (New-Api-User header) for the
                         key-sync job. With both set, every cycle lists A6
                         tokens, parses the owner's "<MODEL> | <merchant>"
                         names, and creates missing pin channels as
                         standbies (reveal rate limit ~5/cycle).
  SICK_WINDOW_MINUTES    sick-pin rotation window, default 60 — an active
                         pin with error logs and zero successes in the
                         window is quarantined + rotated (owner rule
                         2026-10-19: unavailability rotates like a fake).
  MODEL_PREFIXES         comma list, default "claude,gpt"
  USAGE_WINDOW_HOURS     traffic gate, default 168 (7 days)
  CYCLE_MINUTES          default 10
  ENFORCE                false (observe-only) / true
  FAIL_THRESHOLD         consecutive fails before quarantine: default 1
                         for selora-* channels, 2 for a6-*/mia-* channels
  PERMANENT_FAILS        consecutive fails before credit spend stops, default 3
  DISCORD_WEBHOOK        optional alerts
  STATUS_PORT            status/action server port (default 8787) — Caddy
                         proxies /api/cctest/* here; see the status-server
                         section below park()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            raw = resp.read().decode()
            # Discord webhooks answer 204 No Content on success — an empty
            # body is not JSON; return an empty payload instead of raising.
            return (json.loads(raw) if raw.strip() else {}), resp.status
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


# How many recent checks we keep per (channel, model) for the Model Routing
# history dropdown. The latest entry always mirrors last_verdicts.
HISTORY_DEPTH = 3


def record_verdict(ch_state, model, verdict):
    """Remember the latest cctest verdict for (channel, model) — read by
    the status server for the Model Routing admin page. Also appends to a
    capped per-model history (newest first) so the page can show the last
    few checks per merchant, not just the most recent."""
    entry = {
        "verdict": verdict or "inconclusive",
        "at": datetime.now(timezone.utc).isoformat(),
    }
    ch_state.setdefault("last_verdicts", {})[model] = entry
    history = ch_state.setdefault("verdict_history", {}).setdefault(model, [])
    # Newest first; drop any duplicate of this exact check, then cap.
    history.insert(0, entry)
    del history[HISTORY_DEPTH:]


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

    def fix_abilities(self):
        """Rebuild the routing/abilities table (POST /api/channel/fix) —
        idempotent; called after status flips so routing reflects them."""
        payload, http_status = self._request(
            "POST", "/api/channel/fix", {},
        )
        if http_status != 200 or not payload.get("success"):
            raise RuntimeError(f"abilities fix failed: {http_status} {payload}")
        return True

    def create_channel(self, name, key, models, group, base_url, priority=20,
                       model_mapping=None):
        """Create a standby pin channel (POST /api/channel/, mode single).
        Requires the channel:sensitive_write PAT scope. Abilities are built
        automatically on create. `models` may be a list (CSV'd) and
        `model_mapping` a {our-name: upstream-name} dict (JSON'd) — used so a
        single pin can serve a model under both its spellings (e.g. the
        gpt-6-1-sol / gpt-6.1-sol alias pair). Returns True on success."""
        channel = {
            "type": 60,
            "name": name,
            "key": key,
            "base_url": base_url,
            "models": ",".join(models) if isinstance(models, list) else models,
            "group": group,
            "priority": priority,
            "weight": 1,
            "status": 2,  # standby: disabled until promoted
        }
        if model_mapping:
            channel["model_mapping"] = json.dumps(model_mapping)
        payload, http_status = self._request(
            "POST", "/api/channel/",
            {"mode": "single", "channel": channel},
        )
        if http_status != 200 or not payload.get("success"):
            raise RuntimeError(f"channel create failed for {name!r}: {http_status} {payload}")
        return True

    def update_channel_group(self, channel_id, group):
        """Edit only the channel's group list via PUT /api/channel/.
        Safety: group is non-sensitive (controller/channel_authz.go) and
        GORM struct Updates() skips zero values, so the channel key,
        models and every other field are preserved untouched. Abilities
        are rebuilt automatically by the update path."""
        payload, http_status = self._request(
            "PUT", "/api/channel/",
            {"id": channel_id, "group": group},
        )
        if http_status != 200 or not payload.get("success"):
            raise RuntimeError(f"channel group update failed: {http_status} {payload}")
        return True

    def count_logs(self, log_type, channel_id, window_minutes):
        """Total log rows of `log_type` (2=consume/success, 5=error) for one
        channel in the window. Returns None on query failure (never
        misclassifies a channel as sick or healthy on a transport error)."""
        since = int(time.time()) - int(window_minutes) * 60
        query = urllib.parse.urlencode({
            "p": 1, "page_size": 1, "type": log_type,
            "channel": channel_id, "start_timestamp": since,
        })
        payload, status = self._request("GET", f"/api/log/?{query}")
        if status != 200 or not payload.get("success"):
            return None
        return (payload.get("data") or {}).get("total") or 0

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


# ---------------------------------------------------------------------------
# A6 management API (key sync — the owner creates "<MODEL> | <merchant>"
# keys on A6's dashboard daily; this keeps the gateway pin pool in step
# without manual channel creation).
# ---------------------------------------------------------------------------

# Owner's A6-side key naming: "<MODEL> | <merchant ch id>", e.g.
# "FABLE 5 | 4665" → model claude-fable-5, merchant 4665. Map the model
# part of the name to our SKU (the model part uses spaces/dots, our SKUs
# use dashes).
A6_KEY_NAME_TO_SKU = {
    "fable 5": "claude-fable-5",
    "fable 5.1": "claude-fable-5-1",
    "opus 5": "claude-opus-5",
    "opus 5.5": "claude-opus-5-5",
    "sonnet 5": "claude-sonnet-5",
    "sonnet 5.5": "claude-sonnet-5-5",
    "astra": "gpt-6-astra",
    "astra 6": "gpt-6-astra",
    "sol": "gpt-6-sol",
    "6 sol": "gpt-6-sol",
    "6.1 sol": "gpt-6-1-sol",
}

# Model spellings that name the SAME underlying model — a pin serving any of
# them is in the same merchant pool. gpt-6-1-sol is the canonical SKU; the
# cctest.ai dropdown spells it gpt-6.1-sol, and legacy pins were created
# under each spelling. Pool membership, promote and verify treat them as one.
MODEL_ALIASES = {
    "gpt-6-1-sol": {"gpt-6-1-sol", "gpt-6.1-sol"},
    "gpt-6.1-sol": {"gpt-6-1-sol", "gpt-6.1-sol"},
}


def model_pool_names(model):
    """The set of spellings that share one merchant pool for `model`."""
    return MODEL_ALIASES.get(model, {model})


def parse_a6_key_name(raw):
    """'"FABLE 5 | 4665"' → (sku, merchant, channel-name). Name parts are
    case-insensitive; returns (None, None, None) when the name does not
    follow the convention or maps to no known SKU."""
    if not raw:
        return None, None, None
    parts = [p.strip() for p in str(raw).split("|")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None, None, None
    sku = A6_KEY_NAME_TO_SKU.get(parts[0].lower())
    if sku is None:
        return None, None, None
    stem = sku.replace("claude-", "", 1).replace("gpt-", "", 1)
    channel_name = f"a6pin-{stem}-{parts[1]}"
    return sku, parts[1], channel_name


class A6Market:
    """A6's public marketplace listings (no auth): per-model merchant
    availability, price and success telemetry. Used to (a) surface merchant
    health on the dashboard so a manual pick never lands on a dead merchant,
    and (b) rank standby promotion toward healthy cheap merchants instead of
    a blind channel-id order."""

    BASE = "https://a6api.com"

    def search(self, model):
        """[{channel_id, supplier_name, listing_availability,
        recent_success_rate, sample_count, input_price_micros, ...}] for one
        model. Returns [] on any error (health data is advisory)."""
        try:
            payload, status = http_json(
                "GET",
                f"{self.BASE}/api/marketplace/public/channels/search?{urllib.parse.urlencode({'model': model})}",
            )
            if status != 200:
                return []
            items = (payload.get("data") or {}).get("items") or []
            if not isinstance(items, list):
                return []
            return items
        except Exception as e:
            LOG.warning("[market] A6 listing fetch failed for %s: %s", model, e)
            return []

    def health_for(self, model, our_merchant_ids):
        """{merchant_id: {healthy, success_rate, sample_count, available,
        price_micros, supplier}} restricted to our pins. A merchant not on
        the listing (not currently eligible for the model) is unhealthy.
        Merchant ids arrive as strings (channel-name suffixes) but the
        listing's channel_id is an int — compare as strings."""
        our = {str(x) for x in our_merchant_ids}
        out = {}
        for item in self.search(model):
            cid = str(item.get("channel_id"))
            if cid in our:
                success = item.get("recent_success_rate")
                samples = item.get("sample_count") or 0
                avail = item.get("listing_availability")
                disabled = item.get("supplier_channel_disabled") or item.get("user_channel_disabled")
                healthy = (
                    avail == 1
                    and not disabled
                    and (success is None or success >= 9500)
                    and samples >= 10
                )
                out[cid] = {
                    "healthy": bool(healthy),
                    "success_rate": success,
                    "sample_count": samples,
                    "available": avail == 1,
                    "price_micros": item.get("input_price_micros"),
                    "supplier": item.get("supplier_name"),
                }
        return out


class A6Management:
    """A6 dashboard management API client (A6 is a New API fork; the owner's
    dedicated account token list). Key reveal is rate-limited (~5 per batch,
    ~5 min cooldown between batches) — pacing handled by the caller."""

    def __init__(self, base, token, user_id):
        self.base = base.rstrip("/")
        self.token = token
        self.user_id = user_id

    def list_tokens(self):
        """All tokens on the A6 account: [{id, name, ...}, ...]. Name
        follows the "<MODEL> | <merchant>" convention."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "New-Api-User": str(self.user_id),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        url = f"{self.base}/api/token/?p=1&page_size=100"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if not payload.get("success"):
            raise RuntimeError(f"A6 token list failed: {payload}")
        items = (payload.get("data") or {}).get("items") or []
        # Token list may paginate; keep fetching while more pages exist.
        total = (payload.get("data") or {}).get("total") or len(items)
        page = 1
        while len(items) < total:
            page += 1
            url = f"{self.base}/api/token/?p={page}&page_size=100"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            if not payload.get("success"):
                break
            more = (payload.get("data") or {}).get("items") or []
            if not more:
                break
            items.extend(more)
        return items

    def reveal_key(self, token_id):
        """Reveal one token's sk- key. Rate limit is ~5 reveals per batch
        with a ~5 min cooldown after — the sync job paces itself and treats
        a rate-limit response as 'try again next cycle'."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "New-Api-User": str(self.user_id),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        req = urllib.request.Request(
            f"{self.base}/api/token/{token_id}/key",
            data=b"{}", method="POST", headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"A6 key reveal rate-limited/failed: {e.code}") from e
        if not payload.get("success"):
            raise RuntimeError(f"A6 key reveal failed: {payload}")
        key = (payload.get("data") or {}).get("key") or ""
        if not key:
            raise RuntimeError(f"A6 key reveal returned empty key for token {token_id}")
        return key


# ---------------------------------------------------------------------------
# Direct merchant probing (pin verify + promote candidates)
#
# A pin's authenticity question is "does THIS merchant serve the real model",
# which only a check against that merchant's own key can answer. The gateway
# router skips disabled channels, so a gateway-routed check of a standby (or
# of a pin we just rotated off) would land on a different provider and report
# THAT provider's verdict — the 2026-10-21 "verification failed after
# promote" incident. Direct checks use the pin's own A6 key (revealed on
# demand via the management API, cached in memory for the process lifetime).
# ---------------------------------------------------------------------------

# process-local cache: A6 token id (from the channel name's merchant, matched
# to a "<MODEL> | <merchant>" token) → revealed sk- key. Reveals are
# rate-limited (~5/batch); a cache means a standby picked twice in a row (or
# re-checked by the cycle) costs one reveal total, not one per check.
_PIN_KEY_CACHE = {}


def _pin_reveal_key(a6m, channel_name):
    """Resolve a pin channel name to its A6 key via the management API.
    Merchant id = trailing numeric suffix of the channel name; the key is the
    A6 token whose name ends in '| <merchant>' for the pin's model. Cached.
    Returns the sk- key, or None when A6_MANAGE_* is unset / no token
    matches / reveal is rate-limited (None → caller falls back)."""
    if a6m is None:
        return None
    merchant = channel_name.rsplit("-", 1)[-1]
    if not merchant.isdigit():
        return None  # plain-named pin (pre-suffix convention); no direct path
    if channel_name in _PIN_KEY_CACHE:
        return _PIN_KEY_CACHE[channel_name]
    try:
        for token in a6m.list_tokens():
            name = (token.get("name") or "").strip()
            _sku, tok_merchant, _channel = parse_a6_key_name(name)
            if _channel == channel_name or (tok_merchant == merchant and channel_name.endswith("-" + merchant)):
                key = a6m.reveal_key(token.get("id"))
                if key:
                    _PIN_KEY_CACHE[channel_name] = key
                    return key
    except Exception as e:
        LOG.warning("[pin] key reveal for %s failed (%s); cannot direct-check", channel_name, e)
    return None


def sync_a6_keys(gateway, a6m, channels, state, discord, base_url="https://api.a6api.com", group="default,unlimited"):
    """A6 → gateway key sync (owner rule 2026-10-19: every A6 key on the
    management account becomes a standby pin channel for its model).

    Idempotent: A6 tokens whose derived channel name already exists are
    skipped. New keys are revealed (≤ A6_SYNC_BATCH reveals per cycle, the
    A6-side rate limit) and created as standby channels (status 2, P20,
    both groups, exactly the one model). Unknown/unparseable names are
    logged + alerted once per cycle summary, never fatal."""
    reveals_this_cycle = 0
    max_reveals = 5
    existing = {ch.get("name") for ch in channels}
    created, skipped, unmatched = [], 0, []
    try:
        tokens = a6m.list_tokens()
    except Exception as e:
        LOG.warning("[sync] A6 token list failed (%s); sync skipped this cycle", e)
        return
    for token in tokens:
        name = token.get("name") or ""
        sku, merchant, channel_name = parse_a6_key_name(name)
        if channel_name is None:
            if name:
                unmatched.append(name)
            continue
        if channel_name in existing:
            skipped += 1
            continue
        if reveals_this_cycle >= max_reveals:
            LOG.info("[sync] reveal budget reached; %d+ remaining keys sync next cycle", 1)
            break
        try:
            key = a6m.reveal_key(token.get("id"))
        except Exception as e:
            LOG.warning("[sync] reveal failed for %r (%s); will retry next cycle", name, e)
            break
        reveals_this_cycle += 1
        # gpt-6-1-sol is served under two spellings (the cctest.ai dropdown
        # uses the dot form gpt-6.1-sol). Create the pin with both aliases +
        # mapping so ONE pin covers both — keeps the merchant pool unified
        # (no dash/dot duplicate rows for the same merchant).
        models = [sku]
        mapping = None
        if sku == "gpt-6-1-sol":
            models = ["gpt-6-1-sol", "gpt-6.1-sol"]
            mapping = {"gpt-6-1-sol": "gpt-6.1-sol", "gpt-6.1-sol": "gpt-6.1-sol"}
        try:
            gateway.create_channel(channel_name, key, models, group, base_url,
                                   model_mapping=mapping)
        except Exception as e:
            LOG.error("[sync] channel create FAILED for %r: %s", channel_name, e)
            continue
        created.append(channel_name)
        existing.add(channel_name)
        LOG.info("[sync] created standby pin %s for %s (merchant %s)", channel_name, sku, merchant)
    # Reconciliation (owner ask 2026-10-22): a pin whose merchant no longer
    # has a key on the A6 account can never be direct-verified — it falls
    # back to a gateway-routed check that reports ANOTHER merchant's verdict
    # (the 2026-10-22 phantom-5312 confusion). Prune those phantoms so the
    # pool only holds merchants that actually exist on A6. Conservative:
    # disable the channel + alert, never hard-delete (a transient A6 list
    # failure must not wipe the pool — we only prune when the token list
    # loaded successfully).
    a6_merchants = set()
    for token in tokens:
        _sku, tok_merchant, _ch = parse_a6_key_name(token.get("name") or "")
        if tok_merchant:
            a6_merchants.add(tok_merchant)
    # A pin is a merchant pin only when its name ends in "<model-stem>-<digits>"
    # for a KNOWN model stem (a6pin-fable-5-4665). Plain-named legacy pins
    # (a6pin-fable-5) end in a model-name fragment like "5", which is a digit —
    # a bare isdigit() check would misread them as merchant pins. Build the set
    # of valid "stem-" prefixes from the SKU map and require the digit suffix
    # to follow one of them.
    stems = {
        sku.replace("claude-", "", 1).replace("gpt-", "", 1)
        for sku in A6_KEY_NAME_TO_SKU.values()
    }
    def _merchant_pin(name):
        merchant = name.rsplit("-", 1)[-1]
        if not merchant.isdigit():
            return None
        head = name[: -(len(merchant) + 1)]  # strip "-<merchant>"
        for stem in stems:
            if head == f"a6pin-{stem}":
                return merchant
        return None
    pruned = []
    for ch in channels:
        ch_name = ch.get("name") or ""
        if not is_pinned_channel(ch_name):
            continue
        merchant = _merchant_pin(ch_name)
        # Legacy plain-named pins have no merchant id — skip (governed by the
        # cycle, not the A6 key pool).
        if merchant is None:
            continue
        if merchant in a6_merchants:
            continue
        if int(ch.get("status") or 0) == CHANNEL_MANUALLY_DISABLED:
            continue  # already off
        try:
            gateway.set_status(int(ch["id"]), CHANNEL_MANUALLY_DISABLED)
            gateway.fix_abilities()
        except Exception as e:
            LOG.error("[sync] prune FAILED for %r: %s", ch_name, e)
            continue
        pruned.append(ch_name)
        LOG.warning("[sync] pruned phantom pin %s — merchant %s has no A6 key", ch_name, merchant)
    if pruned:
        discord_alert(
            discord,
            f"cctest sync: disabled {len(pruned)} phantom pin(s) with no A6 key: {', '.join(pruned)}",
        )
    state["_sync"] = {
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "created": created,
        "skipped_existing": skipped,
        "unmatched": unmatched,
        "pruned_phantoms": pruned,
    }
    if created:
        discord_alert(discord, f"cctest sync: created {len(created)} standby pin(s): {', '.join(created)}")
    if unmatched:
        LOG.warning("[sync] %d A6 token name(s) not in the SKU map: %s", len(unmatched), ", ".join(unmatched[:5]))


def pin_is_sick(gateway, channel_id, window_minutes):
    """Sick-pin detection (owner rule 2026-10-19): a pin whose recent
    traffic is all failures and no successes is as unusable as a fake —
    rotate it. Returns True (sick), False (healthy), or None (no evidence/
    query failed — NEVER rotate on missing evidence)."""
    errors = gateway.count_logs(5, channel_id, window_minutes)
    if errors is None:
        return None
    if errors == 0:
        return False
    successes = gateway.count_logs(2, channel_id, window_minutes)
    if successes is None:
        return None
    return errors > 0 and successes == 0


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


# ---------------------------------------------------------------------------
# Status + action server (Model Routing admin page support)
#
# The monitor is otherwise outbound-only: verdict and cooldown state lived
# only in this container (state.json + logs + Discord). The admin console
# needs a read surface, so the monitor also serves, on a container-internal
# port (default 8787), proxied by Caddy at /api/cctest/*:
#   GET  /api/cctest/status  admin-gated -> full state projection
#   POST /api/cctest/verify  admin-gated -> run one cctest check now
#   POST /api/cctest/promote admin-gated -> swap a model to the next standby
#   GET  /status             unauthenticated, container-internal debug view
#
# Auth is gateway pass-through: the request's Bearer token is forwarded to
# GATEWAY_URL/api/user/self. Status mapping is deliberate (the SPA's axios
# 401 interceptor refreshes and retries, then logs the user out on a second
# 401): expired/absent session -> 401 (the desired refresh path); valid
# session but role < 10 -> 403 (no refresh loop, no logout); gateway
# unreachable or malformed response -> 503 (page shows the degraded banner).
# ---------------------------------------------------------------------------

# Runtime context for POST actions: set by main() once gateway/cctest/sellers
# exist; stays None when parked (status still works, actions 503).
RUNTIME = None

# Top-level state keys that are not per-channel state entries.
RESERVED_STATE_KEYS = ("bad_standbys", "_meta", "_sync")


def read_display_config():
    """Env mirror of main()'s display-relevant config. Deliberate
    duplication: the status server starts before main() parses env (it must
    answer while parked), so main()'s locals do not exist yet."""
    def env_int(name, default):
        try:
            return max(1, int(os.environ.get(name, str(default))))
        except ValueError:
            return default
    return {
        "enforce": os.environ.get("ENFORCE", "false").lower() in ("1", "true", "yes"),
        "cycle_minutes": env_int("CYCLE_MINUTES", 10),
        "standby_cooldown_hours": env_int("STANDBY_COOLDOWN_HOURS", 3),
        "permanent_fails": max(2, env_int("PERMANENT_FAILS", 3)),
        "thresholds": {
            "a6pin": env_int("FAIL_THRESHOLD_A6PIN", 1),
            "selora": env_int("FAIL_THRESHOLD_SELORA", 1),
            "a6": env_int("FAIL_THRESHOLD_A6", 2),
            "mia": env_int("FAIL_THRESHOLD_MIA", 2),
            "yingz": env_int("FAIL_THRESHOLD_YINGZ", 2),
        },
    }


def status_payload(state, config):
    """Pure projection of the persisted state + display config for the
    admin page. Excludes reserved top-level keys from `channels` so _meta
    and bad_standbys can never leak as pseudo-channel entries."""
    channels = {
        name: entry
        for name, entry in state.items()
        if name not in RESERVED_STATE_KEYS and isinstance(entry, dict)
    }
    # Live A6 merchant health per model's pins (advisory for the dashboard's
    # manual pick + promote ranking). Fetched per request — the marketplace
    # listing is public and page loads are low-frequency. Merchant id is the
    # channel name's trailing numeric suffix; only a6pin channels with a
    # numeric suffix have a marketplace identity. Model comes from the
    # channel's rotation (its own model list), which is the pin's single SKU.
    market = A6Market()
    merchant_health = {}
    pin_models = {}
    for name, entry in channels.items():
        if not (name.startswith("a6pin") and "-" in name):
            continue
        merchant = name.rsplit("-", 1)[-1]
        if not merchant.isdigit():
            continue
        rotation = entry.get("rotation") or ([entry["model"]] if entry.get("model") else [])
        for m in rotation:
            if m:
                pin_models.setdefault(m, set()).add(merchant)
    for model, merchant_ids in pin_models.items():
        try:
            merchant_health[model] = market.health_for(model, set(merchant_ids))
        except Exception:
            continue
    return {
        **config,
        "last_cycle_at": (state.get("_meta") or {}).get("last_cycle_at"),
        "last_sync_at": (state.get("_sync") or {}).get("last_sync_at"),
        "channels": channels,
        "bad_standbys": state.get("bad_standbys") or {},
        "merchant_health": merchant_health,
    }


def check_admin(auth_header):
    """Gateway pass-through auth. Returns (authorized, http_status):
    (False, 401) no/malformed token or gateway says expired,
    (False, 403) authenticated but role < 10,
    (False, 503) gateway unreachable or malformed response,
    (True, 200) admin."""
    gateway_url = os.environ.get("GATEWAY_URL")
    if not gateway_url:
        return False, 503
    token = None
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token:
        return False, 401
    payload, status = http_json(
        "GET", gateway_url.rstrip("/") + "/api/user/self", token, timeout=10.0
    )
    if status == 0 or status >= 500:
        return False, 503
    if status != 200 or not payload.get("success"):
        # Gateway rejected the session (401 expired, 403 ban, ...): mirror
        # it as 401 so the SPA's refresh-and-retry interceptor runs.
        return False, 401
    role = (payload.get("data") or {}).get("role")
    if not isinstance(role, int) or role < 10:
        return False, 403
    return True, 200


def find_seller_entry(sellers, channels, channel_name):
    """Resolve (base_url, seller_key) for the SELLER_CHANNELS entry that
    covers the named channel — same expansion rule as the cycle (exact
    match for a6pin entries, prefix for general sellers)."""
    for name, base_url, seller_key in sellers:
        for ch in expand_seller_to_channels(channels, name, base_url, seller_key):
            if (ch.get("name") or "") == channel_name:
                return base_url, seller_key
    return None


def run_action_verify(body):
    """POST /api/cctest/verify {channel, model}: run one authenticity check
    for a specific pin, on demand.

    Direct-check first: a pin whose merchant cannot serve (or a standby we
    are about to trust) must be checkable WITHOUT routing customer-shaped
    traffic through the gateway ladder — a disabled channel is skipped by
    the router, so a gateway-routed check would land on a different
    provider and its verdict would describe THAT provider (the live
    2026-10-21 "verification failed after promote" bug: the check was
    attributed to mia-failover). The pin's own A6 key is a direct check
    against the merchant, which is exactly what "is this merchant good"
    means. Gateway routing stays for selora-style fingerprint-gated keys,
    whose checks must ride the Go client."""
    channel_name = body.get("channel")
    model = body.get("model")
    if not channel_name or not model:
        return 400, {"error": "body must be {\"channel\": ..., \"model\": ...}"}
    if RUNTIME is None:
        return 503, {"error": "monitor not initialized (parked?)"}
    rt = RUNTIME
    try:
        channels = rt["gateway"].list_channels()
    except Exception as e:
        return 503, {"error": f"channel list failed: {e}"}
    channel = next((c for c in channels if (c.get("name") or "") == channel_name), None)
    if channel is None:
        return 404, {"error": f"channel {channel_name!r} not found"}
    mapping = parse_model_mapping(channel.get("model_mapping"))
    upstream = mapping.get(model, model)

    verdict = None
    checked_direct = False
    # Pinned channels: check the merchant's OWN A6 key directly. The channel
    # list omits keys (controller Omit("key")), so the key comes from the A6
    # management API (revealed on demand, cached). This works for enabled AND
    # standby/disabled pins — the fix for "verification failed after promote".
    if is_pinned_channel(channel_name):
        pin_key = _pin_reveal_key(rt.get("a6m"), channel_name)
        if pin_key:
            pin_base = channel.get("base_url") or "https://api.a6api.com"
            verdict = do_check(rt["cctest"], pin_base, pin_key, upstream)
            checked_direct = True
            LOG.info("[action] verify %s direct against %s -> %s", channel_name, pin_base, verdict)
        else:
            # The pin's own A6 key could not be revealed (no matching token on
            # the A6 account, or reveal rate-limited). A gateway-routed check
            # would land on a DIFFERENT (active) pin and report THAT merchant's
            # verdict as this one's — the 2026-10-22 phantom-5312 incident, where
            # a merchant with no A6 key "verified green" by borrowing the active
            # pin's attr_match. Be honest instead: we cannot verify this merchant.
            merchant = channel_name.rsplit("-", 1)[-1]
            return 409, {"error": (
                f"cannot verify {channel_name!r}: merchant {merchant} has no A6 key "
                f"on the management account (or reveal is rate-limited). The pin cannot "
                f"be checked directly, and a gateway-routed check would test a different "
                f"merchant. Remove this pin or re-add the merchant's key on A6."
            ), "verdict": "unverifiable"}

    if verdict is None:
        # Non-pin (legacy plain-named, or a non-pin channel): fall back to the
        # cycle's seller-entry path (gateway-routed for fingerprint-gated keys).
        entry = find_seller_entry(rt["sellers"], channels, channel_name)
        if entry is None:
            return 400, {"error": f"channel {channel_name!r} has no usable key and is not in SELLER_CHANNELS"}
        base_url, seller_key = entry
        check_name = model if is_gateway_routed(base_url) else upstream
        verdict = do_check(rt["cctest"], base_url, seller_key, check_name)

    # Record + apply the verdict against the channel we actually checked.
    # Direct checks need no gateway-attribution hop: the point is that the
    # verdict describes THIS pin, not whatever the ladder picked.
    ch_state = rt["state"].setdefault(channel_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
    record_verdict(ch_state, model, verdict)
    if checked_direct and verdict in PASS_VERDICTS and ch_state.get("quarantined"):
        # The operator re-verified a pin we quarantined and it now passes —
        # release it (merchant recovered, exactly the recovery loop's job).
        # Only on a passing direct check: an advisory standby verify that
        # fails does not release anything.
        release_quarantine(rt["gateway"], ch_state, int(channel["id"]), channel_name, rt["enforce"], rt["discord"])
    elif not checked_direct:
        # Only run the failover policy for gateway-attributed checks; a
        # direct advisory check of a standby must not itself trigger a
        # quarantine (the operator is inspecting, not routing).
        process_verdict(
            rt["gateway"], rt["cctest"], channel, "", "", model,
            verdict, rt["threshold_for"], rt["enforce"], rt["discord"], rt["state"],
            channels, rt["seller_registry"],
        )
    save_state(rt["state"])
    return 200, {"success": True, "data": {"verdict": verdict or "inconclusive", "channel": channel_name}}


def run_action_promote(body):
    """POST /api/cctest/promote {model, merchant?}: owner-triggered merchant
    rotation. With `merchant` set, promotes THAT specific standby (manual
    pick); without it, promotes the healthiest cheap standby (never a blind
    channel-id order). Quarantines the model's current active pin first,
    then runs the enable-first-verify promote path. Enforce-only."""
    model = body.get("model")
    target_merchant = (body.get("merchant") or "").strip() or None
    if not model:
        return 400, {"error": "body must be {\"model\": ..., \"merchant\": optional}"}
    if RUNTIME is None:
        return 503, {"error": "monitor not initialized (parked?)"}
    if not RUNTIME["enforce"]:
        return 409, {"error": "monitor is in observe-only mode (ENFORCE=false)"}
    rt = RUNTIME
    try:
        channels = rt["gateway"].list_channels()
    except Exception as e:
        return 503, {"error": f"channel list failed: {e}"}
    pool = model_pool_names(model)
    pins = [
        c for c in channels
        if is_pinned_channel(c.get("name") or "")
        and pool & {m.strip() for m in (c.get("models") or "").split(",") if m.strip()}
    ]
    active = next((c for c in pins if int(c.get("status") or 0) == CHANNEL_ENABLED), None)
    if active is None:
        # No active pin (fresh pool or a previous rotation left it dead):
        # promote directly without a quarantine step.
        active = None
    active_name = active["name"] if active else None

    # Candidate standbys (disabled), minus the active pin.
    standbys = [c for c in pins if int(c.get("status") or 0) != CHANNEL_ENABLED]
    if target_merchant:
        standbys = [
            c for c in standbys
            if (c.get("name") or "").endswith(f"-{target_merchant}")
        ]
        if not standbys:
            return 409, {"error": f"no standby pin for {model!r} with merchant {target_merchant!r}"}
    if not standbys:
        return 409, {"error": f"no standby pin available for {model!r}"}

    # Rank candidates by A6 live health (healthy + cheap first) so an
    # automatic promote never lands on a dead/disabled merchant. With an
    # explicit merchant pick the operator's choice wins, but we still flag
    # the health so the page can warn.
    market = A6Market()
    health = market.health_for(model, {c.get("name", "").rsplit("-", 1)[-1] for c in standbys})
    def rank(ch):
        # Higher is better (sorted with reverse=True): healthy first, then
        # highest success rate, then cheapest (negated price).
        merchant = (ch.get("name") or "").rsplit("-", 1)[-1]
        h = health.get(merchant) or {}
        return (
            1 if h.get("healthy") else 0,
            h.get("success_rate") or 0,
            -(h.get("price_micros") or 10**9),
        )
    if not target_merchant:
        standbys.sort(key=rank, reverse=True)
        if not (health.get((standbys[0].get("name") or "").rsplit("-", 1)[-1]) or {}).get("healthy"):
            # Every candidate looks unhealthy on A6's listing — refuse the
            # automatic rotation rather than promote into a dead merchant.
            return 409, {"error": f"no A6-healthy standby for {model!r} (checked {len(standbys)}); pick one manually if you know better"}

    chosen = standbys[0]  # manual pick, or health-ranked top
    chosen_name = chosen.get("name")

    base_url, seller_key = "https://vantyr.xyz", rt.get("relay_token", "")
    if active is not None:
        entry = find_seller_entry(rt["sellers"], channels, active_name)
        if entry is None:
            return 400, {"error": f"channel {active_name!r} is not in SELLER_CHANNELS"}
        base_url, seller_key = entry
        # Quarantine the active pin first — promote_next_standby refuses to
        # act while any pin for the model is enabled (idempotence guard), and
        # the rotate intent is exactly "stop serving from this merchant now".
        ch_state = rt["state"].setdefault(active_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
        ch_state.update({
            "quarantined": True,
            "quarantined_since": datetime.now(timezone.utc).isoformat(),
            "permanent": True,
            "model": model,
        })
        try:
            rt["gateway"].set_status(int(active["id"]), CHANNEL_MANUALLY_DISABLED)
            rt["gateway"].fix_abilities()
        except Exception as e:
            ch_state.update({"quarantined": False, "permanent": False, "model": ""})
            return 503, {"error": f"quarantining {active_name} failed: {e}"}
        LOG.warning("[action] owner rotation: quarantined active pin %s for %s → promoting %s", active_name, model, chosen_name)
        discord_alert(rt["discord"], f"cctest: manual rotation for {model}: {active_name} quarantined → promoting {chosen_name}")
    else:
        LOG.warning("[action] owner rotation: no active pin for %s — promoting %s directly", model, chosen_name)

    # CRITICAL: promote against a POST-quarantine live list. Passing the
    # pre-quarantine snapshot made promote_next_standby's idempotence guard
    # see the pin we just disabled as still-enabled and refuse to promote —
    # leaving the model with zero active pins (live incident 2026-10-21
    # 00:49, fable-5-1 dead until manual repair).
    try:
        fresh = rt["gateway"].list_channels()
    except Exception:
        fresh = channels
    promote_next_standby(
        rt["gateway"], rt["cctest"], active or chosen, base_url, seller_key, model,
        rt["enforce"], rt["discord"], rt["state"], fresh,
        rt["seller_registry"], preferred_name=chosen_name,
    )
    save_state(rt["state"])
    # Report what happened: the promoted standby (if any) is now the enabled
    # pin for the model.
    try:
        after = rt["gateway"].list_channels()
    except Exception:
        after = fresh
    new_active = next(
        (c for c in after
         if is_pinned_channel(c.get("name") or "")
         and int(c.get("status") or 0) == CHANNEL_ENABLED
         and model_pool_names(model) & {m.strip() for m in (c.get("models") or "").split(",") if m.strip()}
         and c.get("name") != active_name),
        None,
    )
    promoted = None
    if new_active is not None:
        promoted = new_active.get("name")
    verdict = None
    if promoted:
        st_state = rt["state"].get(promoted) or {}
        verdict = (st_state.get("last_verdicts") or {}).get(model, {}).get("verdict")
    return 200, {"success": True, "data": {"promoted": promoted, "verdict": verdict, "demoted": active_name}}


class StatusHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status, message):
        self._send_json(status, {"success": False, "message": message})

    def _check_admin(self):
        allowed, status = check_admin(self.headers.get("Authorization"))
        if not allowed:
            if status == 401:
                self._send_error_json(401, "authentication required")
            elif status == 403:
                self._send_error_json(403, "admin role required")
            else:
                self._send_error_json(503, "gateway unavailable")
        return allowed

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/status":
            self._send_json(200, {"success": True, "data": status_payload(load_state(), read_display_config())})
            return
        if path == "/api/cctest/status":
            if not self._check_admin():
                return
            self._send_json(200, {"success": True, "data": status_payload(load_state(), read_display_config())})
            return
        self._send_error_json(404, "not found")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in ("/api/cctest/verify", "/api/cctest/promote"):
            self._send_error_json(404, "not found")
            return
        if not self._check_admin():
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length).decode()) if length else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except (ValueError, json.JSONDecodeError):
            self._send_error_json(400, "invalid JSON body")
            return
        if path == "/api/cctest/verify":
            status, payload = run_action_verify(body)
        else:
            status, payload = run_action_promote(body)
        if status == 200:
            self._send_json(status, payload)
        else:
            self._send_json(status, {"success": False, "message": payload.get("error", "error"), "data": None})

    def log_message(self, format, *args):
        LOG.debug("status-server: %s", format % args)


def start_status_server():
    port = int(os.environ.get("STATUS_PORT", "8787"))
    server = ThreadingHTTPServer(("0.0.0.0", port), StatusHandler)
    threading.Thread(
        target=server.serve_forever, daemon=True, name="cctest-status"
    ).start()
    LOG.info("status server listening on :%d (/status, /api/cctest/*)", port)
    return server


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
    The "a6pin" entry is a POOL prefix (owner rule 2026-10-19): it covers
    EVERY a6pin-* channel in the gateway — daily merchant keys created by
    sync_a6_keys (or by hand) join the pool with zero .env changes. All pin
    checks are gateway-routed with the relay token, so one entry covers
    the whole pool. Exact-name entries like "a6pin-fable-5-1" (one key per
    merchant+model, from the pre-pool .env) still match exactly — the pool
    branch only fires for the bare "a6pin" prefix."""
    if seller_prefix == "a6pin":
        return [ch for ch in channels if (ch.get("name") or "").startswith("a6pin")]
    if seller_prefix.startswith("a6pin"):
        return [ch for ch in channels if (ch.get("name") or "") == seller_prefix]
    return [ch for ch in channels if (ch.get("name") or "").startswith(seller_prefix)]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Serve status even while parked: the admin page must distinguish
    # "monitor parked" (empty channels, last_cycle_at null) from "monitor
    # dead" (502 through Caddy).
    global RUNTIME
    start_status_server()

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
    # A6 key sync (optional: envs A6_MANAGE_TOKEN + A6_MANAGE_USER enable
    # automatic standby-pool creation from the owner's daily A6 keys).
    a6m = None
    a6_manage_token = os.environ.get("A6_MANAGE_TOKEN")
    a6_manage_user = os.environ.get("A6_MANAGE_USER")
    if a6_manage_token and a6_manage_user:
        a6m = A6Management(
            os.environ.get("A6_MANAGE_BASE", "https://a6api.com"),
            a6_manage_token, a6_manage_user,
        )
    else:
        LOG.info("A6 key sync disabled (A6_MANAGE_TOKEN/A6_MANAGE_USER not set)")
    sick_window_minutes = max(1, int(os.environ.get("SICK_WINDOW_MINUTES", "60")))
    # The owner adds keys daily and wants them in the pool fast (owner rule
    # 2026-10-19: as close to real-time as possible). Sync is cheap (token
    # list + ≤5 reveals); the expensive part (cctest checks) stays on the
    # 60-min cycle. Run sync on its own shorter interval.
    sync_interval_minutes = max(1, int(os.environ.get("SYNC_INTERVAL_MINUTES", "5")))

    LOG.info(
        "cctest-monitor starting: enforce=%s cycle=%dm sync=%dm prefixes=%s sellers=%s thresholds(prefix)=%s a6sync=%s",
        enforce, cycle_minutes, sync_interval_minutes, model_prefixes,
        [s[0] for s in sellers], fail_threshold_prefixes, a6m is not None,
    )

    state = load_state()
    # POST actions (verify/promote) share the cycle's runtime objects. The
    # cycle also maintains rt["seller_registry"] for standby promotion.
    RUNTIME = {
        "gateway": gateway,
        "cctest": cctest,
        "sellers": sellers,
        "enforce": enforce,
        "threshold_for": threshold_for,
        "discord": discord,
        "state": state,
        "seller_registry": {},
        "a6m": a6m,
    }
    # Key sync runs on its own fast loop — new A6 keys join the pool within
    # minutes, independent of the (expensive) per-cycle cctest checks.
    if a6m is not None:
        start_sync_loop(a6m, sync_interval_minutes)
    while True:
        try:
            run_cycle(
                gateway, cctest, sellers, model_prefixes, usage_window_hours,
                threshold_for, permanent_fails, enforce, discord, state,
                seller_model_filter, None, sick_window_minutes,
            )
        except Exception:
            LOG.exception("cycle failed")
        time.sleep(cycle_minutes * 60)


def sync_loop(a6m, interval_minutes):
    """Background key-sync loop (daemon thread): pulls the owner's A6 keys
    into the pin pool every `interval_minutes`, independent of the cctest
    cycle so new keys join in minutes, not hours. Best-effort: a failed
    sync retries on the next tick and never blocks the check cycle."""
    while True:
        try:
            if RUNTIME is not None:
                channels = RUNTIME["gateway"].list_channels()
                sync_a6_keys(RUNTIME["gateway"], a6m, channels, RUNTIME["state"], RUNTIME["discord"])
        except Exception:
            LOG.exception("[sync] sync-loop tick failed")
        time.sleep(interval_minutes * 60)


def start_sync_loop(a6m, interval_minutes):
    threading.Thread(
        target=sync_loop, args=(a6m, interval_minutes),
        daemon=True, name="cctest-a6-sync",
    ).start()
    LOG.info("A6 key sync loop started (every %dm)", interval_minutes)


def run_cycle(gateway, cctest, sellers, model_prefixes, usage_window_hours,
              threshold_for, permanent_fails, enforce, discord, state,
              seller_model_filter=None, a6m=None, sick_window_minutes=60):
    seller_model_filter = seller_model_filter or {}
    channels = None
    for name, base_url, seller_key in sellers:
        if channels is None:
            try:
                channels = gateway.list_channels()
            except Exception as e:
                LOG.warning("channel list failed (%s); skipping this cycle", e)
                return
    # A6 key sync (best effort, never fatal): pulls the owner's daily
    # "<MODEL> | <merchant>" keys into the pool as standby channels before
    # the registry is built, so new pins get coverage this same cycle.
    # channel name → seller key, built from ALL seller entries BEFORE any
    # processing: standby promotion must check a standby with the standby's
    # OWN key (each pin is a different per-merchant key), and a promotion
    # triggered while iterating entry N needs entry N+1's key already
    # registered.
    seller_registry = {}
    for name, base_url, seller_key in sellers:
        for ch in expand_seller_to_channels(channels, name, base_url, seller_key):
            seller_registry[ch.get("name")] = seller_key
    # Active pins per model, for sick-pin rotation after their checks.
    active_pins = {}
    for ch in channels:
        if is_pinned_channel(ch.get("name") or "") and int(ch.get("status") or 0) == CHANNEL_ENABLED:
            for m in [x.strip() for x in (ch.get("models") or "").split(",") if x.strip()]:
                active_pins.setdefault(m, ch)
    for name, base_url, seller_key in sellers:
        allowed = seller_model_filter.get(name)
        for channel in expand_seller_to_channels(channels, name, base_url, seller_key):
            process_channel(
                gateway, cctest, channel, base_url, seller_key, model_prefixes,
                usage_window_hours, threshold_for, permanent_fails, enforce,
                discord, state, channels, allowed, seller_registry,
            )
            save_state(state)
    # Sick-pin rotation (owner rule 2026-10-19): a pin with recent failures
    # and zero successes is as unusable as a fake — quarantine + promote,
    # exactly the fake path. Inconclusive cctest verdicts alone never
    # rotate (fail-open), but the gateway's own error log is hard evidence.
    if enforce:
        for model, pin in list(active_pins.items()):
            sick = pin_is_sick(gateway, int(pin["id"]), sick_window_minutes)
            if sick is not True:
                continue
            pin_name = pin.get("name")
            # Re-list live: process_channel (fake-verdict path) may have
            # already rotated this model this cycle, and the snapshot this
            # loop captured is pre-rotation — promoting against it re-enables
            # the very pin we rotated away from (observed live 2026-10-19).
            try:
                live = gateway.list_channels()
            except Exception as e:
                LOG.warning("[sick] live channel list failed (%s); skipping rotation for %s", e, pin_name)
                continue
            live_active = next(
                (ch for ch in live
                 if is_pinned_channel(ch.get("name") or "")
                 and int(ch.get("status") or 0) == CHANNEL_ENABLED
                 and model in [x.strip() for x in (ch.get("models") or "").split(",") if x.strip()]),
                None,
            )
            if live_active is not None and live_active.get("name") != pin_name:
                # A different pin is serving now (rotated earlier this cycle).
                LOG.info("[sick] %s already rotated this cycle — %s is active now", pin_name, live_active.get("name"))
                continue
            if live_active is not None and live_active.get("name") == pin_name:
                # Still the active pin — confirm it is genuinely the one we
                # quarantined (status may have flipped while we iterate).
                pin = live_active
            LOG.warning("[sick] active pin %s (ch %s) failing with no successes — rotating", pin_name, pin.get("id"))
            ch_state = state.setdefault(pin_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
            ch_state.update({
                "quarantined": True,
                "quarantined_since": datetime.now(timezone.utc).isoformat(),
                "permanent": True,
                "model": model,
            })
            try:
                gateway.set_status(int(pin["id"]), CHANNEL_MANUALLY_DISABLED)
                gateway.fix_abilities()
                discord_alert(discord, f"cctest: active pin {pin_name} for {model} is failing with no successes — rotating to next standby")
                fresh = gateway.list_channels()  # post-disable, pre-promotion
                entry = find_seller_entry(sellers, fresh, pin_name)
                if entry:
                    promote_next_standby(
                        gateway, cctest, pin, entry[0], entry[1], model,
                        enforce, discord, state, fresh, seller_registry,
                    )
                else:
                    LOG.error("[sick] %s not covered by any SELLER_CHANNELS entry; quarantined without promotion", pin_name)
            except Exception as e:
                LOG.error("[sick] rotation FAILED for %s (stays active): %s", pin_name, e)
            save_state(state)
    # Freshness marker for the status server: an old last_cycle_at (vs
    # cycle_minutes) visibly signals a broken cycle on the admin page. Not
    # written on the exception path — a crashed cycle keeps the previous
    # stamp, which is exactly the staleness we want to expose.
    state["_meta"] = {"last_cycle_at": datetime.now(timezone.utc).isoformat()}
    save_state(state)


def is_gateway_routed(base_url):
    """True when the seller entry points at our own gateway (Selora's
    fingerprint-gated key requires the Go client, so checks ride the
    gateway and land on whatever channel the router picks)."""
    host = urllib.parse.urlparse(base_url).hostname or ""
    return host in ("vantyr.xyz", "gateway", "localhost", "127.0.0.1") or host.endswith(".vantyr.xyz")


def is_pinned_channel(name):
    """a6pin-<model> channels: deterministic merchant paths (one key per
    merchant per model). Their failover unit is the merchant (swap to a
    standby pin), not the model (remove from seller)."""
    return (name or "").startswith("a6pin")


def promote_next_standby(gateway, cctest, failed_channel, base_url, seller_key,
                         model, enforce, discord, state, channels_snapshot,
                         seller_registry=None, preferred_name=None):
    """Pinned-channel failover (owner rule 2026-10-18): when the active pin
    for a model is caught fake, promote the next standby pin for that
    model.

    Enforcement (A6 client-gating forces gateway-routed checks, and the
    router only picks ENABLED channels, so a disabled standby cannot be
    tested in place): ENABLE the standby first (making it the model's
    only enabled pin — the fake one is already disabled, so promoting
    strictly replaces known-fake with unknown), rebuild routing, THEN
    run the cctest check on it. A fail demotes it immediately (status 2
    + bad_standbys mark, never retried) and the next standby is tried
    the following cycle. Inconclusive verdicts leave it active — the
    regular cycle check keeps watching it.

    Idempotency: promotion stops once any pin for the model is enabled.
    Standby discovery uses MODEL-MEMBERSHIP, not name prefixes —
    a6pin-sonnet-5-* and a6pin-sonnet-5-5-* are different models."""
    if not model:
        LOG.warning("[pin] quarantined pin has no model; no standby search")
        return
    pool = model_pool_names(model)
    # stop if a pin for this model is already active again (idempotence)
    for ch in (channels_snapshot or []):
        if is_pinned_channel(ch.get("name") or "") and int(ch.get("status") or 0) == CHANNEL_ENABLED \
                and pool & {mm.strip() for mm in (ch.get("models") or "").split(",") if mm.strip()}:
            LOG.info("[pin] %s already has an active pin (%s) — no promotion", model, ch.get("name"))
            return
    # standby set = disabled pins serving this model (any alias spelling).
    # Model-membership, not name prefixes — a6pin-sonnet-5-* and
    # a6pin-sonnet-5-5-* are different models; gpt-6-1-sol and gpt-6.1-sol
    # are the SAME model (MODEL_ALIASES).
    # Exclude the failed channel from the standby set — but NOT when it IS
    # the operator's manual pick. run_action_promote passes (active or
    # chosen) as failed_channel; when there is no active pin, that is the
    # chosen standby, and excluding it made a valid manual pick always
    # report "not a standby" (the 2026-10-22 gpt-6-sol no-active-pin bug).
    failed_name = (failed_channel.get("name") or "") if failed_channel else ""
    standbys = [
        ch for ch in (channels_snapshot or [])
        if is_pinned_channel(ch.get("name") or "")
        and int(ch.get("status") or 0) == CHANNEL_MANUALLY_DISABLED
        and pool & {mm.strip() for mm in (ch.get("models") or "").split(",") if mm.strip()}
        and ((ch.get("name") or "") != failed_name or (ch.get("name") or "") == preferred_name)
    ]
    if not standbys:
        discord_alert(
            discord,
            f"cctest: no standby pins left for {model} — active merchant is fake "
            f"and none are in line; traffic rides the general/lower tiers",
        )
        LOG.warning("[pin] NO STANDBY for %s — model rides general tier", model)
        return
    # Cooldown recovery (owner observation 2026-10-19: merchants that were
    # caught fake come back clean — 1169/5312 both real again within
    # hours). A bad mark expires after STANDBY_COOLDOWN_HOURS (default 3
    # per owner rule 2026-10-19): the merchant becomes eligible again and
    # must re-verify via cctest before serving. Fresh (never-tried)
    # standbys are preferred over cooldown-expired ones. Cost bound: at
    # most one re-verification per bad merchant per cooldown window.
    cooldown_seconds = max(1, int(os.environ.get("STANDBY_COOLDOWN_HOURS", "3"))) * 3600
    now = time.time()
    bad_marks = state.setdefault("bad_standbys", {}).setdefault(model, {})
    if isinstance(bad_marks, list):
        # migrate the old list form to {name: marked_at}
        bad_marks = {n: now for n in bad_marks}
        state["bad_standbys"][model] = bad_marks
    fresh = [ch for ch in standbys if ch["name"] not in bad_marks]
    expired = [
        ch for ch in standbys
        if ch["name"] in bad_marks and now - bad_marks[ch["name"]] >= cooldown_seconds
    ]
    if fresh:
        candidates = fresh
    elif expired:
        candidates = expired
        LOG.info("[pin] no fresh standbys for %s — re-trying %d after cooldown",
                 model, len(expired))
    else:
        candidates = []
        if not preferred_name:
            discord_alert(
                discord,
                f"cctest: all standby pins for {model} tested fake (cooldown not "
                f"expired) — traffic rides the general/lower tiers",
            )
            LOG.warning("[pin] ALL standbys bad for %s (in cooldown)", model)
            return
    if preferred_name:
        # A manual pick is an explicit operator override: honor it even when
        # the merchant is bad-marked or fresh pins exist. The enable-first-
        # verify path below still checks the pin before it can serve, so this
        # cannot put an unverified merchant live. The pick must exist among
        # the model's disabled standby pins (not some other channel).
        chosen = next((ch for ch in standbys if ch.get("name") == preferred_name), None)
        if chosen is None:
            # The pick isn't a disabled standby for this model at all.
            discord_alert(
                discord,
                f"cctest: requested standby {preferred_name} for {model} is not "
                f"a standby pin for this model — no promotion",
            )
            LOG.warning("[pin] requested standby %s for %s not a standby; skipping", preferred_name, model)
            return
        if chosen.get("name") in bad_marks:
            age_h = (now - bad_marks[chosen["name"]]) / 3600
            LOG.warning(
                "[pin] manual pick %s for %s overrides a bad mark (%.1fh old) — "
                "operator override, will verify before serving",
                preferred_name, model, age_h,
            )
        standby = chosen
    else:
        if not candidates:
            return
        standby = candidates[0]
    standby_name = standby["name"]
    if not enforce:
        LOG.warning("[pin] OBSERVE-ONLY: would promote standby %s for %s", standby_name, model)
        return
    # ENABLE FIRST (see docstring), rebuild routing, then test.
    try:
        gateway.set_status(int(standby["id"]), CHANNEL_ENABLED)
        gateway.fix_abilities()
    except Exception as e:
        LOG.error("[pin] standby promotion FAILED for %s: %s", standby_name, e)
        return
    LOG.warning("[pin] promoted %s for %s (fake pin disabled) — verifying", standby_name, model)
    discord_alert(discord, f"cctest: promoted standby pin {standby_name} for {model}; verifying authenticity now")
    # The check rides the gateway with the SKU name (gateway-routed
    # checks use customer-facing names; the router now picks this pin as
    # the model's only enabled deterministic path).
    check_name = model
    verdict = do_check(cctest, base_url, seller_key, check_name)
    LOG.info("[pin] standby verification %s (%s) -> %s", standby_name, check_name, verdict)
    st_state = state.setdefault(
        standby_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    record_verdict(st_state, model, verdict)
    if verdict in PASS_VERDICTS:
        LOG.warning("[pin] %s PASSED verification for %s — active pin", standby_name, model)
        bad_marks.pop(standby_name, None)
        state["bad_standbys"][model] = bad_marks
        discord_alert(discord, f"cctest: {standby_name} verified genuine for {model}")
        return
    if verdict in BAD_VERDICTS:
        # demote immediately: model has no clean merchant in this slot;
        # traffic falls to the general/lower tiers until the next
        # standby gets tried next cycle.
        try:
            gateway.set_status(int(standby["id"]), CHANNEL_MANUALLY_DISABLED)
            gateway.fix_abilities()
        except Exception as e:
            LOG.error("[pin] demotion FAILED for %s (stays active!): %s", standby_name, e)
            return
        bad_marks[standby_name] = time.time()
        state["bad_standbys"][model] = bad_marks
        LOG.warning("[pin] standby %s tested FAKE for %s — demoted (cooldown re-verifies after %sh); next in line next cycle", standby_name, model, os.environ.get("STANDBY_COOLDOWN_HOURS", "3"))
        discord_alert(discord, f"cctest: standby {standby_name} for {model} failed verification — demoted, trying the next one")
        return
    LOG.info("[pin] standby %s inconclusive — stays active, watched by the cycle", standby_name)


def process_verdict(gateway, cctest, channel, base_url, seller_key, model,
                    verdict, threshold_for, enforce, discord, state, channels_snapshot,
                    seller_registry=None):
    """Apply a verdict to (channel, model): per-model fail counting and
    failover escalation. Shared by the nominal path and the
    serving-channel attribution path."""
    name = channel["name"]
    channel_id = int(channel["id"])
    ch_state = state.setdefault(
        name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    record_verdict(ch_state, model, verdict)
    if verdict in BAD_VERDICTS:
        ch_state["fails"] += 1
        model_fails = ch_state.setdefault("model_fails", {})
        model_fails[model] = model_fails.get(model, 0) + 1
        threshold = threshold_for(name)
        if model_fails[model] >= threshold:
            failover_model(
                gateway, channel, ch_state, name, model, verdict,
                enforce, discord, channels_snapshot,
                cctest=cctest, base_url=base_url, seller_key=seller_key,
                state=state, seller_registry=seller_registry,
            )
    elif verdict in PASS_VERDICTS:
        ch_state["fails"] = 0
        ch_state.setdefault("model_fails", {}).pop(model, None)


def process_channel(gateway, cctest, channel, base_url, seller_key, model_prefixes,
                    usage_window_hours, threshold_for, permanent_fails, enforce,
                    discord, state, channels_snapshot, model_allowlist=None,
                    seller_registry=None):
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
            # notice via the owner-override branch above). For pinned
            # channels, quarantine resolution is standby promotion, not
            # re-testing the same merchant.
            if is_pinned_channel(name):
                promote_next_standby(
                    gateway, cctest, channel, base_url, seller_key,
                    eligible[0] if eligible else None,
                    enforce, discord, state, channels_snapshot,
                    seller_registry,
                )
            return
        candidate = ch_state.get("model") or (eligible[0] if eligible else None)
        if candidate is None:
            LOG.warning("[%s] quarantined but no eligible model to re-test", name)
            return
        # Pinned channels never re-test their own merchant: the verdict is
        # deterministic, a fail is final for that merchant (owner rule
        # 2026-10-18 — balance only spent on active keys and swaps).
        if is_pinned_channel(name):
            ch_state["permanent"] = True
            if not ch_state.get("alerted"):
                discord_alert(
                    discord,
                    f"cctest: {name} pinned merchant caught fake ({candidate}) "
                    f"— promoting a standby",
                )
                ch_state["alerted"] = True
            LOG.warning("[%s] PIN QUARANTINED (deterministic fail on %s)", name, candidate)
            promote_next_standby(
                gateway, cctest, channel, base_url, seller_key,
                candidate, enforce, discord, state, channels_snapshot,
                seller_registry,
            )
            save_state(state)
            return
        verdict = do_check(cctest, base_url, seller_key, candidate)
        LOG.info("[%s] quarantine re-test %s -> %s", name, candidate, verdict)
        record_verdict(ch_state, candidate, verdict)
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
        record_verdict(ch_state, removed_candidate, verdict)
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
    # gate self-sustains dead SKUs in the rotation forever. PIN channels
    # are exempt: the active pin is the model's front door — an unused
    # SKU's pin must still be checked (fake merchants must not serve
    # unchecked), and a standby is never checked (disabled, skipped
    # above).
    if is_pinned_channel(name):
        used = True
    else:
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

    # Which name does the CHECK use? Gateway-routed checks ride our relay,
    # which routes by the CUSTOMER-FACING SKU — send the SKU (the gateway
    # applies model_mapping itself on the outbound hop). Direct checks
    # talk to the seller, which wants the UPSTREAM name (A6 registers
    # gpt-6.1-sol; sending our SKU gpt-6-1-sol gets model_not_allowed).
    mapping = parse_model_mapping(channel.get("model_mapping"))
    upstream_candidate = mapping.get(candidate, candidate)
    check_name = candidate if is_gateway_routed(base_url) else upstream_candidate
    verdict = do_check(cctest, base_url, seller_key, check_name)
    LOG.info("[%s] check %s (upstream %s) -> %s", name, check_name, upstream_candidate, verdict)

    # Gateway-routed attribution: a check labeled for this channel may
    # have been served by a DIFFERENT channel (the gateway routes by its
    # own priorities). Look up which channel actually served the model in
    # the last few minutes and attribute the verdict there. Without this,
    # failover actions would be taken against channels that never served
    # the checked request (audit 2026-10-13 defect #1).
    actual_channel = None
    if is_gateway_routed(base_url):
        try:
            actual_channel = gateway.last_channel_for_model(check_name, window_minutes=15)
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
                seller_registry,
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
        seller_registry,
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


def failover_model(gateway, ch, ch_state, name, model, verdict, enforce, discord, channels_snapshot,
                   cctest=None, base_url=None, seller_key=None, state=None, seller_registry=None):
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
            # Pinned channels: the quarantine IS the merchant-swap trigger —
            # promote the next standby (enable-first, then verify). Without
            # this the model is left with no active pin until the next
            # cycle's quarantined-re-test branch notices.
            if is_pinned_channel(name):
                promote_next_standby(
                    gateway, cctest, ch, base_url, seller_key, model,
                    enforce, discord, state, channels_snapshot,
                    seller_registry,
                )
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
