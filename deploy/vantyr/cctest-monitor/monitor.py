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
# attr_upgraded (ours, 2026-10-23): attribution detected attr_swapped, but
# the detected model ranks strictly higher than the expected one on the
# tier ladder — an upgrade, treated as a pass (owner rule 2026-10-23).
PASS_VERDICTS = {"official", "attr_match", "attr_upgraded"}
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


_STATE_LOCK = threading.Lock()
# Mutation lock: serialize every operation that changes gateway channel state
# (enable/disable/quarantine/promote/dedup/prune). ThreadingHTTPServer runs
# each verify/promote on its own thread, and the cycle + sync threads run
# concurrently — without this, two promotes interleave: both read the same
# pre-quarantine snapshot, both quarantine the active pin, and both enable
# their standby (the 2026-10-23 audit finding B1: two pins enabled at once
# until the next cycle's dedup). Held for the WHOLE mutation sequence, not
# just the state save — the lock's job is the gateway writes, not the file.
_MUTATION_LOCK = threading.Lock()

# Fast ticks vs the hourly cycle (2026-10-27). The cycle holds the mutation
# lock through each channel's cctest check (30-150s), and the 5-minute breaker
# and the primary sweep took it non-blocking, so they skipped whenever the
# cycle was mid-check: 13 skipped [primary] ticks in 24h, 09:22-09:32 in a row,
# i.e. a Kiro outage in that window would not have failed over. Fast ticks now
# wait for the lock (FAST_TICK_LOCK_WAIT_SECONDS), and the cycle yields to a
# waiting or running fast tick at its next lock boundary. _FAST_ACTIVE counts
# fast ticks from the moment they ask for the lock until they release it.
_FAST_COND = threading.Condition()
_FAST_ACTIVE = 0
# Upper bound on how long the cycle waits for a fast tick to finish (a breaker
# rotation can include one pre-promotion cctest check, up to ~300s).
CYCLE_YIELD_MAX_SECONDS = 600


def _fast_lock_acquire():
    """Mutation lock for the breaker tick and the primary sweep. Waits up to
    FAST_TICK_LOCK_WAIT_SECONDS (default 360: longer than one worst-case
    cctest check, ~300s, so the cycle step in flight always finishes first;
    0 = the old non-blocking try). Returns True when held; release with
    _fast_lock_release()."""
    global _FAST_ACTIVE
    with _FAST_COND:
        _FAST_ACTIVE += 1
    wait = _watchdog_env_int("FAST_TICK_LOCK_WAIT_SECONDS", 360, lo=0)
    acquired = (_MUTATION_LOCK.acquire(timeout=wait) if wait > 0
                else _MUTATION_LOCK.acquire(blocking=False))
    if not acquired:
        _fast_lock_release(held=False)
    return acquired


def _fast_lock_release(held=True):
    global _FAST_ACTIVE
    if held:
        _MUTATION_LOCK.release()
    with _FAST_COND:
        _FAST_ACTIVE -= 1
        _FAST_COND.notify_all()


def _cycle_lock_acquire():
    """Mutation lock for one step of the hourly cycle. A fast tick that is
    waiting or running goes first: the cycle waits for it to finish, then
    takes the lock. Otherwise the cycle waits CYCLE_LOCK_WAIT_SECONDS
    (default 0: skip the step when an operator action holds the lock, the
    old behavior). Returns True when held; release _MUTATION_LOCK."""
    wait = _watchdog_env_int("CYCLE_LOCK_WAIT_SECONDS", 0, lo=0)
    with _FAST_COND:
        if _FAST_ACTIVE:
            _FAST_COND.wait_for(lambda: _FAST_ACTIVE == 0, timeout=CYCLE_YIELD_MAX_SECONDS)
            # The tick just released; a short wait covers anyone who slipped in.
            wait = max(wait, 30)
    return (_MUTATION_LOCK.acquire(timeout=wait) if wait > 0
            else _MUTATION_LOCK.acquire(blocking=False))


def save_state(state):
    # Three writers share this file (cycle thread, sync thread, HTTP action
    # handlers). Without the lock, two writers interleave json.dump into the
    # same .tmp — a truncated/corrupted write then replaces state.json.
    # Serialize the write+replace so state.json is always a complete document.
    with _STATE_LOCK:
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

    def test_channel(self, channel_id, model, timeout=90.0):
        """Live availability probe through New API's own channel test
        (GET /api/channel/test/:id): one minimal streaming completion
        (max_tokens 16) over the channel's real key, base URL and model
        mapping. Works on DISABLED channels and never changes their status —
        TestChannel has none of the scheduled health check's auto-enable /
        auto-disable side effects (verified live 2026-10-28 on ch54/58/75/
        84/90). Returns (ok, latency_ms, detail); latency_ms is None when
        the test failed. Never raises."""
        query = urllib.parse.urlencode({"model": model, "stream": "true"})
        payload, status = http_json(
            "GET", f"{self.base}/api/channel/test/{int(channel_id)}?{query}",
            self.token, timeout=timeout,
        )
        if status != 200:
            return False, None, f"http {status}"
        if not payload.get("success"):
            code = payload.get("error_code") or "failed"
            return False, None, f"{code}: {str(payload.get('message') or '')[:100]}"
        try:
            ms = int(float(payload.get("time") or 0) * 1000)
        except (TypeError, ValueError):
            ms = None
        return True, ms, "ok"

    def sell_prices(self):
        """{model_name: (input $/1M, output $/1M)} — what we charge, from the
        public pricing API. Ratio-priced models only (quota_type 0): New API
        bills model_ratio * 2 dollars per 1M input tokens, output at
        completion_ratio times that, scaled by the default group ratio.
        Per-request-priced models are omitted (no per-token margin)."""
        payload, status = self._request("GET", "/api/pricing")
        if status != 200 or not payload.get("success"):
            raise RuntimeError(f"pricing fetch failed: {status}")
        group = float((payload.get("group_ratio") or {}).get("default") or 1)
        out = {}
        for item in payload.get("data") or []:
            if item.get("quota_type") not in (0, None):
                continue
            ratio = float(item.get("model_ratio") or 0)
            if ratio <= 0:
                continue
            per_in = ratio * 2 * group
            out[item.get("model_name")] = (per_in, per_in * float(item.get("completion_ratio") or 1))
        return out

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

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        """Total log rows of `log_type` (2=consume/success, 5=error) for one
        channel in the window. Returns None on query failure (never
        misclassifies a channel as sick or healthy on a transport error).

        `since_ts` (epoch seconds) overrides the window start — used for the
        post-restore grace so errors that predate a restore cannot count
        toward the next disable (they made the primary flap every 5m)."""
        since = (int(since_ts) if since_ts
                 else int(time.time()) - int(window_minutes) * 60)
        query = urllib.parse.urlencode({
            "p": 1, "page_size": 1, "type": log_type,
            "channel": channel_id, "start_timestamp": since,
        })
        payload, status = self._request("GET", f"/api/log/?{query}")
        if status != 200 or not payload.get("success"):
            return None
        return (payload.get("data") or {}).get("total") or 0

    def recent_consume_logs(self, channel_id, window_minutes, limit=50):
        """Recent type=2 (consume) log ROWS for one channel, newest first —
        the data latency/reliability scoring needs (`other` JSON carries
        `frt` and `stream_status.end_reason`; `use_time` is seconds).
        Returns a list of row dicts, or None on query failure (callers must
        treat None as 'no evidence', never as healthy or sick)."""
        since = int(time.time()) - int(window_minutes) * 60
        query = urllib.parse.urlencode({
            "p": 1, "page_size": int(limit), "type": 2,
            "channel": channel_id, "start_timestamp": since,
        })
        payload, status = self._request("GET", f"/api/log/?{query}")
        if status != 200 or not payload.get("success"):
            return None
        items = (payload.get("data") or {}).get("items")
        return items if isinstance(items, list) else []

    def recent_error_logs(self, channel_id, window_minutes, limit=50, max_rows=1000):
        """Recent type=5 (error) log rows for one channel, newest first —
        `content` carries the status code (e.g. "status_code=502, ...").
        Returns a list of row dicts, or None on query failure.

        PAGINATED (audit H1, 2026-10-25). A single page capped the hard-error
        count while the denominator used the TRUE success count, so the
        error ratio was understated and the 80%-severe breaker could never
        trip on a busy channel: 200 errors / 40 successes (83% failing)
        read as "not sick". We now page until the window is exhausted, with a
        hard `max_rows` bound so one pathological channel cannot stall the
        sweep. Callers that need an exact count must compare against
        count_logs(5, ...) — pin_latency_sick does.
        """
        since = int(time.time()) - int(window_minutes) * 60
        rows = []
        page = 1
        while len(rows) < max_rows:
            query = urllib.parse.urlencode({
                "p": page, "page_size": int(limit), "type": 5,
                "channel": channel_id, "start_timestamp": since,
            })
            payload, status = self._request("GET", f"/api/log/?{query}")
            if status != 200 or not payload.get("success"):
                return None
            data = payload.get("data") or {}
            items = data.get("items")
            if not isinstance(items, list) or not items:
                break
            rows.extend(items)
            total = data.get("total")
            if isinstance(total, int) and len(rows) >= total:
                break
            if len(items) < int(limit):
                break
            page += 1
        return rows[:max_rows]

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

    @staticmethod
    def prediction(result):
        """The model cctest actually detected, from attribution.prediction
        (e.g. claude-opus-4-6). Returns None when absent/unparseable."""
        if not isinstance(result, dict):
            return None
        attr = result.get("attribution")
        if isinstance(attr, dict):
            value = attr.get("prediction") or attr.get("predicted") or attr.get("model")
            if isinstance(value, str) and value:
                return value
        # tolerate a top-level prediction field too
        value = result.get("prediction")
        if isinstance(value, str) and value:
            return value
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
    # Kiro serves haiku today; A6 haiku keys bought later join the pool as
    # standby pins like every other model (2026-10-27).
    "haiku 5.5": "claude-haiku-5-5",
}

# Model spellings that name the SAME underlying model — a pin serving any of
# them is in the same merchant pool. gpt-6-1-sol is the canonical SKU; the
# cctest.ai dropdown spells it gpt-6.1-sol, and legacy pins were created
# under each spelling. Pool membership, promote and verify treat them as one.
MODEL_ALIASES = {
    "gpt-6-1-sol": {"gpt-6-1-sol", "gpt-6.1-sol"},
    "gpt-6.1-sol": {"gpt-6-1-sol", "gpt-6.1-sol"},
}

# Accepted-upgrade policy (owner rule 2026-10-23): when an attribution check
# says a channel is serving a model that ranks STRICTLY HIGHER than the
# expected one on the same ladder, the swap is an upgrade — the customer gets
# more than they paid for — so it is not a fail and must not quarantine.
# Each ladder is ordered low -> high; the two families never cross-accept.
#   claude: sonnet-5 < sonnet-5-5 < opus-5 < opus-5-5 < fable-5 < fable-5-1
#   gpt:    sol < 6-1-sol < astra
# This reproduces the owner's table exactly (fable-5-1 is the top of the
# claude ladder, so it accepts nothing; astra is the top of the gpt ladder,
# so it matches only itself).
TIER_LADDERS = [
    ["sonnet-5", "sonnet-5-5", "opus-5", "opus-5-5", "fable-5", "fable-5-1"],
    ["6-sol", "6-1-sol", "6-astra"],
]


def _tier_stem(model):
    """Reduce a model/prediction spelling to its ladder stem: lowercase, drop
    a claude-/gpt- prefix, canonicalize the gpt-6.1-sol dot spelling, and
    collapse spaces to dashes. Returns the stem or None when empty."""
    if not model:
        return None
    s = str(model).strip().lower()
    for prefix in ("claude-", "gpt-"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.replace(" ", "-")
    s = s.replace("6.1-sol", "6-1-sol")  # cctest dropdown spelling
    return s or None


def _tier_match(expected, predicted):
    """Classify a prediction against the expected model on the tier ladders.
    Returns 'higher' (strict upgrade), 'same' (same rung — includes spelling
    aliases like gpt-6.1-sol vs gpt-6-1-sol), or None (different rung lower,
    cross-family, or unparseable — a real swap)."""
    e = _tier_stem(expected)
    p = _tier_stem(predicted)
    if not e or not p:
        return None
    for ladder in TIER_LADDERS:
        if e in ladder and p in ladder:
            if p == e:
                return "same"
            return "higher" if ladder.index(p) > ladder.index(e) else None
    return None


def accepted_upgrade(expected, predicted):
    """True when `predicted` ranks strictly higher than `expected` on the same
    tier ladder. Cross-family, sideways (same rung), lower, or unparseable
    predictions are all False (still a real swap)."""
    return _tier_match(expected, predicted) == "higher"


def model_pool_names(model):
    """The set of spellings that share one merchant pool for `model`."""
    return MODEL_ALIASES.get(model, {model})


def min_active_for(model):
    """Active-pin target for one model's pool: MIN_ACTIVE_PINS (default 2),
    overridden per model by MIN_ACTIVE_PINS_BY_MODEL ("claude-fable-5-1:3,
    gpt-6-astra:3"; any alias spelling). Malformed values fall back to the
    default (a typo must never disable a pool or crash the cycle)."""
    try:
        default = max(1, int(os.environ.get("MIN_ACTIVE_PINS", "2")))
    except (TypeError, ValueError):
        default = 2
    pool = model_pool_names(model)
    for entry in os.environ.get("MIN_ACTIVE_PINS_BY_MODEL", "").split(","):
        name, sep, value = entry.strip().partition(":")
        if not sep or name.strip() not in pool:
            continue
        try:
            return max(1, int(value.strip()))
        except ValueError:
            LOG.error("bad MIN_ACTIVE_PINS_BY_MODEL entry %r — using %d", entry.strip(), default)
    return default


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


# Model stems from the SKU map — used to distinguish merchant-suffixed pins
# (a6pin-fable-5-4665 → merchant "4665") from legacy plain-named pins
# (a6pin-sonnet-5 → suffix "5" is part of the model, NOT a merchant).
_MODEL_STEMS = {
    sku.replace("claude-", "", 1).replace("gpt-", "", 1)
    for sku in A6_KEY_NAME_TO_SKU.values()
}


def pin_merchant(name):
    """Extract the merchant id from a merchant-suffixed pin name, or None for
    a legacy plain-named pin.

    Longest-match against the SKU-map stems: 'a6pin-fable-5-4665' → stem
    'fable-5' + merchant '4665'; 'a6pin-fable-5-1' → stem 'fable-5-1' is
    itself a model, no merchant → None; 'a6pin-sonnet-5-5-2863' → stem
    'sonnet-5-5' + merchant '2863'.
    """
    if not (name or "").startswith("a6pin-"):
        return None
    rest = name[len("a6pin-"):]
    # Try the longest stem match first so "fable-5-1-3825" resolves to stem
    # "fable-5-1" + merchant "3825", not stem "fable-5" + merchant "1-3825".
    for stem in sorted(_MODEL_STEMS, key=len, reverse=True):
        if rest == stem:
            return None  # bare stem — plain-named legacy pin, no merchant
        if rest.startswith(stem + "-"):
            suffix = rest[len(stem) + 1:]
            if suffix.isdigit():
                return suffix
            # Suffix isn't a bare merchant id — the stem wasn't the right split.
            # Keep trying shorter stems (e.g. "fable-5-1-x" is not a merchant).
    return None


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
        price_micros, supplier}} for every merchant we asked about.
        A merchant NOT on the listing (delisted — cannot be ordered, will
        503) is returned as explicitly unhealthy: healthy=False, available=
        False, unlisted=True. Previously such merchants were simply omitted,
        and callers treated a missing entry as "unknown" instead of dead —
        the 2026-10-23 sonnet-5 outage (auto-promote picked delisted
        merchant 1204). Merchant ids arrive as strings (channel-name
        suffixes) but the listing's channel_id is an int — compare as
        strings.

        Every spelling in the model's pool is searched (2026-10-27): A6
        lists gpt-6-1-sol only as gpt-6.1-sol, so a search for the canonical
        SKU returned nothing and EVERY 6-1-sol merchant read as delisted. The
        ranking then meant nothing and promotion flapped between delisted
        #85 and degraded #89 while eight 97-100% merchants sat unused."""
        our = {str(x) for x in our_merchant_ids}
        # Seed every requested merchant as unlisted/unhealthy; listed ones
        # overwrite with their live telemetry.
        out = {
            cid: {
                "healthy": False,
                "success_rate": None,
                "sample_count": 0,
                "available": False,
                "unlisted": True,
                "price_micros": None,
                "supplier": None,
            }
            for cid in our
        }
        items = []
        for spelling in sorted(model_pool_names(model)):
            items.extend(self.search(spelling))
        for item in items:
            cid = str(item.get("channel_id"))
            # First listing wins when a merchant appears under two spellings.
            if cid in our and out[cid]["unlisted"]:
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
                    "unlisted": False,
                    "price_micros": item.get("input_price_micros"),
                    "output_price_micros": item.get("output_price_micros"),
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

    def wallet_balance_usd(self, quota_per_unit=500000):
        """The account wallet's remaining balance in USD (GET /api/user/self,
        data.quota / quota_per_unit — A6 /api/status reports 500000). Every
        A6 key is unlimited_quota, so this wallet is what every merchant
        spends from (2026-10-27). Raises on any failure."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "New-Api-User": str(self.user_id),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
        req = urllib.request.Request(f"{self.base}/api/user/self", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        if not payload.get("success"):
            raise RuntimeError(f"A6 user/self failed: {payload.get('message')}")
        quota = (payload.get("data") or {}).get("quota")
        if not isinstance(quota, (int, float)):
            raise RuntimeError("A6 user/self returned no quota")
        return quota / float(quota_per_unit)


# A6 wallet low-balance alert (checklist C4, 2026-10-27). An empty wallet
# fails EVERY merchant at once with 403 当前可用额度不足 — the sick rotation
# now ignores those errors (is_wallet_error), so this alert is the signal.
# Alerts once when the balance drops below A6_WALLET_ALERT_USD, once more below
# A6_WALLET_CRITICAL_USD, and re-arms after a top-up lifts it back above the
# warning level (a partial top-up into the low band re-arms only the critical
# alert). A failed balance read never alerts (and never clears).
def check_wallet(a6m, state, discord, warn_usd, critical_usd, quota_per_unit=500000):
    try:
        balance = a6m.wallet_balance_usd(quota_per_unit)
    except Exception as e:
        LOG.warning("[wallet] A6 balance check failed: %s", e)
        return None
    wallet = state.setdefault("_wallet", {})
    wallet["balance_usd"] = round(balance, 2)
    wallet["checked_at"] = datetime.now(timezone.utc).isoformat()
    level = "critical" if balance < critical_usd else "low" if balance < warn_usd else "ok"
    alerted = wallet.get("alerted")  # None | "low" | "critical"
    if level == "ok":
        if alerted:
            LOG.info("[wallet] A6 balance back to $%.2f — alert re-armed", balance)
            discord_alert(discord, f"cctest: A6 wallet topped up — balance ${balance:.2f}")
        wallet["alerted"] = None
    elif level == "critical" and alerted != "critical":
        LOG.warning("[wallet] A6 balance CRITICAL: $%.2f (< $%.2f)", balance, critical_usd)
        discord_alert(discord, f"cctest: CRITICAL — A6 wallet at ${balance:.2f} (below ${critical_usd:.2f}). "
                               f"When it hits $0 every A6 merchant fails with 403. Top up now.")
        wallet["alerted"] = "critical"
    elif level == "low" and alerted is None:
        LOG.warning("[wallet] A6 balance low: $%.2f (< $%.2f)", balance, warn_usd)
        discord_alert(discord, f"cctest: A6 wallet low — ${balance:.2f} left (below ${warn_usd:.2f}). Top up soon.")
        wallet["alerted"] = "low"
    elif level == "low" and alerted == "critical":
        # Partial top-up out of the critical band: no message, but a second
        # drain below critical must page again.
        wallet["alerted"] = "low"
    return balance


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


def _pin_reveal_key(a6m, channel_name, model=None):
    """Resolve a pin channel name to its A6 key via the management API.

    Returns the sk- key, or None when A6_MANAGE_* is unset / no token
    matches / reveal is rate-limited (None → caller falls back).

    MODEL MATTERS (audit BLOCKER 2026-10-25). Merchant ids are reused across
    models — the same merchant sells several SKUs (e.g. 4756 sells fable-5
    AND opus-5-5), and list_tokens() returns them in API order. An earlier
    version matched on the merchant suffix alone, so a pin could be revealed
    with ANOTHER MODEL's key: the check then reported a swap against the
    wrong model, refused a perfectly healthy pin, and bad-marked it for the
    cooldown. Worst case an operator promote quarantined the active pin and
    then refused the standby, leaving the model with zero enabled pins.

    Matching order:
      1. exact derived channel name (unambiguous — encodes the SKU),
      2. merchant suffix AND the token's SKU is in the pin's model pool.
    When `model` is None we fall back to the merchant-only match for
    backwards compatibility, but every caller must pass it.
    """
    if a6m is None:
        return None
    merchant = pin_merchant(channel_name)
    if merchant is None:
        return None  # plain-named legacy pin — no merchant id, no direct path
    if channel_name in _PIN_KEY_CACHE:
        return _PIN_KEY_CACHE[channel_name]
    pool = model_pool_names(model) if model else None
    try:
        for token in a6m.list_tokens():
            name = (token.get("name") or "").strip()
            sku, tok_merchant, derived_channel = parse_a6_key_name(name)
            exact = derived_channel == channel_name
            same_merchant = (
                tok_merchant == merchant
                and channel_name.endswith("-" + merchant)
                and (pool is None or sku in pool)
            )
            if exact or same_merchant:
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
    pruned = []
    # Mutation-locked (non-blocking): the prune disables channels — racing a
    # concurrent promote would let the promote re-enable a pin we just pruned
    # (or prune a standby the promote is about to enable). A busy lock skips
    # the prune this tick; the next 5-min sync retries.
    if _MUTATION_LOCK.acquire(blocking=False):
        try:
            pruned = _prune_phantom_pins(gateway, channels, a6_merchants, discord)
        finally:
            _MUTATION_LOCK.release()
    else:
        LOG.info("[sync] mutation lock busy — prune skipped this tick")
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


def _prune_phantom_pins(gateway, channels, a6_merchants, discord):
    pruned = []
    for ch in channels:
        ch_name = ch.get("name") or ""
        if not is_pinned_channel(ch_name):
            continue
        merchant = pin_merchant(ch_name)
        # Legacy plain-named pins have no merchant id — skip (governed by the
        # cycle, not the A6 key pool).
        if merchant is None:
            continue
        if merchant in a6_merchants:
            continue
        if int(ch.get("status") or 0) == CHANNEL_MANUALLY_DISABLED:
            continue  # already off
        if int(ch.get("status") or 0) == CHANNEL_ENABLED:
            # NEVER prune the active pin — disabling it would strand the model
            # (zero serving pins until the next cycle promotes a standby).
            # Log + alert so the owner re-adds the key or rotates manually.
            LOG.warning("[sync] %s merchant %s has no A6 key but is the ACTIVE pin — "
                        "leaving it live; add the key back on A6 or promote a standby",
                        ch_name, merchant)
            discord_alert(discord, f"cctest sync: {ch_name}'s merchant {merchant} lost its A6 key "
                                   f"but is the ACTIVE pin for the model — NOT pruned "
                                   f"(would strand the model). Re-add the key on A6 or rotate manually.")
            continue
        try:
            gateway.set_status(int(ch["id"]), CHANNEL_MANUALLY_DISABLED)
            gateway.fix_abilities()
        except Exception as e:
            LOG.error("[sync] prune FAILED for %r: %s", ch_name, e)
            continue
        pruned.append(ch_name)
        LOG.warning("[sync] pruned phantom pin %s — merchant %s has no A6 key", ch_name, merchant)
    return pruned


def _row_created_at(row):
    """A log row's created_at as int epoch seconds, or None when absent."""
    try:
        value = row.get("created_at")
        return None if value is None else int(value)
    except (TypeError, ValueError, AttributeError):
        return None


# A6 smart-routing failures that mean THIS merchant's candidate pool is
# exhausted or empty (502/500 "all candidates failed", 503 "pool has no
# active candidate", 503 "every merchant in the subscription pool is
# unavailable"). A6 platform-side 503s (billing DB saturation, relay memory
# guard) hit every merchant at once and are deliberately not listed.
POOL_ERROR_MARKERS = ("智能路由候选均请求失败", "个人智能路由池没有活跃候选", "订阅池内商家当前全部不可用")


def is_pool_error(content):
    text = str(content or "")
    return text.lstrip().startswith("status_code=5") and any(m in text for m in POOL_ERROR_MARKERS)


def pin_pool_dead(gateway, channel_id, window_minutes, streak, since_ts=None):
    """Fast "pool dead" signal (2026-10-27): True when the pin answered at
    least `streak` A6 pool errors since its last success (and since
    `since_ts`, the promotion time). The breaker's ratio rule needs 10 hard
    errors and a 10% share, so a pin whose A6 pool just died after a busy hour
    keeps receiving its share of every request until the hourly cycle; the
    gateway retries those on another channel, but each one costs the customer
    a failed attempt first. Returns None when a log query fails."""
    errors = gateway.recent_error_logs(channel_id, window_minutes)
    ok_rows = gateway.recent_consume_logs(channel_id, window_minutes, limit=1)
    if errors is None or ok_rows is None:
        return None
    last_ok = max((_row_created_at(r) or 0 for r in ok_rows), default=0)
    floor = max(last_ok, int(since_ts or 0))
    streak_rows = [r for r in errors if (_row_created_at(r) or 0) > floor]
    return sum(1 for r in streak_rows if is_pool_error(r.get("content"))) >= streak


def _parse_other(row):
    """`other` is a JSON string column; tolerate missing/invalid."""
    try:
        o = json.loads(row.get("other") or "{}")
        return o if isinstance(o, dict) else {}
    except (ValueError, TypeError):
        return {}


def pin_latency_sick(gateway, channel_id, window_minutes, latency_cfg,
                     since_ts=None):
    """Latency/reliability/degraded-merchant sickness (owner ask 2026-10-22,
    re-applied 2026-10-24): an active pin that serves the REAL model but too
    slowly, too often abandoned, or erroring at a high rate still bleeds
    users — the authenticity check (attr_match) and the error-vs-success
    type check above are BOTH blind to it (a client_gone stream still bills
    quota and reads as success; a merchant 502ing 5% of the time between
    successes never trips "all failures").

    Signals, scored over the channel's recent logs:
      - client_gone ratio over STREAMING consume rows (non-stream rows log
        frt=-1000 with no stream_status on every success — the ch25 false
        positive, 2026-10-22). The ch52 case: 46%.
      - median frt (ms) over streaming rows with normal-size prompts (owner
        refinement 2026-10-27): the mean was skewed by outlier spikes and by
        large prompts whose baseline is legitimately higher. frt == -1000 on
        a STREAM row is a hang (no first token ever — the ch40 case, 11
        hangs at 8% gone). Prompts over 10K input tokens are excluded from
        the frt baseline (large context deserves a higher threshold).
      - hard-error ratio: type=5 rows vs type=2 rows in the window. The
        ch74 opus-5 case: 25 x 502 "smart-routing candidates all failed"
        interleaved with 465 successes — invisible to both older checks.

    Returns True (sick), False (healthy), or None (insufficient evidence /
    query failed — NEVER rotate on missing or thin evidence)."""
    min_samples = latency_cfg["min_samples"]
    frt_ms_threshold = latency_cfg["frt_ms_threshold"]
    client_gone_ratio = latency_cfg["client_gone_ratio"]
    hang_threshold = latency_cfg["hang_threshold"]
    error_ratio_threshold = latency_cfg["error_ratio_threshold"]
    # Hard-error signal: a merchant that interleaves 5xx with successes.
    # Only rows whose content starts with a 5xx status code count —
    # type=5 also contains benign client aborts and upstream 429s that New
    # API already retried elsewhere (recent_error_logs parses the status
    # code from `content`; "status_code=502, ..." is the merchant-side
    # failure that matters, the ch74 opus-5 case).
    error_rows = gateway.recent_error_logs(channel_id, window_minutes, limit=100)
    successes = gateway.count_logs(2, channel_id, window_minutes, since_ts=since_ts)
    if error_rows is None or successes is None:
        return None
    if since_ts:
        # Grace (post-promotion / post-restore) slices the error ROWS too. The
        # success count was sliced but the rows were not, so a re-promoted pin
        # was scored on its previous stint's errors against a handful of fresh
        # successes: fable-5's only pin (ch51) was benched with hard_err=30
        # ok=3 "in grace" (2026-10-27 14:01) and the model went dark. Rows
        # without a timestamp still count (the old behavior).
        error_rows = [r for r in error_rows
                      if _row_created_at(r) is None or _row_created_at(r) >= int(since_ts)]
    hard_errors = sum(
        1 for r in error_rows
        if str(r.get("content") or "").lstrip().startswith("status_code=5")
    )
    total_errors = gateway.count_logs(5, channel_id, window_minutes, since_ts=since_ts)
    if total_errors is None:
        return None
    total = hard_errors + successes
    error_ratio = (hard_errors / total) if total > 0 else 0.0
    # Latency/abandonment signal over streaming consume rows.
    rows = gateway.recent_consume_logs(channel_id, window_minutes)
    if rows is None:
        return None
    stream_rows = [r for r in rows if isinstance(_parse_other(r).get("stream_status"), dict)]
    gone = 0
    hangs = 0
    frts = []
    for row in stream_rows:
        other = _parse_other(row)
        ss = other["stream_status"]
        # client_gone counts ONCE per row (the frt==-1000 branch below used
        # to double-increment it, making the "ratio" exceed 100%). Hangs are
        # a SEPARATE axis with their own counter and threshold — the ch40
        # profile was 11 hangs at 8% gone.
        is_gone = ss.get("end_reason") == "client_gone"
        try:
            frt = int(other.get("frt"))
        except (TypeError, ValueError):
            frt = None
        if is_gone:
            gone += 1
        if frt is not None and frt >= 0:
            # Owner refinement 2026-10-27: only normal-size prompts count
            # toward the latency baseline (large context deserves a higher
            # threshold and was skewing the mean). The prompt size is the log
            # row's prompt_tokens column — other.usage_semantic is a STRING
            # ("anthropic"/"openai") on live rows, not a usage dict (reading
            # it as a dict crashed every cycle, 2026-10-27 04:45).
            try:
                input_tokens = int(row.get("prompt_tokens") or 0)
            except (TypeError, ValueError):
                input_tokens = 0
            if input_tokens <= 10000:
                frts.append(frt)
        elif frt == -1000:
            # Streaming row that never produced a first token = hang.
            # Counted in `hangs` only — NOT in `gone` (separate axis) and
            # NOT in `frts` (the median must stay an honest median of observed
            # first-token times; hangs already trip via hang_threshold).
            hangs += 1
    # Judge latency only with enough streaming traffic (fail-open on thin
    # data); the hard-error ratio uses total row counts so it works even
    # when most traffic is non-streaming (the ch74 case: small prompts,
    # mixed stream/non-stream).
    latency_sick = False
    if len(stream_rows) >= min_samples:
        ratio = gone / len(stream_rows)
        # Owner refinement 2026-10-27: median frt instead of mean — more
        # robust against outlier spikes that skewed the mean above the
        # threshold (large prompts are already excluded from frts).
        if frts:
            sorted_frts = sorted(frts)
            median_frt = sorted_frts[len(sorted_frts) // 2]
        else:
            median_frt = 0
        latency_sick = (ratio >= client_gone_ratio or median_frt >= frt_ms_threshold
                        or hangs >= hang_threshold)
    else:
        ratio = -1.0
        median_frt = -1
    # Error-axis trip requires BOTH a ratio AND an absolute count (owner
    # decision 2026-10-25): at Kiro's bursty volume a quiet 15-minute window
    # can hold ~30 requests, so 3 failures read as 10% and disabled the
    # whole primary on noise. min_errors makes a handful of failures
    # incapable of tripping it no matter how small the denominator.
    min_errors = latency_cfg.get("min_errors", 0)
    error_sick = (total >= min_samples and error_ratio >= error_ratio_threshold
                  and hard_errors >= min_errors)
    sick = latency_sick or error_sick
    LOG.info(
        "[latency] ch %s: hard_err=%d ok=%d (ratio=%.2f, all_err=%d), stream=%d, client_gone=%d (%.0f%%), hangs=%d, median_frt=%dms -> %s",
        channel_id, hard_errors, successes, error_ratio, total_errors, len(stream_rows), gone,
        ratio * 100 if ratio >= 0 else 0, hangs, median_frt, "SICK" if sick else "ok",
    )
    # Thin evidence on BOTH axes → no verdict at all (fail-open). A pin
    # serving a handful of requests an hour must not be judged "healthy"
    # any more than it may be judged "sick".
    if len(stream_rows) < min_samples and total < min_samples:
        return None
    return sick


# A6 wallet exhaustion (2026-10-27): every A6 key on the account is
# unlimited_quota, so "当前可用额度不足" (403) means the ACCOUNT wallet is
# empty — every merchant fails identically and none of them is at fault.
# Rotating on it burns through good standbys and promotes nothing better.
WALLET_ERROR_MARKERS = ("当前可用额度不足", "insufficient_user_quota")


def is_wallet_error(content):
    text = str(content or "")
    return any(marker in text for marker in WALLET_ERROR_MARKERS)


def _non_wallet_error_count(gateway, channel_id, window_minutes, errors, since_ts=None):
    """errors minus the wallet-exhaustion rows among them. Rows the paginated
    query did not return are assumed to be merchant errors (conservative: the
    old behavior). A failed row query also keeps the old behavior. since_ts
    narrows the rows the same way it narrowed `errors` (post-restore grace)."""
    rows = gateway.recent_error_logs(channel_id, window_minutes)
    if rows is None:
        return errors
    wallet = sum(
        1 for r in rows
        if is_wallet_error(r.get("content"))
        and (since_ts is None or int(r.get("created_at") or 0) >= int(since_ts))
    )
    return max(0, errors - wallet)


def pin_is_sick(gateway, channel_id, window_minutes, latency_cfg=None,
                since_ts=None):
    """Sick-pin detection (owner rule 2026-10-19): a pin whose recent
    traffic is all failures and no successes is as unusable as a fake —
    rotate it. With latency_cfg set and enabled, ALSO rotate a pin that
    serves the real model but is too slow / too abandoned / erroring too
    often to be usable (degraded-merchant detection). Returns True (sick),
    False (healthy), or None (no evidence/query failed — NEVER rotate on
    missing evidence)."""
    errors = gateway.count_logs(5, channel_id, window_minutes, since_ts=since_ts)
    if errors is None:
        return None
    # ALL-FAILURES RULE (owner rule 2026-10-19) applies on EVERY path,
    # armed or not: a pin with errors and ZERO successes in the window is
    # unusable no matter what the errors say — an expired key (401), quota
    # exhaustion, or a transport reset is just as fatal as a 5xx. This runs
    # BEFORE the latency branch deliberately: an earlier version deferred to
    # pin_latency_sick first, and because that only counts hard 5xx content,
    # a pin failing 100% of requests with 429/401/transport errors was never
    # rotated at all (regression introduced 2026-10-24, caught by audit).
    # The benign-error exclusion still applies to the RATIO-based checks
    # below, where it prevents false positives on sparse evidence.
    if errors > 0:
        successes = gateway.count_logs(2, channel_id, window_minutes, since_ts=since_ts)
        if successes is None:
            return None
        if successes == 0:
            # Wallet exhaustion is not the merchant's fault (see
            # WALLET_ERROR_MARKERS); the wallet alert covers it. Only the
            # remaining errors can make the pin sick.
            if _non_wallet_error_count(gateway, channel_id, window_minutes, errors, since_ts) == 0:
                LOG.warning("[sick] ch %s: all %d errors are A6 wallet exhaustion — "
                            "not rotating (wallet problem, not merchant)", channel_id, errors)
                return None
            return True
    # No all-failures verdict: fall through to the degraded-merchant signal
    # (slow / abandoned / hard-5xx ratio), which needs enough samples and
    # deliberately excludes benign 429s and client aborts.
    if latency_cfg and latency_cfg.get("enabled"):
        return pin_latency_sick(gateway, channel_id, window_minutes, latency_cfg,
                                since_ts=since_ts)
    return False


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

# ---------------------------------------------------------------------------
# Gateway availability watchdog
#
# Every loop in this process is a *consumer* of the gateway admin API, so a
# dead gateway degrades all of them to the same line — `[primary] sweep
# failed` / `channel list failed` / `sync-loop tick failed` — repeated every
# tick with no escalation. That is exactly what a 23-minute total outage
# looked like on 2026-10-26: Caddy served 357 x 502 to real users while the
# logs showed nothing but a routine-looking sweep error, because every alert
# path in here ends in `discord_alert`, which needs no gateway and so was
# never the thing that failed.
#
# This loop is deliberately dumb and independent: it polls /api/status (an
# unauthenticated liveness route) on a short interval, and pages Discord when
# the gateway has been unreachable for a sustained window. It also reports
# recovery with the measured downtime so an outage is never silent at either
# end. It is the only check that can still speak when everything else is
# down, so it must never depend on gateway auth, channel state, or state.json.
# ---------------------------------------------------------------------------

GATEWAY_WATCHDOG_DOWN_AFTER = 120   # seconds unreachable before paging
GATEWAY_WATCHDOG_INTERVAL = 30      # seconds between probes


def _watchdog_env_int(name, default, lo=1):
    """Module-level because the watchdog starts before main() parses env
    (it must survive a parked monitor). Malformed values fall back to the
    default rather than raising — a bad env var must not cost the one alert
    path that works when everything else is down."""
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        LOG.error("bad %s=%r — using default %s", name, os.environ.get(name), default)
        return default
    return max(lo, value)


def _env_float(name, default, lo=0.0):
    """Module-level float env reader (the sync loop runs outside main()).
    Malformed or out-of-range values fall back to the default."""
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        LOG.error("bad %s=%r — using default %s", name, os.environ.get(name), default)
        return default
    return value if value >= lo else default


def gateway_liveness(base_url, timeout=10.0):
    """True when the gateway answers /api/status. Any HTTP answer counts:
    a 500 still proves the process is up and serving, which is what this
    watchdog distinguishes from 'nothing is listening'."""
    url = base_url.rstrip("/") + "/api/status"
    _payload, status = http_json("GET", url, None, None, timeout=timeout)
    return status != 0


def gateway_watchdog_loop(base_url, discord, interval=GATEWAY_WATCHDOG_INTERVAL,
                          down_after=GATEWAY_WATCHDOG_DOWN_AFTER):
    """Pages when the gateway is unreachable for `down_after` seconds, and
    again when it comes back. Holds no other state: one transition out, one
    transition back, so a long outage produces exactly two messages."""
    LOG.info("[watchdog] gateway liveness probe started: every %ds, alert after %ds down",
             interval, down_after)
    down_since = None
    alerted = False
    while True:
        try:
            up = gateway_liveness(base_url)
        except Exception:
            # A bug in the probe must not kill the watchdog thread.
            LOG.exception("[watchdog] liveness probe failed")
            up = False
        now = time.time()
        if up:
            if alerted and down_since is not None:
                minutes = max(1, int((now - down_since) // 60))
                LOG.warning("[watchdog] gateway REACHABLE again after %dm down", minutes)
                discord_alert(
                    discord,
                    f"cctest: **gateway is back** — {base_url} answered again after "
                    f"~{minutes}m unreachable. Users were seeing 502s for that window.",
                )
            down_since = None
            alerted = False
        else:
            if down_since is None:
                down_since = now
                LOG.warning("[watchdog] gateway unreachable — starting downtime clock")
            elif not alerted and (now - down_since) >= down_after:
                alerted = True
                minutes = max(1, int((now - down_since) // 60))
                LOG.error("[watchdog] gateway DOWN for %dm — paging", minutes)
                discord_alert(
                    discord,
                    f"cctest: **GATEWAY DOWN** — {base_url} has not answered "
                    f"/api/status for {minutes}m. Every API request is failing "
                    f"(Caddy returns 502). Check `docker ps` for vantyr-gateway.",
                )
        time.sleep(interval)


def start_gateway_watchdog(base_url, discord, interval=GATEWAY_WATCHDOG_INTERVAL,
                           down_after=GATEWAY_WATCHDOG_DOWN_AFTER):
    threading.Thread(
        target=gateway_watchdog_loop,
        args=(base_url, discord, interval, down_after),
        daemon=True, name="cctest-gateway-watchdog",
    ).start()


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
RESERVED_STATE_KEYS = ("bad_standbys", "_meta", "_sync", "_wallet",
                       "_standby_health", "_standby_alerts", "_refill",
                       "_standby_sweep")


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
        # Degraded-merchant rotation posture — the admin page must be able
        # to tell "off by design" from "armed" (and spot a typo'd ratio).
        "latency_rotation": {
            "enabled": os.environ.get("LATENCY_ROTATION_ENABLED", "false").lower() in ("1", "true", "yes"),
            "min_samples": env_int("LATENCY_MIN_SAMPLES", 20),
            "frt_ms_threshold": env_int("LATENCY_FRT_MS_THRESHOLD", 10000),
            "client_gone_ratio": os.environ.get("LATENCY_CLIENT_GONE_RATIO", "0.20"),
            "hang_threshold": env_int("LATENCY_HANG_THRESHOLD", 3),
            "error_ratio": os.environ.get("LATENCY_ERROR_RATIO", "0.05"),
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
    whose checks must ride the Go client.

    Mutation-locked (blocking acquire): a verify can release a quarantine
    (gateway write) and consumes a rate-limited A6 key reveal. Two concurrent
    verifies would double-burn the reveal budget and can race the release.
    Blocking is right here — the check itself takes 30-90s, so a short queue
    beats a spurious 409 on the operator's deliberate click.
    """
    channel_name = body.get("channel")
    model = body.get("model")
    if not channel_name or not model:
        return 400, {"error": "body must be {\"channel\": ..., \"model\": ...}"}
    if RUNTIME is None:
        return 503, {"error": "monitor not initialized (parked?)"}
    with _MUTATION_LOCK:
        return _run_action_verify_locked(body, channel_name, model)


def _run_action_verify_locked(body, channel_name, model):
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
        pin_key = _pin_reveal_key(rt.get("a6m"), channel_name, upstream)
        if pin_key:
            pin_base = channel.get("base_url") or "https://api.a6api.com"
            verdict = do_check(rt["cctest"], pin_base, pin_key, upstream)
            checked_direct = True
            LOG.info("[action] verify %s direct against %s -> %s", channel_name, pin_base, verdict)
        else:
            # Merchant-suffixed pin (a6pin-<model>-<digits>) with no A6 key:
            # a gateway-routed check would land on a DIFFERENT (active) pin
            # and report THAT merchant's verdict — the 2026-10-22 phantom-5312
            # incident. Refuse honestly instead of borrowing a green badge.
            # Plain-named legacy pins (a6pin-sonnet-5) have no merchant id —
            # they fall through to the gateway path below (they were never
            # direct-checkable and their verdicts were always gateway-routed).
            merchant = pin_merchant(channel_name)
            if merchant is not None:
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
    if verdict in PASS_VERDICTS and ch_state.get("quarantined"):
        # The operator re-verified a pin we quarantined and it now passes —
        # release it. For a direct check the pass is this merchant's own; for
        # a gateway-routed check (plain-named legacy pins, the only
        # direct-uncheckable kind) the pass proves the model's pool is
        # serving genuine output — either way the quarantine is stale. A
        # failing check never releases anything. release_quarantine now
        # clears state only and NEVER enables (owner spec 2026-10-24), so no
        # one-active guard is needed — the pin stays a standby until a
        # promote picks it up.
        release_quarantine(rt["gateway"], ch_state, int(channel["id"]), channel_name, rt["enforce"], rt["discord"])
    elif verdict in BAD_VERDICTS:
        # A direct check of a STANDBY is advisory — the operator is inspecting,
        # not routing — so it must not quarantine anything. But when the
        # operator verifies the pin that is ACTUALLY SERVING and the verdict is
        # bad, discarding it was a real bug (audit M3, 2026-10-25): the UI went
        # red, the pin stayed enabled, and the fail counter was never touched
        # because process_verdict is skipped for direct checks.
        #
        # For the ACTIVE pin, record the confirmed failure with the normal
        # threshold accounting (process_verdict) so repeated confirms
        # quarantine and fail over exactly as a cycle check would. Guarded on
        # status==enabled so a standby remains advisory.
        if int(channel.get("status") or 0) == CHANNEL_ENABLED:
            LOG.warning(
                "[action] verify found ACTIVE pin %s serving a bad verdict (%s) — "
                "applying the normal fail threshold and failover policy", channel_name, verdict,
            )
            process_verdict(
                rt["gateway"], rt["cctest"], channel, "", "", model,
                verdict, rt["threshold_for"], rt["enforce"], rt["discord"], rt["state"],
                channels, rt["seller_registry"],
            )
        else:
            LOG.info("[action] verify of standby %s returned %s — advisory only, nothing quarantined",
                     channel_name, verdict)
    save_state(rt["state"])
    return 200, {"success": True, "data": {"verdict": verdict or "inconclusive", "channel": channel_name}}


def run_action_promote(body):
    """POST /api/cctest/promote {model, merchant?}: owner-triggered merchant
    rotation. With `merchant` set, promotes THAT specific standby (manual
    pick); without it, promotes the healthiest cheap standby (never a blind
    channel-id order). Quarantines the model's current active pin first,
    then runs the enable-first-verify promote path. Enforce-only.

    Mutation-locked: ThreadingHTTPServer runs concurrent requests on separate
    threads, and the cycle/sync threads mutate channels concurrently. Two
    interleaved promotes would both quarantine the same active pin and both
    enable their standby — two actives, the retired lottery. A busy lock
    means a rotation is already in flight: refuse (409) rather than queue —
    the second click was almost certainly a double-click.
    """
    model = body.get("model")
    target_merchant = (body.get("merchant") or "").strip() or None
    if not model:
        return 400, {"error": "body must be {\"model\": ..., \"merchant\": optional}"}
    if RUNTIME is None:
        return 503, {"error": "monitor not initialized (parked?)"}
    if not _MUTATION_LOCK.acquire(blocking=False):
        return 409, {"error": "another rotation is in flight — retry in a few seconds"}
    try:
        return _run_action_promote_locked(body, model, target_merchant)
    finally:
        _MUTATION_LOCK.release()


def _run_action_promote_locked(body, model, target_merchant):
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

    base_url, seller_key = "https://vantyr.xyz", ""
    if active is not None:
        entry = find_seller_entry(rt["sellers"], channels, active_name)
        if entry is None:
            return 400, {"error": f"channel {active_name!r} is not in SELLER_CHANNELS"}
        base_url, seller_key = entry
    else:
        # No active pin: the post-promotion verification rides the gateway
        # with the standby's own seller entry (the "a6pin" prefix entry is
        # the relay key). Resolve or fail closed — an empty key would make
        # the verification check fail auth.
        entry = find_seller_entry(rt["sellers"], channels, chosen_name)
        if entry is not None:
            base_url, seller_key = entry
        else:
            return 400, {"error": f"channel {chosen_name!r} is not in SELLER_CHANNELS"}

    if active is not None:
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

    # Gateway availability watchdog — started BEFORE the config gate below so
    # it still speaks when the monitor is parked. It is the only alert path
    # that survives a dead gateway (2026-10-26: 23-minute outage, 357 x 502,
    # no page, because every other alert here rides the gateway).
    if os.environ.get("GATEWAY_WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes"):
        if gateway_url:
            start_gateway_watchdog(
                gateway_url,
                os.environ.get("DISCORD_WEBHOOK") or None,
                interval=_watchdog_env_int("GATEWAY_WATCHDOG_INTERVAL", 30, lo=5),
                down_after=_watchdog_env_int("GATEWAY_WATCHDOG_DOWN_AFTER", 120, lo=30),
            )
        else:
            LOG.warning("[watchdog] not started: GATEWAY_URL unset")

    if not (gateway_url and gateway_token and cctest_key):
        park("GATEWAY_URL, GATEWAY_TOKEN, and CCTEST_KEY must all be set")
        return 1
    sellers = parse_seller_channels(
        os.environ.get("SELLER_CHANNELS", ""),
        known_prefixes=("selora", "a6", "a6pin", "mia", "yingz", "kiro"),
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
        # IS the merchant serving a fake. Threshold 2 (owner rule 2026-10-23):
        # one bad verdict might be a transient upstream glitch; two
        # consecutive bad checks is much stronger evidence. Reduces false
        # quarantines of flaky-but-genuine merchants.
        ("a6pin", max(1, int(os.environ.get("FAIL_THRESHOLD_A6PIN", "2")))),
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
    # Degraded-merchant auto-rotation (owner ask 2026-10-22/24): in ADDITION
    # to authenticity (attr_match) and the all-failures sick rule, rotate an
    # active pin whose real traffic is too slow / too abandoned / erroring
    # too often. Defaults OFF (LATENCY_ROTATION_ENABLED unset) — unchanged
    # behavior until the owner arms it after watching the [latency] lines.
    # Thresholds from the live fleet distribution (2026-10-22): healthy fleet
    # runs 0-2% gone / 0.5-8s FRT / <5% hard errors; the bad pins sat at
    # 18-48% gone, 13.9s FRT, or 5%+ 502s. ERROR_RATIO catches the ch74 case
    # (502s interleaved with successes, invisible to the all-failures rule).
    # Parse defensively: a malformed env value must NOT crash-loop the
    # container (restart: unless-stopped), and ratios are clamped into
    # (0, 1] so a typo like "-5" can never arm the whole fleet.
    def _env_int(name, default, lo=1, hi=None):
        try:
            v = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            LOG.error("bad %s=%r — using default %s", name, os.environ.get(name), default)
            v = default
        v = max(lo, v)
        return min(hi, v) if hi is not None else v

    def _env_ratio(name, default):
        try:
            v = float(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            LOG.error("bad %s=%r — using default %s", name, os.environ.get(name), default)
            v = default
        if not (0.0 < v <= 1.0):
            LOG.error("out-of-range %s=%r — clamped to default %s", name, v, default)
            v = default
        return v

    latency_cfg = {
        "enabled": os.environ.get("LATENCY_ROTATION_ENABLED", "false").lower() in ("1", "true", "yes"),
        "min_samples": _env_int("LATENCY_MIN_SAMPLES", 20),
        "frt_ms_threshold": _env_int("LATENCY_FRT_MS_THRESHOLD", 10000, lo=0),
        "client_gone_ratio": _env_ratio("LATENCY_CLIENT_GONE_RATIO", 0.20),
        "hang_threshold": _env_int("LATENCY_HANG_THRESHOLD", 3),
        "error_ratio_threshold": _env_ratio("LATENCY_ERROR_RATIO", 0.05),
    }
    # PRIMARY (non-pin) channels — owner decision 2026-10-25, "Option A".
    # A channel whose name is listed here is the PREFERRED supplier for its
    # models (e.g. kiro-pool at priority 30 outranks every a6pin at 20). The
    # a6pin pins stay enabled as the BACKUP. Without this the primary is
    # invisible to the monitor (is_pinned_channel only matches "a6pin*"), so
    # it is never health-swept and never fails over — a Kiro stop would take
    # four Claude models down with no rotation.
    #
    # Behaviour, when a primary trips the severe-degradation thresholds:
    #   1. DISABLE it, so New API's priority routing falls through to the
    #      a6pin backup for every model it serves (no promotion needed — the
    #      pins are already enabled and below it in priority).
    #   2. Re-enable it automatically once it has been healthy AGAIN for
    #      PRIMARY_RESTORE_MINUTES, staying disabled in between. The
    #      disables/enables are recorded in state so a restart cannot leave
    #      it stuck off.
    primary_channels = tuple(
        n.strip() for n in os.environ.get("PRIMARY_CHANNELS", "").split(",") if n.strip()
    )
    primary_restore_minutes = max(1, int(os.environ.get("PRIMARY_RESTORE_MINUTES", "30")))
    # Live availability probe used to decide a RESTORE (owner decision
    # 2026-10-25, option B). Points at the primary's own API surface: the
    # kiro-proxy speaks Anthropic /v1/messages on :8080. Key is the proxy's
    # own API key. Without these the monitor cannot prove recovery and
    # refuses to restore (safe: stays on the a6pin backup).
    primary_probe = {
        "base_url": os.environ.get("PRIMARY_PROBE_BASE_URL", "").strip(),
        "api_key": os.environ.get("PRIMARY_PROBE_KEY", "").strip(),
        "model": os.environ.get("PRIMARY_PROBE_MODEL", "claude-sonnet-5").strip(),
    }

    # The owner adds keys daily and wants them in the pool fast (owner rule
    # 2026-10-19: as close to real-time as possible). Sync is cheap (token
    # list + ≤5 reveals); the expensive part (cctest checks) stays on the
    # 60-min cycle. Run sync on its own shorter interval.
    sync_interval_minutes = max(1, int(os.environ.get("SYNC_INTERVAL_MINUTES", "5")))

    LOG.info(
        "cctest-monitor starting: enforce=%s cycle=%dm sync=%dm prefixes=%s sellers=%s thresholds(prefix)=%s a6sync=%s latency_rotation=%s (samples>=%d gone>=%.0f%% frt>=%dms hangs>=%d err>=%.0f%%)",
        enforce, cycle_minutes, sync_interval_minutes, model_prefixes,
        [s[0] for s in sellers], fail_threshold_prefixes, a6m is not None,
        latency_cfg["enabled"], latency_cfg["min_samples"],
        latency_cfg["client_gone_ratio"] * 100, latency_cfg["frt_ms_threshold"],
        latency_cfg["hang_threshold"], latency_cfg["error_ratio_threshold"] * 100,
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
        "primary_channels": primary_channels,
        "primary_probe": primary_probe,
    }
    # Key sync runs on its own fast loop — new A6 keys join the pool within
    # minutes, independent of the (expensive) per-cycle cctest checks.
    if a6m is not None:
        start_sync_loop(a6m, sync_interval_minutes)
    # Severe-degradation circuit breaker (owner ask 2026-10-24): the hourly
    # cycle catches a bad merchant within the hour, but a pin failing ~all
    # requests (the ch25 case: 96% hard errors) costs real users that whole
    # window. This watchdog reuses the exact rotation path with a SEVERE-ONLY
    # config on a short interval, so catastrophic pins rotate in minutes, not
    # an hour. Gated on enforce AND the latency flag being armed; fail-open.
    circuit_cfg = {
        "enabled": latency_cfg.get("enabled") and os.environ.get(
            "CIRCUIT_BREAKER_ENABLED", "true").lower() in ("1", "true", "yes"),
        # Owner decision 2026-10-25 (option 1): the FAST breaker trips at a
        # 10% hard-error rate so a Kiro outage fails over to the a6pin
        # backup within one 5-minute tick instead of waiting for 80%
        # catastrophic evidence. Latency/hangs still never trip it alone —
        # only hard (5xx) errors and abandoned streams do, so a slow-but-
        # working primary is not yanked away mid-conversation.
        # Defensive parsing (audit L1): a malformed value must not raise
        # AFTER the status server has started — that produced a restart loop
        # with a working /status, which looks like a hung monitor.
        "min_samples": _env_int("CIRCUIT_MIN_SAMPLES", 15),
        "client_gone_ratio": _env_ratio("CIRCUIT_CLIENT_GONE_RATIO", 0.50),
        "frt_ms_threshold": 10**12,     # latency alone never trips the breaker
        "hang_threshold": 10**9,        # hangs alone never trip it either
        "error_ratio_threshold": _env_ratio("CIRCUIT_ERROR_RATIO", 0.10),
        # Absolute floor (owner decision 2026-10-25): a percentage alone made
        # 3 failures in a quiet 30-request window read as 10% and disabled
        # the whole primary on noise. Require this many hard errors too.
        "min_errors": _env_int("CIRCUIT_MIN_ERRORS", 10),
        # Fast bench (2026-10-27): a pin answering this many A6 pool errors in
        # a row since its last success is benched on the next tick, provided
        # another pin still serves its pool (pin_pool_dead). 0 disables.
        "pool_error_streak": _env_int("CIRCUIT_POOL_ERROR_STREAK", 3, lo=0),
    }
    circuit_window = _env_int("CIRCUIT_WINDOW_MINUTES", 15)
    circuit_interval = _env_int("CIRCUIT_INTERVAL_MINUTES", 5)
    probe_interval = _env_int("PRIMARY_PROBE_INTERVAL_MINUTES", 1)
    if circuit_cfg["enabled"] and enforce:
        start_circuit_breaker(circuit_cfg, circuit_window, circuit_interval,
                              primary_channels, primary_restore_minutes)
        if primary_channels:
            threading.Thread(
                target=primary_probe_loop,
                args=(circuit_cfg, circuit_window, primary_restore_minutes,
                      probe_interval),
                daemon=True, name="cctest-primary-probe",
            ).start()
    while True:
        try:
            run_cycle(
                gateway, cctest, sellers, model_prefixes, usage_window_hours,
                threshold_for, permanent_fails, enforce, discord, state,
                seller_model_filter, None, sick_window_minutes,
                latency_cfg=latency_cfg,
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
                # Persist the sync summary immediately — without this the
                # dashboard's last_sync_at lags by up to a full cycle and a
                # restart between sync and cycle loses created-pin records.
                save_state(RUNTIME["state"])
        except Exception:
            LOG.exception("[sync] sync-loop tick failed")
        # Wallet check in its own try: a failed key sync (gateway down, A6
        # token list error) must not also silence the low-balance alert.
        try:
            if RUNTIME is not None:
                check_wallet(a6m, RUNTIME["state"], RUNTIME["discord"],
                             _env_float("A6_WALLET_ALERT_USD", 10.0),
                             _env_float("A6_WALLET_CRITICAL_USD", 3.0))
                save_state(RUNTIME["state"])
        except Exception:
            LOG.exception("[wallet] wallet check tick failed")
        # Standby health sweep (2026-10-28) in its own try, on its own pace:
        # every STANDBY_SWEEP_HOURS (default 3; 0 disables). One tiny live
        # probe per standby, read-only on channel status.
        try:
            sweep_every = _watchdog_env_int("STANDBY_SWEEP_HOURS", 3, lo=0) * 3600
            if RUNTIME is not None and RUNTIME.get("enforce") and sweep_every:
                last = (RUNTIME["state"].get("_standby_sweep") or {}).get("ts") or 0
                if time.time() - last >= sweep_every:
                    sweep_standby_health(RUNTIME["gateway"], RUNTIME["state"], RUNTIME["discord"])
        except Exception:
            LOG.exception("[standby] health sweep tick failed")
        time.sleep(interval_minutes * 60)


def start_sync_loop(a6m, interval_minutes):
    threading.Thread(
        target=sync_loop, args=(a6m, interval_minutes),
        daemon=True, name="cctest-a6-sync",
    ).start()
    LOG.info("A6 key sync loop started (every %dm)", interval_minutes)


def probe_primary_live(base_url, api_key, model, timeout=60):
    """LIVE availability probe for a disabled primary (owner decision
    2026-10-25, "Option B"): send the smallest real completion and require a
    valid assistant message back.

    Why not /health: the kiro-proxy's /health reports PROCESS liveness only
    ({"status":"ok","uptime":...}). During the 2026-10-24 outage — 429s and
    stalled upstream reads for 300s — /health was green the whole time while
    every request failed. Proving "Kiro is available again" means exercising
    the real path: auth → upstream → a returned message.

    Cost note: the kiro-proxy injects a ~6.5k-token system prompt, so each
    probe costs ~6.5k input tokens. Probes run ONLY while the primary is
    disabled, at most once per cycle — bounded and negligible.

    Returns (ok: bool, detail: str). ok=True ONLY on a 2xx carrying a
    well-formed assistant message; every other outcome (timeout, 429, 5xx,
    malformed body) is ok=False so the primary stays disabled. Never raises.
    """
    import json as _json
    body = _json.dumps({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not (200 <= resp.status < 300):
                return False, f"http {resp.status}"
            payload = _json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        # 429/5xx from the proxy = still unavailable. This is the signature
        # of the outage we are guarding against.
        return False, f"http {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"
    if not isinstance(payload, dict):
        return False, "malformed body"
    content = payload.get("content")
    if payload.get("type") != "message" or not isinstance(content, list) or not content:
        return False, "no assistant message in response"
    usage = payload.get("usage") or {}
    return True, f"ok (out={usage.get('output_tokens')}, model={payload.get('model')})"


def _primary_sick_since(gateway, channel_id, window_minutes, circuit_cfg, since_ts):
    """Sick check for the PRIMARY during its post-restore grace: identical
    scoring, but the log queries start at `since_ts` (the restore time) so
    errors from before the restore cannot re-trip the breaker.

    Why this exists (owner decision 2026-10-25): the breaker's 15-minute
    window outlives a 5-minute restore, so the first sweep after a restore
    kept seeing the SAME failures that caused the outage and disabled Kiro
    again — a permanent 5-minute disable/restore flap, each flap briefly
    pushing ~all Claude traffic onto the a6pin backup.

    Needs a minimum sample before judging, otherwise 1 error in 10s would
    trip it; returns None (no verdict) when the window since the restore is
    too small — the caller treats None as "not sick", which is correct:
    the primary just proved itself with a live probe.
    """
    min_samples = max(1, int(circuit_cfg.get("min_samples") or 15))
    errors = gateway.count_logs(5, channel_id, window_minutes, since_ts=since_ts)
    successes = gateway.count_logs(2, channel_id, window_minutes, since_ts=since_ts)
    if errors is None or successes is None:
        return None
    total = errors + successes
    if total < min_samples:
        LOG.info("[primary] post-restore window has %d request(s) (< %d) — no verdict yet",
                 total, min_samples)
        return None
    if errors > 0 and successes == 0:
        return True
    return pin_latency_sick(gateway, channel_id, window_minutes, circuit_cfg,
                            since_ts=since_ts)


def sweep_primary_channels(circuit_cfg, window_minutes, restore_minutes, restore_only=False):
    """Health-sweep the PRIMARY (non-pin) channels and fail over / restore.

    Owner decision 2026-10-25 ("Option A"): kiro-pool is the preferred
    supplier and the a6pin pins are the backup. The monitor only ever
    inspected channels named a6pin*, so the primary — by then carrying ~98%
    of Claude traffic — was never health-checked and never failed over.

    Failover model differs from pins: there is nothing to promote. The
    primary outranks the pins, so DISABLING it makes New API's priority
    routing fall through to the already-enabled a6pin backup. Restore is the
    inverse and must be automatic, or a single bad window leaves the (often
    cheaper) primary off forever.

    Returns the number of primaries acted on.
    """
    rt = RUNTIME
    if rt is None or not rt.get("enforce") or not rt.get("primary_channels"):
        return 0
    if not _fast_lock_acquire():
        LOG.warning("[primary] mutation lock still busy after the wait — skipping this tick")
        return 0
    acted = 0
    try:
        channels = rt["gateway"].list_channels()
        state = rt["state"]
        prim_state = state.setdefault("_primary", {})
        wanted = set(rt["primary_channels"])
        now = time.time()

        for ch in channels:
            name = ch.get("name") or ""
            if name not in wanted:
                continue
            cid = int(ch["id"])
            enabled = int(ch.get("status") or 0) == CHANNEL_ENABLED
            entry = prim_state.setdefault(name, {"disabled_at": None, "healthy_since": None})

            if enabled and restore_only:
                # Fast probe pass (every PRIMARY_PROBE_INTERVAL_MINUTES): only
                # restore disabled primaries; disable decisions stay on the
                # 5-minute breaker tick so a burst of noise cannot flip the
                # primary off more often than the evaluation window allows.
                continue
            if enabled:
                # Post-restore grace (owner decision 2026-10-25): after a
                # restore, errors from BEFORE it are still inside the window
                # and would immediately re-trip the breaker — the live
                # 5-minute disable/restore flap. Only evidence gathered since
                # the restore counts. Measured on the log scan below; the
                # window still bounds how far back we look.
                grace_since = entry.get("restored_at")
                if grace_since and now - grace_since < window_minutes * 60:
                    LOG.info("[primary] %s in post-restore grace (%ds of %dm) — "
                             "judging only evidence since the restore",
                             name, int(now - grace_since), window_minutes)
                    sick = _primary_sick_since(rt["gateway"], cid, window_minutes,
                                               circuit_cfg, grace_since)
                else:
                    sick = pin_is_sick(rt["gateway"], cid, window_minutes,
                                       latency_cfg=circuit_cfg)
                if sick is True:
                    try:
                        rt["gateway"].set_status(cid, CHANNEL_MANUALLY_DISABLED)
                        rt["gateway"].fix_abilities()
                    except Exception as e:
                        LOG.error("[primary] FAILED to disable %s: %s", name, e)
                        continue
                    entry["disabled_at"] = now
                    entry["healthy_since"] = None
                    acted += 1
                    LOG.warning(
                        "[primary] %s (ch %s) degraded — DISABLED, traffic fails over to "
                        "the a6pin backup for its models", name, cid,
                    )
                    discord_alert(
                        rt["discord"],
                        f"cctest: primary {name} degraded — disabled; a6pin backup now serving. "
                        f"Restores automatically as soon as a live probe succeeds "
                        # Module-level helper: _env_int is local to main(), and
                        # calling it here raised NameError AFTER the disable,
                        # so the alert never sent and save_state was skipped
                        # (2026-10-25..27, caught by the test suite's tracebacks).
                        f"(checked every {_watchdog_env_int('PRIMARY_PROBE_INTERVAL_MINUTES', 1)}m).",
                    )
                else:
                    entry["healthy_since"] = None
            else:
                # Disabled by us? Only restore what WE turned off.
                if entry.get("disabled_at") is None:
                    LOG.debug("[primary] %s is disabled but not by us — leaving it", name)
                    continue
                # Restore requires a LIVE proof (owner decision 2026-10-25).
                # A disabled primary serves no traffic, so its log window is
                # empty — the old code treated that emptiness as "evidence"
                # and re-enabled after the timer with nothing proven, which
                # flaps: re-enable a still-broken Kiro, it fails, disable,
                # wait, repeat. Instead, send one real minimal completion and
                # require a valid message back. One passing probe restores
                # (owner: single proof); a failing probe keeps it disabled and
                # resets the clock.
                probe_cfg = rt.get("primary_probe") or {}
                base_url = probe_cfg.get("base_url")
                api_key = probe_cfg.get("api_key")
                probe_model = probe_cfg.get("model") or "claude-sonnet-5"
                if not base_url or not api_key:
                    LOG.warning(
                        "[primary] %s disabled but no probe configured "
                        "(PRIMARY_PROBE_BASE_URL / PRIMARY_PROBE_KEY) — cannot "
                        "prove availability, leaving it off", name,
                    )
                    entry["healthy_since"] = None
                    continue
                entry["attempts"] = int(entry.get("attempts") or 0) + 1
                ok, detail = probe_primary_live(base_url, api_key, probe_model)
                entry["last_probe"] = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "ok": ok, "detail": detail, "attempts": entry["attempts"],
                }
                LOG.info("[primary] probe %s -> %s (%s) [attempt %d]",
                         name, "AVAILABLE" if ok else "still down", detail, entry["attempts"])
                if not ok:
                    # Still unavailable — evidence-backed, so no timer starts.
                    entry["healthy_since"] = None
                    acted += 1  # persist the probe result for the dashboard
                    continue
                try:
                    rt["gateway"].set_status(cid, CHANNEL_ENABLED)
                    rt["gateway"].fix_abilities()
                except Exception as e:
                    LOG.error("[primary] FAILED to restore %s: %s", name, e)
                    continue
                was_down_for = int(now - (entry.get("disabled_at") or now))
                entry["disabled_at"] = None
                entry["healthy_since"] = None
                entry["restored_at"] = now
                entry["last_restore"] = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "down_seconds": was_down_for,
                    "attempts": entry.pop("attempts", 0),
                    "probe": detail,
                }
                acted += 1
                LOG.warning(
                    "[primary] %s (ch %s) RESTORED after %dm down / %d probe(s): %s",
                    name, cid, max(1, was_down_for // 60), entry["last_restore"]["attempts"], detail,
                )
                discord_alert(
                    rt["discord"],
                    f"cctest: primary {name} is AVAILABLE again (live probe passed after "
                    f"{max(1, was_down_for // 60)}m down) — restored as primary.",
                )

        if acted:
            save_state(state)
        return acted
    except Exception:
        LOG.exception("[primary] sweep failed")
        return acted
    finally:
        _fast_lock_release()


def circuit_breaker_tick(circuit_cfg, window_minutes):
    """One severe-degradation sweep. Reuses the normal rotation path with a
    severe-only config: only catastrophic evidence trips it (>=80% hard
    errors, or >=50% abandoned streams), so a merely-marginal merchant waits
    for the regular hourly cycle. Returns the number of rotations attempted.

    Mutation-locked like the cycle's rotation: an operator promote/verify
    landing mid-sweep would race it. The tick waits for the lock (see
    _fast_lock_acquire) and skips only when it stays busy.

    With circuit_cfg["pool_error_streak"] set, a pin that answered that many
    A6 pool errors in a row since its last success is benched first (never
    the pool's last active pin).
    """
    rt = RUNTIME
    if rt is None or not rt.get("enforce"):
        return 0
    if not _fast_lock_acquire():
        LOG.warning("[circuit] mutation lock still busy after the wait — skipping this tick")
        return 0
    try:
        channels = rt["gateway"].list_channels()
        # C2 (checklist 2026-10-26): collect all active pins per model POOL,
        # like run_cycle does. Keying by raw model scored a dual-spelling pin
        # (gpt-6-1-sol + gpt-6.1-sol) twice per tick and could rotate it twice.
        active_pins = {}  # {pool_key: [ch1, ch2, ...]}
        for ch in channels:
            if not (is_pinned_channel(ch.get("name") or "")
                    and int(ch.get("status") or 0) == CHANNEL_ENABLED):
                continue
            for m in [x.strip() for x in (ch.get("models") or "").split(",") if x.strip()]:
                pool_key = sorted(model_pool_names(m))[0]
                if pool_key not in active_pins:
                    active_pins[pool_key] = []
                if ch not in active_pins[pool_key]:
                    active_pins[pool_key].append(ch)
        streak = int(circuit_cfg.get("pool_error_streak") or 0)
        if streak > 0:
            _bench_pool_dead_pins(rt, active_pins, window_minutes, streak)
        _run_sick_rotation(
            rt["gateway"], rt["cctest"], rt["sellers"], active_pins, rt["state"],
            rt["discord"], True, window_minutes, rt.get("seller_registry"),
            latency_cfg=circuit_cfg,
        )
        # Fast refill (2026-10-28): a pool that drops below its target is
        # topped up within one 5-minute tick, not at the next hourly cycle.
        # Pacing per pool is REFILL_RETRY_MINUTES (inside the refill), so a
        # pool with no passing standby does not burn cctest checks every tick.
        try:
            refill_active_pins(rt["gateway"], rt["cctest"], rt["state"], rt["discord"], True)
        except Exception:
            LOG.exception("[refill] fast refill failed")
        save_state(rt["state"])
        return sum(len(pins) for pins in active_pins.values())
    except Exception:
        LOG.exception("[circuit] tick failed")
        return 0
    finally:
        _fast_lock_release()


def _bench_pool_dead_pins(rt, active_pins, window_minutes, streak):
    """Bench (quarantine) every active pin whose A6 pool is answering only
    pool errors (pin_pool_dead), as long as another pin still serves its
    pool, then try to refill the pool from a PASS-verified standby. Benched
    pins leave active_pins so the sick rotation that follows skips them.
    Caller holds the mutation lock."""
    gateway, state, discord = rt["gateway"], rt["state"], rt["discord"]
    for pool_key, pins in active_pins.items():
        for pin_ch in list(pins):
            if len(pins) <= 1:
                break  # never bench the pool's last pin on this signal alone
            name = pin_ch.get("name") or ""
            since = _grace_start(pin_ch, state)
            if pin_pool_dead(gateway, int(pin_ch["id"]), window_minutes, streak,
                             since_ts=since) is not True:
                continue
            try:
                gateway.set_status(int(pin_ch["id"]), CHANNEL_MANUALLY_DISABLED)
                gateway.fix_abilities()
            except Exception as e:
                LOG.error("[circuit] FAILED to bench pool-dead pin %s: %s", name, e)
                continue
            pins.remove(pin_ch)
            ch_state = state.setdefault(name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
            # Not "permanent": the merchant is not fake, its A6 pool is empty
            # or failing. The 2h quarantine re-check releases it to standby.
            ch_state.update({
                "quarantined": True,
                "quarantined_since": datetime.now(timezone.utc).isoformat(),
                "permanent": False,
                "model": pool_key,
            })
            LOG.warning("[circuit] %s (ch %s) answered %d+ A6 pool errors in a row — benched; "
                        "%d pin(s) still serve %s", name, pin_ch.get("id"), streak, len(pins), pool_key)
            discord_alert(discord, f"cctest: {name} answered {streak}+ A6 pool errors in a row "
                                   f"(smart-routing pool empty/failing) — benched; "
                                   f"{', '.join(p.get('name') or '' for p in pins)} still serving {pool_key}")
            try:
                fresh = gateway.list_channels()
                entry = find_seller_entry(rt["sellers"], fresh, name)
                if entry:
                    promote_next_standby(gateway, rt["cctest"], pin_ch, entry[0], entry[1], pool_key,
                                         True, discord, state, fresh, rt.get("seller_registry"))
            except Exception as e:
                LOG.error("[circuit] refill after benching %s failed: %s", name, e)
            save_state(state)


def circuit_breaker_loop(circuit_cfg, window_minutes, interval_minutes,
                         primary_channels=(), restore_minutes=30):
    LOG.info(
        "[circuit] severe-degradation breaker started: every %dm over a %dm window "
        "(error>=%.0f%% or gone>=%.0f%%, min %d)",
        interval_minutes, window_minutes, circuit_cfg["error_ratio_threshold"] * 100,
        circuit_cfg["client_gone_ratio"] * 100, circuit_cfg["min_samples"],
    )
    if primary_channels:
        LOG.info(
            "[primary] failover enabled for primary channel(s) %s: disable on severe "
            "degradation; RESTORE requires a passing live probe (max wait %dm)",
            list(primary_channels), restore_minutes,
        )
    while True:
        time.sleep(interval_minutes * 60)
        try:
            n = circuit_breaker_tick(circuit_cfg, window_minutes)
            if n:
                LOG.debug("[circuit] swept %d active pin(s)", n)
        except Exception:
            LOG.exception("[circuit] loop tick failed")
        if primary_channels:
            try:
                sweep_primary_channels(circuit_cfg, window_minutes, restore_minutes)
            except Exception:
                LOG.exception("[primary] loop tick failed")


def primary_probe_loop(circuit_cfg, window_minutes, restore_minutes, interval_minutes):
    """Fast restore-probe loop (owner decision 2026-10-25: probe every
    minute, not every 5). Only RESTORES a disabled primary — it never
    disables, so it cannot add disable churn. A disabled primary is caught
    by the 5-minute breaker tick (which also probes), and this loop rechecks
    the live probe far more often so a recovered Kiro comes back within
    ~1 minute instead of up to 5.

    Cost: each probe is one minimal completion (~6.5k input tokens, the
    proxy's system prompt), spent ONLY while the primary is disabled. While
    the primary is enabled this loop does no A6/gateway work at all beyond a
    channel-list read."""
    LOG.info("[primary] fast restore probe started: every %dm (disabled primary only)",
             interval_minutes)
    while True:
        time.sleep(interval_minutes * 60)
        rt = RUNTIME
        if rt is None or not rt.get("enforce") or not rt.get("primary_channels"):
            continue
        prim = rt["state"].get("_primary") or {}
        if not any((e or {}).get("disabled_at") for e in prim.values()):
            continue  # nothing disabled — no probe cost
        try:
            sweep_primary_channels(circuit_cfg, window_minutes, restore_minutes,
                                   restore_only=True)
        except Exception:
            LOG.exception("[primary] fast probe tick failed")


def start_circuit_breaker(circuit_cfg, window_minutes, interval_minutes,
                          primary_channels=(), restore_minutes=30):
    threading.Thread(
        target=circuit_breaker_loop,
        args=(circuit_cfg, window_minutes, interval_minutes,
              tuple(primary_channels or ()), restore_minutes),
        daemon=True, name="cctest-circuit-breaker",
    ).start()


def run_cycle(gateway, cctest, sellers, model_prefixes, usage_window_hours,
              threshold_for, permanent_fails, enforce, discord, state,
              seller_model_filter=None, a6m=None, sick_window_minutes=60,
              latency_cfg=None):
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
    # Auto-release (owner rule 2026-10-23): a quarantined pin whose LATEST
    # verdict is a pass got a green check somewhere (manual verify, a prior
    # cycle's re-check) but the release never landed — a restart or a partial
    # failure between the check and the release. The state is the source of
    # truth: if the latest recorded verdict says the merchant is genuine, the
    # quarantine is stale. Release it back to standby (never straight to
    # active — another pin is serving the model by now).
    if enforce:
        for name, ch_state in state.items():
            if not isinstance(ch_state, dict):
                continue
            if not ch_state.get("quarantined"):
                continue
            if not is_pinned_channel(name):
                continue
            last = (ch_state.get("last_verdicts") or {})
            model = ch_state.get("model") or ""
            latest = (last.get(model) or {}).get("verdict")
            # Tolerate malformed state (2026-10-24: a6pin-6-astra-3016 held
            # verdict=[None, None] from an earlier record_verdict bug; the
            # membership test crashed with unhashable-type and killed every
            # cycle). Anything that isn't a plain string is not a pass.
            if not isinstance(latest, str) or latest not in PASS_VERDICTS:
                continue
            # Find the channel; skip if missing (deleted pin).
            ch = next((c for c in channels if (c.get("name") or "") == name), None)
            if ch is None:
                continue
            try:
                # release_quarantine now never enables the channel (owner spec
                # 2026-10-24), so no re-bench is needed — the pin stays a
                # standby until promoted.
                release_quarantine(gateway, ch_state, int(ch["id"]), name, enforce, discord)
                LOG.warning("[release] auto-released %s — latest verdict %s is a pass", name, latest)
                discord_alert(discord, f"cctest: {name} auto-released (latest verdict: {latest})")
            except Exception as e:
                LOG.error("[release] auto-release FAILED for %s: %s", name, e)
    # Active pins per model, for sick-pin rotation after their checks.
    # C2 (checklist 2026-10-26): min-active target per model (default 2).
    # Manually-enabled extras beyond the target create a lottery the owner
    # explicitly retired — extras are disabled back to standby with an alert.
    # When below target, refill_active_pins (end of cycle) tops the pool up.
    # The target is per model pool (min_active_for, MIN_ACTIVE_PINS_BY_MODEL).
    active_pins = {}  # {pool_key: [ch1, ch2, ...]}
    for ch in channels:
        if not (is_pinned_channel(ch.get("name") or "") and int(ch.get("status") or 0) == CHANNEL_ENABLED):
            continue
        for m in [x.strip() for x in (ch.get("models") or "").split(",") if x.strip()]:
            # Model aliases share ONE pool (gpt-6-1-sol == gpt-6.1-sol): two
            # enabled pins on the same pool — whatever spelling each serves —
            # count against the same target. Track per canonical pool representative.
            pool_key = sorted(model_pool_names(m))[0]
            if pool_key not in active_pins:
                active_pins[pool_key] = []
            if ch not in active_pins[pool_key]:
                active_pins[pool_key].append(ch)
    extra_actives = []
    for pool_key, pins in active_pins.items():
        target = min_active_for(pool_key)
        if len(pins) > target:
            # Keep the first `target`, disable the rest.
            for extra in pins[target:]:
                extra_actives.append((pool_key, extra))
    if extra_actives and enforce and _cycle_lock_acquire():
      try:
        for pool_key, extra in extra_actives:
            extra_name = extra.get("name")
            min_active = min_active_for(pool_key)
            keepers = ", ".join(ch.get("name") or "" for ch in active_pins[pool_key][:min_active])
            LOG.warning("[dedup] %s has %d active pins (target %d) — disabling extra %s (keeping %s)",
                        pool_key, len(active_pins[pool_key]), min_active, extra_name, keepers)
            try:
                gateway.set_status(int(extra["id"]), CHANNEL_MANUALLY_DISABLED)
            except Exception as e:
                LOG.error("[dedup] failed to disable extra pin %s: %s", extra_name, e)
                continue
            discord_alert(discord, f"cctest: {pool_key} had {len(active_pins[pool_key])} active pins (target {min_active}) — disabled {extra_name}")
        if extra_actives:
            try:
                gateway.fix_abilities()
            except Exception:
                pass
            # Refresh the channel list so process_channel sees the corrected state.
            try:
                channels = gateway.list_channels()
            except Exception:
                pass
      finally:
        _MUTATION_LOCK.release()
    elif extra_actives and enforce:
        LOG.info("[dedup] mutation lock busy — deferring dedup to the next cycle")
    # MUTATION-LOCKED per-channel processing (audit BLOCKER 2026-10-25).
    # process_channel can quarantine, promote, enable, disable and edit a
    # channel's model list. It used to run unlocked, so an operator promote
    # or a circuit-breaker tick landing mid-loop raced it: the auditor
    # reproduced TWO enabled pins for one model (cycle enabling its standby
    # after the operator had already enabled a different one) and a
    # quarantine+promote that ignored a lock held by another thread. The
    # lock is per-channel rather than per-cycle so a long cycle (dozens of
    # cctest checks, each up to ~90s) does not block the 5-minute breaker or
    # the operator for its whole duration.
    for name, base_url, seller_key in sellers:
        allowed = seller_model_filter.get(name)
        for channel in expand_seller_to_channels(channels, name, base_url, seller_key):
            # _cycle_lock_acquire yields to a waiting fast tick first (it gets
            # the lock between two channels instead of skipping its turn).
            if _cycle_lock_acquire():
                try:
                    process_channel(
                        gateway, cctest, channel, base_url, seller_key, model_prefixes,
                        usage_window_hours, threshold_for, permanent_fails, enforce,
                        discord, state, channels, allowed, seller_registry,
                    )
                finally:
                    _MUTATION_LOCK.release()
            else:
                # An operator action holds the lock; this channel's turn is
                # skipped and the next cycle re-checks it. Failing open
                # (not blocking) keeps the operator responsive — the same
                # trade-off the sick rotation makes.
                LOG.info("[cycle] mutation lock busy — skipping check of %s this cycle",
                         channel.get("name"))
            save_state(state)
    # Sick-pin rotation (owner rule 2026-10-19): a pin with recent failures
    # and zero successes is as unusable as a fake — quarantine + promote,
    # exactly the fake path. Inconclusive cctest verdicts alone never
    # rotate (fail-open), but the gateway's own error log is hard evidence.
    # Mutation-locked: the sick rotation quarantines + promotes channels —
    # an HTTP promote/verify landing mid-rotation would race it (two pins
    # enabled, or the rotation re-enabling a pin the operator just rotated
    # off). A busy cycle skips the rotation this round; the next cycle's
    # sick check catches it.
    if enforce:
        if not _cycle_lock_acquire():
            LOG.info("[sick] another rotation is in flight — skipping sick checks this cycle")
        else:
            try:
                _run_sick_rotation(gateway, cctest, sellers, active_pins, state, discord, enforce, sick_window_minutes, seller_registry, latency_cfg=latency_cfg)
            finally:
                _MUTATION_LOCK.release()
        # Refill (2026-10-27): promote_next_standby only ran after a failure,
        # so nothing ever topped a pool up to its target — every model sat on
        # one active pin and lost all A6 coverage whenever that merchant
        # failed (fable-5, 14:01). Runs after the checks and the sick rotation
        # so it sees the cycle's final state.
        if _cycle_lock_acquire():
            try:
                refill_active_pins(gateway, cctest, state, discord, enforce)
            except Exception:
                LOG.exception("[refill] refill failed")
            finally:
                _MUTATION_LOCK.release()
        else:
            LOG.info("[refill] mutation lock busy — refill deferred to the next cycle")
    # Freshness marker for the status server: an old last_cycle_at (vs
    # cycle_minutes) visibly signals a broken cycle on the admin page. Written
    # HERE, at the true end of the hourly cycle, and NOT in
    # _run_sick_rotation — the 5-minute circuit breaker calls that function
    # too, which used to make the stamp fresh whenever the breaker was alive
    # and hide a dead cycle (audit M2, 2026-10-25). Not written on the
    # exception path (main() catches before this point), so a crashed cycle
    # keeps the previous stamp — exactly the staleness we want to expose.
    state["_meta"] = {"last_cycle_at": datetime.now(timezone.utc).isoformat()}
    save_state(state)


def _pin_enabled_at(channel):
    """When the gateway last changed this channel's status, as int epoch
    seconds (other_info.status_time, stamped by model.UpdateChannelStatus on
    every enable/disable, whoever made it). For an enabled pin that is the
    moment it was enabled. None when absent or unparseable."""
    raw = channel.get("other_info")
    if not raw:
        return None
    try:
        info = json.loads(raw) if isinstance(raw, str) else raw
        value = info.get("status_time") if isinstance(info, dict) else None
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _grace_start(pin_ch, state):
    """Start of an active pin's post-promotion grace: the later of the
    monitor's own promotion (promoted_at) and the gateway's last status change.
    A pin enabled by hand or through the API has no promoted_at (ch9,
    2026-10-27 17:29: enabled ~17:05, then benched on 20 errors from its 12:54
    stint, still inside the 6h sick window). None when neither is known."""
    starts = [t for t in ((state.get(pin_ch.get("name")) or {}).get("promoted_at"),
                          _pin_enabled_at(pin_ch)) if t]
    return max(starts) if starts else None


def _run_sick_rotation(gateway, cctest, sellers, active_pins, state, discord, enforce, sick_window_minutes, seller_registry=None, latency_cfg=None):
    """Rotate sick active pins. active_pins is now {model: [ch1, ch2, ...]} (C2,
    checklist 2026-10-26), supporting multiple active pins per model."""
    if enforce:
        # Flatten the multi-active structure: [(model, pin), ...].
        pin_list = [(model, pin) for model, pins in active_pins.items() for pin in pins]
        for model, pin in pin_list:
            pin_name = pin.get("name")
            # Post-promotion grace (owner refinement 2026-10-27): a newly promoted
            # pin is scored only on traffic since its promotion, not on inherited
            # errors from the previous active pin. The grace lasts one sick
            # window and also starts at a manual enable (_grace_start).
            grace_since = None
            started = _grace_start(pin, state)
            if started and time.time() - started < sick_window_minutes * 60:
                grace_since = started
                LOG.info("[sick] %s in post-promotion grace (enabled %.1fm ago) — scoring since then",
                         pin_name, (time.time() - started) / 60)
            sick = pin_is_sick(gateway, int(pin["id"]), sick_window_minutes, latency_cfg=latency_cfg, since_ts=grace_since)
            if sick is not True:
                continue
            # Re-list live: process_channel (fake-verdict path) may have
            # already rotated this model this cycle, and the snapshot this
            # loop captured is pre-rotation — promoting against it re-enables
            # the very pin we rotated away from (observed live 2026-10-19).
            try:
                live = gateway.list_channels()
            except Exception as e:
                LOG.warning("[sick] live channel list failed (%s); skipping rotation for %s", e, pin_name)
                continue
            live_actives = [
                ch for ch in live
                if is_pinned_channel(ch.get("name") or "")
                and int(ch.get("status") or 0) == CHANNEL_ENABLED
                and model_pool_names(model) & {x.strip() for x in (ch.get("models") or "").split(",") if x.strip()}
            ]
            live_names = {ch.get("name") for ch in live_actives}
            if pin_name not in live_names:
                # This pin was rotated earlier this cycle.
                LOG.info("[sick] %s already rotated this cycle — %s active now",
                         pin_name, ", ".join(live_names) or "(none)")
                continue
            # Re-fetch the live version of this pin (status may have changed).
            live_pin = next((ch for ch in live if ch.get("name") == pin_name), pin)
            # Label the rotation honestly: the all-failures rule and the
            # degraded-merchant rule (latency/errors with successes) are
            # different diagnoses and the owner's alert must not claim
            # "no successes" for a pin that was serving fine but bleeding.
            degraded = bool(latency_cfg and latency_cfg.get("enabled"))
            reason = ("degraded (slow / abandoned streams / hard errors — see the "
                      "[latency] log line for this channel)" if degraded
                      else "failing with no successes")
            LOG.warning("[sick] active pin %s (ch %s) %s — rotating", pin_name, live_pin.get("id"), reason)
            ch_state = state.setdefault(pin_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
            ch_state.update({
                "quarantined": True,
                "quarantined_since": datetime.now(timezone.utc).isoformat(),
                "permanent": True,
                "model": model,
            })
            try:
                gateway.set_status(int(live_pin["id"]), CHANNEL_MANUALLY_DISABLED)
                gateway.fix_abilities()
                discord_alert(discord, f"cctest: active pin {pin_name} for {model} is {reason} — rotating to next standby")
                fresh = gateway.list_channels()  # post-disable, pre-promotion
                entry = find_seller_entry(sellers, fresh, pin_name)
                if entry:
                    promote_next_standby(
                        gateway, cctest, live_pin, entry[0], entry[1], model,
                        enforce, discord, state, fresh, seller_registry,
                    )
                else:
                    LOG.error("[sick] %s not covered by any SELLER_CHANNELS entry; quarantined without promotion", pin_name)
            except Exception as e:
                LOG.error("[sick] rotation FAILED for %s (stays active): %s", pin_name, e)
            save_state(state)
    # NOTE: the _meta freshness marker is written by run_cycle, NOT here.
    # _run_sick_rotation is also called by the 5-minute circuit breaker, and
    # stamping it here made last_cycle_at look fresh whenever the breaker was
    # alive — the admin page's "cycle is stale" signal, the only external sign
    # that the hourly cctest cycle has died, went permanently green (audit
    # M2, 2026-10-25).
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


def _standby_score(gateway, channel_id, window_minutes, state, channel_name):
    """Compute standby ranking metrics: our success rate, median FRT, and
    sample size. Returns (success_rate, median_frt_ms, samples) or None on
    insufficient data. Used by C1 (checklist 2026-10-26) to rank standby pins
    by OUR OWN traffic, with A6 marketplace health only as a tiebreak.

    Post-promotion grace (owner refinement 2026-10-27): score only traffic
    since the pin was last promoted. A newly promoted pin inherits no errors
    from the previous active pin — scoring starts fresh."""
    ch_state = state.get(channel_name) or {}
    since_ts = ch_state.get("promoted_at")
    try:
        errors = gateway.count_logs(5, channel_id, window_minutes, since_ts=since_ts)
        successes = gateway.count_logs(2, channel_id, window_minutes, since_ts=since_ts)
    except Exception:
        return None
    if errors is None or successes is None:
        return None
    total = errors + successes
    if total < 5:
        # Thin data: not enough to rank meaningfully.
        return None
    success_rate = successes / total if total > 0 else 0.0
    # Median FRT from streaming consume logs.
    try:
        rows = gateway.recent_consume_logs(channel_id, window_minutes)
    except Exception:
        rows = None
    if rows is None:
        median_frt = 0
    else:
        stream_rows = [r for r in rows if isinstance(_parse_other(r).get("stream_status"), dict)]
        frts = []
        for row in stream_rows:
            other = _parse_other(row)
            try:
                frt = int(other.get("frt"))
            except (TypeError, ValueError):
                frt = None
            if frt is not None and frt >= 0:
                frts.append(frt)
        if frts:
            sorted_frts = sorted(frts)
            median_frt = sorted_frts[len(sorted_frts) // 2]
        else:
            median_frt = 0
    return (success_rate, median_frt, total)


def _rank_standbys(gateway, model, candidates, state):
    """Order standby candidates for promotion, best first. Returns (ranked
    candidates, A6 health by merchant id). On a ranking failure the input
    order is kept and the health map is empty (fail-open, never worse than
    first-fresh)."""
    # Prefer A6-healthy candidates (2026-10-23 sonnet-5 outage: the
    # first fresh standby was merchant 1204, delisted from the A6
    # marketplace and dead — 503s for the whole model). A marketplace
    # check is one cheap public GET; a delisted/unhealthy merchant
    # sorts last and an unavailable one is skipped when any healthy
    # candidate exists. Health data unavailable (A6 fetch failed) →
    # fall back to first-fresh (fail-open, never worse than before).
    # C1 (checklist 2026-10-26): rank by OUR success rate + FRT first, then
    # A6 marketplace health as a tiebreak. Our metrics are primary evidence
    # (real customer traffic); A6 health is still consulted (delisted pins
    # sort last), but no longer the only ranking factor.
    our_scores = {}  # {channel_name: (success_rate, median_frt, samples) | None}
    window_h = int(os.environ.get("USAGE_WINDOW_HOURS", "7"))
    for ch in candidates:
        ch_id = int(ch.get("id") or 0)
        ch_name = ch.get("name") or ""
        our_scores[ch_name] = _standby_score(gateway, ch_id, window_h * 60, state, ch_name)
    try:
        market = A6Market()
        candidates_health = market.health_for(
            model,
            {c.get("name", "").rsplit("-", 1)[-1] for c in candidates},
        )

        def _rank(ch):
            ch_name = ch.get("name") or ""
            h = candidates_health.get(ch_name.rsplit("-", 1)[-1]) or {}
            # Gate: a delisted merchant ALWAYS sorts last, whatever our
            # history says (2026-10-27 6.1-sol flap: delisted #85 had
            # traffic data, so it outranked six listed never-used
            # standbys that had none).
            listed = 0 if h.get("unlisted") else 1
            # Primary: our own metrics (success rate desc, FRT asc).
            our = our_scores.get(ch_name)
            if our is not None:
                success_rate, median_frt, samples = our
                primary = (success_rate, -median_frt, samples)
            else:
                # No data: sort after those with data, but before delisted.
                primary = (-1.0, 0, 0)
            # Tiebreak: A6 marketplace health.
            if h.get("unlisted"):
                tiebreak = (0, 0, 0)
            else:
                tiebreak = (
                    1 if h.get("healthy") else 0,
                    h.get("success_rate") or 0,
                    -(h.get("price_micros") or 10**9),
                )
            return (listed,) + primary + tiebreak
        return sorted(candidates, key=_rank, reverse=True), candidates_health
    except Exception as e:
        LOG.warning("[pin] standby ranking (our metrics + A6 health) failed for %s (%s); "
                    "first-fresh fallback", model, e)
        return list(candidates), {}


def _gate_cfg():
    """Entry-gate thresholds (owner rules 2026-10-28): a standby only goes
    active when its A6 price leaves at least PIN_MIN_MARGIN (1.5x) on BOTH
    input and output, and a live probe through its own channel answers
    within PIN_MAX_PROBE_MS (8s). PIN_ENTRY_PROBE=false skips the probe."""
    try:
        margin = float(os.environ.get("PIN_MIN_MARGIN", "1.5"))
    except ValueError:
        margin = 1.5
    return {
        "min_margin": margin if margin > 0 else 1.5,
        "max_probe_ms": _watchdog_env_int("PIN_MAX_PROBE_MS", 8000),
        "probe": os.environ.get("PIN_ENTRY_PROBE", "true").lower() in ("1", "true", "yes"),
        "retry_seconds": _watchdog_env_int("REFILL_RETRY_MINUTES", 30, lo=0) * 60,
    }


def _sell_prices(gateway):
    """Our sell prices, or {} when unavailable (the margin check then
    fails open — a pricing-API hiccup must not stop a pool from refilling)."""
    fetch = getattr(gateway, "sell_prices", None)
    if fetch is None:
        return {}
    try:
        return fetch() or {}
    except Exception as e:
        LOG.warning("[gate] sell-price fetch failed (%s); margin check skipped", e)
        return {}


def _margin_check(pool_key, merchant_health, sell, min_margin):
    """(ok, reason). Our sell price over the merchant's A6 listing price, on
    input and output separately. Missing data on either side passes (logged
    by the caller); the price gate only blocks on known-bad margins."""
    ours = next((sell[s] for s in sorted(model_pool_names(pool_key)) if s in sell), None)
    a6_in = (merchant_health or {}).get("price_micros")
    a6_out = (merchant_health or {}).get("output_price_micros")
    if not ours or not a6_in:
        return True, "margin unknown"
    in_x = ours[0] / (a6_in / 1e6)
    out_x = ours[1] / (a6_out / 1e6) if a6_out else None
    worst = min(x for x in (in_x, out_x) if x is not None)
    detail = f"margin in {in_x:.2f}x" + (f" / out {out_x:.2f}x" if out_x is not None else "")
    if worst < min_margin:
        return False, f"{detail} < {min_margin:.2f}x floor"
    return True, detail


def _entry_gate(gateway, ch, pool_key, merchant_health, sell, cfg, state):
    """Cheap pre-checks before a standby may spend a cctest check or go
    active: price margin, then one live probe through the channel itself
    (catches A6 "no active candidate" 503s, 403 model_not_allowed keys and
    slow merchants — none of which cctest reports as a fail). Records the
    probe in state["_standby_health"]. Returns (ok, reason)."""
    name = ch.get("name") or ""
    ok, reason = _margin_check(pool_key, merchant_health, sell, cfg["min_margin"])
    if not ok:
        return False, reason
    if not cfg["probe"] or not hasattr(gateway, "test_channel"):
        return True, reason
    alive, ms, detail = gateway.test_channel(int(ch["id"]), pool_key)
    state.setdefault("_standby_health", {})[name] = {
        "ok": bool(alive), "ms": ms, "detail": detail, "at": time.time(),
    }
    if not alive:
        return False, f"live probe failed ({detail})"
    if ms is not None and ms > cfg["max_probe_ms"]:
        return False, f"live probe slow ({ms}ms > {cfg['max_probe_ms']}ms)"
    return True, f"{reason}, probe {ms}ms"


def _alert_once(state, discord, key, active, text):
    """Deduplicated pool alert: fires when `active` turns True, re-arms when
    it turns False again."""
    alerts = state.setdefault("_standby_alerts", {})
    if active and not alerts.get(key):
        discord_alert(discord, text)
        LOG.warning("[pool] %s", text)
    alerts[key] = bool(active)


def refill_active_pins(gateway, cctest, state, discord, enforce=True):
    """Top every pin pool up to its target (min_active_for) with standbys that
    PASS a direct check against their OWN A6 key (2026-10-27).

    promote_next_standby only ran after a failure, so nothing ever added a
    second pin: every model sat on one active merchant and lost all A6
    coverage the moment it failed (fable-5, 14:01). Only pools that still have
    an active pin are refilled — a pool with none is a failover, owned by
    promote_next_standby (which may fail open). A refill never enables an
    inconclusive, quarantined, bad-marked (in cooldown) or delisted standby,
    and spends at most REFILL_MAX_CHECKS (default 2) cctest checks per pool
    per call. Needs the A6 management API for the keys (no-op without it).
    Caller holds the mutation lock. Returns the names of the pins enabled."""
    a6m = RUNTIME.get("a6m") if RUNTIME else None
    if a6m is None or not enforce:
        return []
    try:
        channels = gateway.list_channels()
    except Exception as e:
        LOG.warning("[refill] channel list failed (%s); refill skipped", e)
        return []
    max_checks = _watchdog_env_int("REFILL_MAX_CHECKS", 2, lo=0)
    cooldown = _watchdog_env_int("STANDBY_COOLDOWN_HOURS", 3) * 3600
    pools = {}  # {pool_key: {"active": [ch, ...], "standby": [ch, ...]}}
    for ch in channels:
        status = int(ch.get("status") or 0)
        if not is_pinned_channel(ch.get("name") or "") or status not in (CHANNEL_ENABLED, CHANNEL_MANUALLY_DISABLED):
            continue
        keys = {sorted(model_pool_names(x.strip()))[0]
                for x in (ch.get("models") or "").split(",") if x.strip()}
        for key in keys:
            slot = pools.setdefault(key, {"active": [], "standby": []})
            slot["active" if status == CHANNEL_ENABLED else "standby"].append(ch)
    added = []
    now = time.time()
    bad = state.setdefault("bad_standbys", {})
    gate = _gate_cfg()
    sell = None  # fetched lazily, once, only when some pool needs a refill
    for pool_key, slot in sorted(pools.items()):
        target = min_active_for(pool_key)
        active = len(slot["active"])
        if not slot["active"] or active >= target:
            state.setdefault("_refill", {}).pop(pool_key, None)
            continue
        marks = {}
        for spelling in model_pool_names(pool_key):
            if isinstance(bad.get(spelling), dict):
                marks.update(bad[spelling])
        candidates = [
            ch for ch in slot["standby"]
            if not (state.get(ch["name"]) or {}).get("quarantined")
            and not (ch["name"] in marks and now - marks[ch["name"]] < cooldown)
        ]
        if not candidates:
            LOG.info("[refill] %s has %d/%d active pin(s) and no eligible standby", pool_key, active, target)
            continue
        # Retry pacing (2026-10-28): the 5-minute breaker tick also calls the
        # refill, so a pool that just came up short waits REFILL_RETRY_MINUTES
        # before spending cctest checks on it again.
        last_try = (state.setdefault("_refill", {}).get(pool_key) or {}).get("at") or 0
        if gate["retry_seconds"] and now - last_try < gate["retry_seconds"]:
            continue
        if sell is None:
            sell = _sell_prices(gateway)
        ranked, health = _rank_standbys(gateway, pool_key, candidates, state)
        checks = 0
        gated = []
        for ch in ranked:
            if active >= target or checks >= max_checks:
                break
            name = ch["name"]
            merchant_health = health.get(name.rsplit("-", 1)[-1]) or {}
            if merchant_health.get("unlisted"):
                # Delisted merchants 503. The pool is still served, so there
                # is no reason to fail open onto one.
                continue
            # Entry gate (owner rules 2026-10-28): margin floor + live probe
            # BEFORE the cctest check, so dead, slow or loss-making standbys
            # never spend the check budget (dead ones only ever return an
            # inconclusive verdict, which used to burn both refill checks).
            passed, reason = _entry_gate(gateway, ch, pool_key, merchant_health, sell, gate, state)
            if not passed:
                gated.append(f"{name}: {reason}")
                LOG.info("[refill] %s blocked by entry gate — %s", name, reason)
                continue
            key = _pin_reveal_key(a6m, name, pool_key)
            if not key:
                continue
            # A6 registers the upstream spelling (gpt-6.1-sol), not our SKU.
            check_model = parse_model_mapping(ch.get("model_mapping")).get(pool_key, pool_key)
            verdict = do_check(cctest, ch.get("base_url") or "https://api.a6api.com", key, check_model)
            checks += 1
            st = state.setdefault(name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False})
            record_verdict(st, pool_key, verdict)
            LOG.info("[refill] verify %s (%s) direct -> %s", name, check_model, verdict)
            if verdict in BAD_VERDICTS:
                if isinstance(bad.get(pool_key), list):
                    bad[pool_key] = {n: now for n in bad[pool_key]}
                bad.setdefault(pool_key, {})[name] = time.time()
                continue
            if verdict not in PASS_VERDICTS:
                continue  # inconclusive: never enabled while the pool is served
            try:
                gateway.set_status(int(ch["id"]), CHANNEL_ENABLED)
                gateway.fix_abilities()
            except Exception as e:
                LOG.error("[refill] enabling %s FAILED: %s", name, e)
                continue
            st["promoted_at"] = time.time()
            for spelling in model_pool_names(pool_key):
                if isinstance(bad.get(spelling), dict):
                    bad[spelling].pop(name, None)
            active += 1
            added.append(name)
            LOG.warning("[refill] enabled verified standby %s for %s (%d/%d active pins)",
                        name, pool_key, active, target)
            discord_alert(discord, f"cctest: refill — enabled verified standby {name} for {pool_key} "
                                   f"({active}/{target} active pins)")
        if active < target:
            LOG.info("[refill] %s still at %d/%d active pin(s) after %d check(s)", pool_key, active, target, checks)
            state.setdefault("_refill", {})[pool_key] = {
                "at": now, "active": active, "target": target, "gated": gated[:10],
            }
        else:
            state.setdefault("_refill", {}).pop(pool_key, None)
    if added:
        save_state(state)
    return added


def sweep_standby_health(gateway, state, discord):
    """Standby health sweep (owner ask 2026-10-28): one live probe per
    standby through its own channel (Gateway.test_channel — works on
    disabled channels, never flips status), so a dead spare is known BEFORE
    it is needed. Then alert, once per condition, when a pool is below its
    active target or has no standby that is both alive and inside the
    margin floor. Read-only on channel status, so it needs no mutation lock
    (it runs on the sync loop, every STANDBY_SWEEP_HOURS)."""
    gate = _gate_cfg()
    try:
        channels = gateway.list_channels()
    except Exception as e:
        LOG.warning("[standby] channel list failed (%s); sweep skipped", e)
        return {}
    pools = {}
    for ch in channels:
        status = int(ch.get("status") or 0)
        if not is_pinned_channel(ch.get("name") or "") or status not in (CHANNEL_ENABLED, CHANNEL_MANUALLY_DISABLED):
            continue
        keys = {sorted(model_pool_names(x.strip()))[0]
                for x in (ch.get("models") or "").split(",") if x.strip()}
        for key in keys:
            slot = pools.setdefault(key, {"active": [], "standby": []})
            slot["active" if status == CHANNEL_ENABLED else "standby"].append(ch)
    sell = _sell_prices(gateway)
    market = A6Market()
    summary = {}
    for pool_key, slot in sorted(pools.items()):
        health = market.health_for(pool_key, {(c.get("name") or "").rsplit("-", 1)[-1] for c in slot["standby"]})
        usable = []
        for ch in slot["standby"]:
            name = ch.get("name") or ""
            if (state.get(name) or {}).get("permanent"):
                continue  # confirmed fake / benched for good — not a spare
            mh = health.get(name.rsplit("-", 1)[-1]) or {}
            if mh.get("unlisted"):
                state.setdefault("_standby_health", {})[name] = {
                    "ok": False, "ms": None, "detail": "delisted on A6", "at": time.time()}
                continue
            ok, reason = _entry_gate(gateway, ch, pool_key, mh, sell, gate, state)
            LOG.info("[standby] %s (%s): %s", name, pool_key, "usable — " + reason if ok else "NOT usable — " + reason)
            if ok:
                usable.append(name)
        target = min_active_for(pool_key)
        summary[pool_key] = {"active": len(slot["active"]), "target": target, "usable_standbys": usable}
        _alert_once(state, discord, f"short:{pool_key}", len(slot["active"]) < target,
                    f"cctest: {pool_key} has {len(slot['active'])}/{target} active A6 pins")
        _alert_once(state, discord, f"nospare:{pool_key}", not usable,
                    f"cctest: {pool_key} has NO usable standby (alive, under "
                    f"{gate['max_probe_ms'] // 1000}s, >= {gate['min_margin']:.1f}x margin) — "
                    f"add a merchant key on A6")
    state["_standby_sweep"] = {"at": datetime.now(timezone.utc).isoformat(),
                               "ts": time.time(), "pools": summary}
    save_state(state)
    return summary


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

    Idempotency: promotion stops once the model has MIN_ACTIVE_PINS (default 2)
    enabled pins (C2, checklist 2026-10-26). Standby discovery uses
    MODEL-MEMBERSHIP, not name prefixes — a6pin-sonnet-5-* and
    a6pin-sonnet-5-5-* are different models."""
    if not model:
        LOG.warning("[pin] quarantined pin has no model; no standby search")
        return
    pool = model_pool_names(model)
    min_active = min_active_for(model)
    # C2: stop promoting once the model has min_active pins (idempotence).
    actives_for_model = [
        ch for ch in (channels_snapshot or [])
        if is_pinned_channel(ch.get("name") or "")
        and int(ch.get("status") or 0) == CHANNEL_ENABLED
        and pool & {mm.strip() for mm in (ch.get("models") or "").split(",") if mm.strip()}
    ]
    if len(actives_for_model) >= min_active:
        LOG.info("[pin] %s already has %d active pin(s) (target %d) — no promotion",
                 model, len(actives_for_model), min_active)
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
        candidates, candidates_health = _rank_standbys(gateway, model, candidates, state)
        # Entry gate (owner rules 2026-10-28): the first ranked standby that
        # is listed, inside the margin floor and answers a live probe in
        # time. While another pin still serves the model, a failing gate
        # means no promotion now (the next refill retries). With NOTHING
        # serving, fail open onto the top-ranked candidate as before — a
        # dark model is worse than an unproven merchant.
        gate = _gate_cfg()
        sell = _sell_prices(gateway)
        gated_pick = None
        for cand in candidates:
            cand_health = candidates_health.get((cand.get("name") or "").rsplit("-", 1)[-1]) or {}
            if cand_health.get("unlisted"):
                continue
            passed, reason = _entry_gate(gateway, cand, model, cand_health, sell, gate, state)
            if passed:
                gated_pick = cand
                break
            LOG.info("[pin] %s blocked by entry gate for %s — %s", cand.get("name"), model, reason)
        if gated_pick is None and actives_for_model:
            LOG.warning("[pin] no standby for %s passes the entry gate while %d pin(s) still "
                        "serve it — no promotion, refill retries", model, len(actives_for_model))
            return
        if gated_pick is None:
            gated_pick = candidates[0]
            LOG.warning("[pin] no standby for %s passes the entry gate and nothing serves the "
                        "model — promoting %s anyway (fail-open)", model, gated_pick.get("name"))
        standby = gated_pick
    standby_name = standby["name"]
    if not enforce:
        LOG.warning("[pin] OBSERVE-ONLY: would promote standby %s for %s", standby_name, model)
        return

    # VERIFY FIRST (2026-10-23 owner rule): check the standby's own A6 key
    # directly BEFORE enabling it — no unverified merchant ever serves
    # traffic. The pin's own key comes from the A6 management API (cached);
    # a pin whose key can't be revealed falls back to the old enable-first
    # path (fail-open, better than leaving the model dark).
    pre_verdict = None
    pre_checked = False
    # PASS-only while the model is still served (2026-10-27). The fail-open
    # enable-then-verify fallback below exists for the 2026-10-24 deadlock:
    # a model with NO serving pin. When another pin still serves the model,
    # enabling an unverified merchant only adds risk (the gateway-routed
    # verify after the enable lands on whichever pin the router picks, so it
    # does not even test the new one) — refuse, and let the next cycle's
    # refill try the next standby.
    still_served = bool(actives_for_model)
    pin_key = _pin_reveal_key(RUNTIME.get("a6m") if RUNTIME else None, standby_name, model)
    if not pin_key and still_served:
        LOG.warning("[pin] %s has no revealable A6 key — not enabled while %s is still served "
                    "by %d pin(s)", standby_name, model, len(actives_for_model))
        return
    if pin_key:
        pin_base = standby.get("base_url") or "https://api.a6api.com"
        # A6 registers the UPSTREAM spelling (gpt-6.1-sol); asking for our SKU
        # is a 403 model_not_allowed, i.e. an inconclusive check (the same
        # mapping the quarantine re-check uses, audit M5).
        check_model = parse_model_mapping(standby.get("model_mapping")).get(model, model)
        pre_verdict = do_check(cctest, pin_base, pin_key, check_model)
        LOG.info("[pin] pre-promotion verify %s (%s) direct -> %s", standby_name, check_model, pre_verdict)
        st_state = state.setdefault(
            standby_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
        )
        record_verdict(st_state, model, pre_verdict)
        if pre_verdict in BAD_VERDICTS:
            # Confirmed bad: never enable.
            LOG.warning("[pin] %s FAILED pre-promotion verify for %s — NOT enabled", standby_name, model)
            bad_marks[standby_name] = time.time()
            state["bad_standbys"][model] = bad_marks
            discord_alert(discord, f"cctest: standby {standby_name} for {model} failed pre-promotion check — NOT enabled")
            return
        if pre_verdict in PASS_VERDICTS:
            pre_checked = True
        elif still_served:
            LOG.warning("[pin] %s pre-promotion verify inconclusive for %s — not enabled while "
                        "the model is still served", standby_name, model)
            return
        else:
            # INCONCLUSIVE (cctest unreachable, or the key lacks the model
            # permission — HTTP 403 model_not_allowed). Do NOT refuse: a
            # direct-check limitation is not evidence of fakeness, and
            # refusing here deadlocked claude-sonnet-5-5 into zero serving
            # paths on 2026-10-24 (every standby's direct key returned None,
            # so no pin was ever enabled and nothing re-tried). Fall through
            # to the gateway-routed enable-then-verify path below: the pin is
            # enabled, then verified through the real customer route, and
            # demoted immediately on a bad verdict. "No unverified merchant
            # serves traffic" still holds — verification just moves after
            # the enable, exactly as it did before direct checks existed.
            LOG.warning("[pin] %s pre-promotion verify inconclusive for %s — "
                        "falling back to gateway-routed verify after enable", standby_name, model)

    # Enable after verification (or immediately when direct check wasn't
    # possible — fail-open, the old behavior for un-revealable pins).
    try:
        gateway.set_status(int(standby["id"]), CHANNEL_ENABLED)
        gateway.fix_abilities()
    except Exception as e:
        LOG.error("[pin] standby promotion FAILED for %s: %s", standby_name, e)
        return
    # Record promotion timestamp (owner refinement 2026-10-27): newly promoted
    # pins are scored only on traffic SINCE the promotion, not on inherited
    # errors from the previous active pin (post-promotion grace).
    st_state = state.setdefault(
        standby_name, {"rotation": [], "idx": 0, "fails": 0, "quarantined": False}
    )
    st_state["promoted_at"] = time.time()
    LOG.warning("[pin] promoted %s for %s — %s", standby_name, model,
                "pre-verified" if pre_checked else "verifying now")
    if pre_checked:
        discord_alert(discord, f"cctest: promoted pre-verified standby pin {standby_name} for {model}")
    else:
        discord_alert(discord, f"cctest: promoted standby pin {standby_name} for {model}; verifying authenticity now")

    # The post-enable check confirms routing actually lands on this pin
    # (gateway-routed). Skipped when we already direct-verified — redundant.
    if pre_checked:
        LOG.warning("[pin] %s PASSED pre-promotion verification for %s — active pin", standby_name, model)
        bad_marks.pop(standby_name, None)
        state["bad_standbys"][model] = bad_marks
        return
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
        if verdict == "attr_upgraded":
            # Serving a higher-tier model than asked — accepted by policy,
            # but not "genuine".
            discord_alert(discord, f"cctest: {standby_name} verified acceptable for {model} (serving a higher-tier model)")
        else:
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
            discord_alert(
                discord,
                f"cctest: CRITICAL — confirmed-fake {standby_name} for {model} "
                f"could not be demoted ({e}) — it stays live until the next cycle retries. "
                f"Manual disable recommended.",
            )
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
        if verdict == "attr_upgraded":
            # One alert per (channel, model) upgrade state — a merchant that
            # persistently serves a higher model would otherwise ping every
            # cycle. Re-arms if the verdict leaves attr_upgraded.
            upgrades = ch_state.setdefault("upgrade_alerted", {})
            if not upgrades.get(model):
                upgrades[model] = True
                discord_alert(
                    discord,
                    f"cctest: {name} serving an upgrade for {model} "
                    f"(detected a higher-tier model) — accepted, not quarantined",
                )
        else:
            # Any non-upgrade verdict re-arms the alert for that model.
            ch_state.setdefault("upgrade_alerted", {}).pop(model, None)


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
        # Quarantined pins are re-checked on a timer (owner rule 2026-10-23):
        # a merchant caught fake may recover within hours (they rotate
        # upstreams). RECHECK_INTERVAL: every 2h for normal quarantine;
        # "permanent" (deterministic fake) gets 8h. A passing direct check
        # against the pin's OWN key releases it back to standby (never
        # straight to active — another pin is serving by now).
        candidate = ch_state.get("model") or (eligible[0] if eligible else None)
        if candidate is None:
            LOG.warning("[%s] quarantined but no eligible model to re-test", name)
            return
        # Owner rule 2026-10-24: permanent (confirmed-fake) pins re-check
        # every 3h, same cadence class as normal quarantine (2h). Both are
        # env-tunable so the cadence can change without a code deploy.
        def _recheck_h(var, default):
            try:
                return max(1, int(os.environ.get(var, str(default))))
            except (TypeError, ValueError):
                return default
        recheck_hours = (
            _recheck_h("QUARANTINE_RECHECK_PERMANENT_HOURS", 3)
            if ch_state.get("permanent")
            else _recheck_h("QUARANTINE_RECHECK_HOURS", 2)
        )
        recheck_seconds = recheck_hours * 3600
        now = time.time()
        last_recheck = ch_state.get("last_quarantine_check", 0)

        # Check whether the model still has an active pin — if not, the
        # priority is restoring service (promote a standby), not re-checking
        # the quarantined one.
        try:
            live = gateway.list_channels()
        except Exception:
            live = channels_snapshot
        pool = model_pool_names(candidate)
        has_active = any(
            is_pinned_channel(c.get("name") or "")
            and int(c.get("status") or 0) == CHANNEL_ENABLED
            and pool & {x.strip() for x in (c.get("models") or "").split(",") if x.strip()}
            for c in (live or [])
        )
        if not has_active:
            # No active pin for this model — try to promote a standby NOW.
            # The quarantined pin itself is excluded from its own standby
            # set (name != failed_name, no preferred_name), so for a
            # SINGLE-pin model this promote is a no-op and the pin must
            # still get its scheduled re-check below — otherwise a recovered
            # merchant is never re-tested and the model stays dead until a
            # manual promote. Only return early when a standby actually
            # exists to promote (the re-check then waits for its timer).
            standby_exists = any(
                is_pinned_channel(c.get("name") or "")
                and int(c.get("status") or 0) == CHANNEL_MANUALLY_DISABLED
                and (c.get("name") or "") != name
                and pool & {x.strip() for x in (c.get("models") or "").split(",") if x.strip()}
                for c in (live or [])
            )
            if standby_exists:
                promote_next_standby(
                    gateway, cctest, channel, base_url, seller_key,
                    candidate, enforce, discord, state, live,
                    seller_registry,
                )
                save_state(state)
                return
            # Sole pin and no standby: fall through to the re-check timer.

        if now - last_recheck < recheck_seconds:
            return
        if not is_pinned_channel(name):
            # Non-pin quarantined channels keep the old gateway-routed re-test.
            verdict = do_check(cctest, base_url, seller_key, candidate)
            LOG.info("[%s] quarantine re-test %s -> %s", name, candidate, verdict)
            record_verdict(ch_state, candidate, verdict)
            ch_state["last_quarantine_check"] = now
            if verdict in PASS_VERDICTS:
                # Non-pin legacy channel recovered. release_quarantine now
                # only clears quarantine state (never enables, owner spec
                # 2026-10-24); the owner re-enables legacy channels manually.
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
        # Pinned: direct-check the merchant's OWN key — the only way to know
        # if THIS merchant recovered. A gateway-routed check would test
        # whichever pin is active, not this one.
        pin_key = _pin_reveal_key(RUNTIME.get("a6m") if RUNTIME else None, name, candidate)
        if pin_key is None:
            LOG.info("[%s] quarantine re-check skipped — no A6 key for merchant", name)
            return
        pin_base = channel.get("base_url") or "https://api.a6api.com"
        # A6 registers the UPSTREAM spelling (e.g. gpt-6.1-sol), not our SKU
        # (gpt-6-1-sol); asking for the SKU gets 403 model_not_allowed, which
        # returns None and means the pin is NEVER released from quarantine —
        # re-checked and refused forever. Same mapping the verify path uses
        # (audit M5, 2026-10-25).
        check_model = parse_model_mapping(channel.get("model_mapping")).get(candidate, candidate)
        verdict = do_check(cctest, pin_base, pin_key, check_model)
        LOG.info("[%s] quarantine re-check %s direct -> %s", name, check_model, verdict)
        record_verdict(ch_state, candidate, verdict)
        ch_state["last_quarantine_check"] = now
        if verdict in PASS_VERDICTS:
            # Merchant recovered — release to standby (not active; another
            # pin is serving this model by now). release_quarantine now never
            # enables the channel, so the pin simply rejoins the standby pool.
            release_quarantine(gateway, ch_state, channel_id, name, enforce, discord)
            discord_alert(discord, f"cctest: {name} recovered ({candidate} passes) — back in the standby pool")
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
            LOG.info("[%s] inconclusive re-check; quarantine unchanged", name)
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
    # Active pins are checked with their OWN A6 key (2026-10-27). A
    # gateway-routed check tests whichever channel the router picks: for
    # Kiro-backed models that is kiro-pool, so their A6 pins went 13-35h
    # without a verdict of their own, and with two active pins it lands on
    # a random one. A pin whose key cannot be revealed (legacy plain-named
    # pin, reveal rate limit) keeps the gateway-routed check below.
    direct_key = None
    if is_pinned_channel(name):
        direct_key = _pin_reveal_key(RUNTIME.get("a6m") if RUNTIME else None, name, candidate)
    if direct_key:
        check_name = upstream_candidate  # A6 registers the upstream spelling
        verdict = do_check(cctest, channel.get("base_url") or "https://api.a6api.com",
                           direct_key, check_name)
        LOG.info("[%s] check %s direct (own key) -> %s", name, check_name, verdict)
    else:
        check_name = candidate if is_gateway_routed(base_url) else upstream_candidate
        verdict = do_check(cctest, base_url, seller_key, check_name)
        LOG.info("[%s] check %s (upstream %s) -> %s", name, check_name, upstream_candidate, verdict)

    # Gateway-routed attribution: a check labeled for this channel may
    # have been served by a DIFFERENT channel (the gateway routes by its
    # own priorities). Look up which channel actually served the model in
    # the last few minutes and attribute the verdict there. Without this,
    # failover actions would be taken against channels that never served
    # the checked request (audit 2026-10-13 defect #1). A direct check
    # describes this channel by construction — no attribution hop.
    actual_channel = None
    if is_gateway_routed(base_url) and not direct_key:
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
    # Pool-aware "only entry" test (audit H4, 2026-10-25). Aliases share one
    # pool: a pin listing BOTH gpt-6-1-sol and gpt-6.1-sol kept a non-empty
    # `remaining` after removing one spelling, so it took the model-removal
    # path instead of quarantining. The removal was then blocked by its own
    # channel (which still lists the sibling spelling), and the cycle repeated
    # that forever — a confirmed-fake dual-spelling pin could never be
    # quarantined, only silently kept serving.
    pool = model_pool_names(model)
    remaining = [m for m in (ch.get("models") or "").split(",")
                 if m.strip() and m.strip() not in pool]
    if not remaining:
        LOG.info("[%s] model %s is the only entry; escalating to channel quarantine instead", name, model)
        if enforce:
            start_quarantine(gateway, ch_state, int(ch["id"]), name, model, verdict, discord)
            # Pinned channels: the quarantine IS the merchant-swap trigger —
            # promote the next standby (enable-first, then verify). Without
            # this the model is left with no active pin until the next
            # cycle's quarantined-re-test branch notices.
            # CRITICAL: re-list channels post-quarantine — the snapshot is
            # cycle-start state where the pin we just disabled still shows
            # enabled, so promote_next_standby's idempotence guard would see
            # "already has an active pin" and refuse. (2026-10-23 audit.)
            if is_pinned_channel(name):
                try:
                    fresh = gateway.list_channels()
                except Exception:
                    fresh = channels_snapshot
                promote_next_standby(
                    gateway, cctest, ch, base_url, seller_key, model,
                    enforce, discord, state, fresh,
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
        and pool & {m.strip() for m in (other.get("models") or "").split(",")}
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
    """Returns the verdict category as a string, or None when inconclusive.

    DELIBERATELY A SINGLE VALUE (refactor 2026-10-24). This used to return
    (verdict, prediction), and one caller assigned the whole tuple to a
    variable it then tested with `if pre_verdict:` / `in BAD_VERDICTS`.
    A non-empty tuple is truthy and matches no verdict set, so a FAILED
    pre-promotion check read as a PASS and promoted the merchant anyway
    (live: a6pin-opus-5-5-4756 re-promoted onto 96%-failing traffic while
    the healthy pin was rotated away). The prediction was never used by
    any caller — only by this function's own tier logic — so returning one
    value removes the whole class of unpacking mistakes.

    Callers must treat None as INCONCLUSIVE: never a pass, never a rotation
    trigger. See pin_latency_sick / process_verdict for that contract.

    Accepted-upgrade policy (owner rule 2026-10-23): an attr_swapped verdict
    is reclassified to a PASS verdict here, before any caller sees it:
      - predicted model ranks strictly HIGHER on the tier ladder →
        attr_upgraded (the customer got more than they paid for);
      - predicted model is the SAME rung (spelling alias, e.g. cctest's
        gpt-6.1-sol for our gpt-6-1-sol) → attr_match (it IS the right
        model — quarantining for a dot spelling would be a false positive).
    So no caller counts a fail or quarantines for either. `model` here is
    the name we asked the seller for (SKU or upstream spelling — the tier
    match normalizes both)."""
    result = cctest.check(base_url, seller_key, model)
    if result is None:
        return None
    verdict = cctest.verdict_category(result)
    prediction = cctest.prediction(result) if hasattr(cctest, "prediction") else None
    if verdict == "attr_swapped":
        tier = _tier_match(model, prediction)
        if tier == "higher":
            LOG.warning(
                "[upgrade] expected %s but served %s — strictly higher tier, accepted",
                model, prediction,
            )
            return "attr_upgraded"
        if tier == "same":
            LOG.warning(
                "[alias] expected %s, prediction %s — same model (spelling alias), accepted",
                model, prediction,
            )
            return "attr_match"
    return verdict


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
    """Clear the quarantine state WITHOUT enabling the channel (owner spec
    2026-10-24: "Verify" must only check trueness and lift the quarantine
    tag — never pin. Pinning happens exclusively through "Use this
    merchant" (promote), which owns the quarantine-first→enable-next
    sequence. Previously this set status=ENABLED, which made a verify on
    a standby silently go live — the 2026-10-22 sol double-pin root
    cause. The channel keeps whatever status it has (usually a disabled
    standby); only the quarantine bookkeeping is cleared, so the pin
    returns to the promotable pool instead of the live pool.)
    """
    if not enforce:
        LOG.info("[%s] OBSERVE-ONLY: would release from quarantine", name)
        return
    ch_state.update({"quarantined": False, "fails": 0, "permanent": False,
                     "alerted": False, "model": ""})
    LOG.info("[%s] released from quarantine (kept at current channel status)", name)
    discord_alert(discord, f"cctest: {name} released from quarantine — standby, not pinned")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
