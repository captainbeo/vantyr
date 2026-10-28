"""Tests for the 2026-10-28 pin entry gate in monitor.py:

  - margin floor (PIN_MIN_MARGIN, default 1.5x) on input AND output
  - live probe through the channel test before any cctest check
  - refill skips dead / slow / loss-making standbys without spending checks
  - refill retry pacing (REFILL_RETRY_MINUTES)
  - promote_next_standby honours the gate while the model is still served,
    and fails open only when nothing serves it
  - standby health sweep + deduplicated pool alerts
  - Gateway.sell_prices conversion

Own file so concurrent sessions editing the other test files cannot drop
these. Run: python test_monitor_gate.py
"""
import contextlib
import copy
import importlib.util
import os
import time

spec = importlib.util.spec_from_file_location("monitor", os.path.join(os.path.dirname(__file__), "monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.STATE_PATH = os.path.join(os.environ.get("TEMP", "."), "state_gate_test.json")

A6_BASE = "https://api.a6api.com"
# Fable 5.1 sell: $0.25 in / $1.30 out per 1M.
SELL = {"claude-fable-5-1": (0.25, 1.30)}


@contextlib.contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            os.environ[k] = str(v)
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def runtime(**rt):
    saved = m.RUNTIME
    m.RUNTIME = rt
    try:
        yield
    finally:
        m.RUNTIME = saved
        try:
            os.remove(m.STATE_PATH)
        except OSError:
            pass


@contextlib.contextmanager
def market(prices=None, unlisted=()):
    """Hermetic A6 market. prices: {merchant: (in_micros, out_micros)};
    default $0.108 / $0.54 (3825's listing). Captures discord alerts."""
    prices = prices or {}
    alerts = []
    orig_health, orig_alert = m.A6Market.health_for, m.discord_alert

    def health(self, model, ids):
        out = {}
        for x in ids:
            x = str(x)
            if x in unlisted:
                out[x] = {"healthy": False, "unlisted": True, "price_micros": None,
                          "output_price_micros": None}
                continue
            pin_, pout = prices.get(x, (108000, 540000))
            out[x] = {"healthy": True, "success_rate": 10000, "sample_count": 100,
                      "available": True, "unlisted": False, "price_micros": pin_,
                      "output_price_micros": pout, "supplier": "t"}
        return out

    m.A6Market.health_for = health
    m.discord_alert = lambda hook, text: alerts.append(text)
    m._PIN_KEY_CACHE.clear()
    try:
        yield alerts
    finally:
        m.A6Market.health_for, m.discord_alert = orig_health, orig_alert
        m._PIN_KEY_CACHE.clear()


def pin(cid, name, models, status):
    return {"id": cid, "name": name, "status": status, "models": models,
            "group": "default,unlimited", "model_mapping": "", "base_url": A6_BASE}


class GW:
    """Fake gateway. probes: {channel_id: (ok, ms, detail)}; default alive 2s."""

    def __init__(self, channels, probes=None, sell=None):
        # Own copy: tests reuse one channel list across several refills, and a
        # shared list leaks one call's enables into the next.
        self.channels = copy.deepcopy(channels)
        self.probes = probes or {}
        self.sell = SELL if sell is None else sell
        self.writes = []
        self.probed = []

    def list_channels(self):
        return copy.deepcopy(self.channels)

    def set_status(self, cid, status):
        for ch in self.channels:
            if ch["id"] == cid:
                ch["status"] = status
        self.writes.append((cid, status))
        return True

    def fix_abilities(self):
        return True

    def test_channel(self, cid, model, timeout=90.0):
        self.probed.append(cid)
        return self.probes.get(cid, (True, 2000, "ok"))

    def sell_prices(self):
        return dict(self.sell)

    # _standby_score inputs: no traffic history.
    def count_logs(self, *a, **kw):
        return 0

    def recent_consume_logs(self, *a, **kw):
        return []

    def recent_error_logs(self, *a, **kw):
        return []


class A6M:
    def __init__(self, *names):
        self.tokens = [{"id": i, "name": n} for i, n in enumerate(names)]

    def list_tokens(self):
        return list(self.tokens)

    def reveal_key(self, tid):
        return f"sk-{self.tokens[tid]['name'].split('|')[1].strip()}-{tid}"


class CC:
    def __init__(self, verdicts=None, default="attr_match"):
        self.verdicts = verdicts or {}
        self.default = default
        self.calls = []

    def check(self, base_url, key, model):
        self.calls.append((base_url, key, model))
        merchant = key.split("-")[1] if key.startswith("sk-") else key
        verdict = self.verdicts.get(merchant, self.default)
        return None if verdict is None else {"verdict": verdict}

    @staticmethod
    def verdict_category(result):
        return result["verdict"]


F51 = "claude-fable-5-1"


def pool(*standby_merchants, active=("3825",)):
    chs = []
    cid = 40
    for mer in active:
        chs.append(pin(cid, f"a6pin-fable-5-1-{mer}", F51, 1))
        cid += 1
    for mer in standby_merchants:
        chs.append(pin(cid, f"a6pin-fable-5-1-{mer}", F51, 2))
        cid += 1
    return chs


def ids(chs):
    return {ch["name"].rsplit("-", 1)[-1]: ch["id"] for ch in chs}


# ---------------------------------------------------------------------------
# Margin check
# ---------------------------------------------------------------------------

def test_margin_passes_at_or_above_floor():
    ok, reason = m._margin_check(F51, {"price_micros": 108000, "output_price_micros": 540000}, SELL, 1.5)
    assert ok, reason                       # 2.31x in / 2.41x out
    ok, reason = m._margin_check(F51, {"price_micros": 144000, "output_price_micros": 720000}, SELL, 1.5)
    assert ok, reason                       # 5630: 1.74x / 1.81x


def test_margin_blocks_below_floor_on_either_side():
    # Input fine (2.5x), output 1.3x -> blocked.
    ok, reason = m._margin_check(F51, {"price_micros": 100000, "output_price_micros": 1000000}, SELL, 1.5)
    assert not ok and "floor" in reason, reason
    # The 6.1-sol 4820 case: output 0.7x.
    sell = {"gpt-6-1-sol": (0.10, 0.20)}
    ok, reason = m._margin_check("gpt-6-1-sol", {"price_micros": 57600, "output_price_micros": 288000}, sell, 1.5)
    assert not ok, reason


def test_margin_unknown_fails_open():
    assert m._margin_check(F51, {}, SELL, 1.5)[0]
    assert m._margin_check(F51, {"price_micros": 1}, {}, 1.5)[0]


def test_margin_matches_alias_spelling():
    sell = {"gpt-6-1-sol": (0.10, 0.20)}
    ok, _ = m._margin_check("gpt-6.1-sol", {"price_micros": 20900, "output_price_micros": 104400}, sell, 1.5)
    assert ok


def test_gate_cfg_defaults_and_bad_values():
    with env(PIN_MIN_MARGIN="", PIN_MAX_PROBE_MS="8000", PIN_ENTRY_PROBE="true", REFILL_RETRY_MINUTES="30"):
        os.environ.pop("PIN_MIN_MARGIN")
        cfg = m._gate_cfg()
        assert cfg["min_margin"] == 1.5 and cfg["max_probe_ms"] == 8000 and cfg["probe"]
        assert cfg["retry_seconds"] == 1800
    with env(PIN_MIN_MARGIN="junk", PIN_MAX_PROBE_MS="x"):
        cfg = m._gate_cfg()
        assert cfg["min_margin"] == 1.5 and cfg["max_probe_ms"] == 8000


# ---------------------------------------------------------------------------
# Refill + gate
# ---------------------------------------------------------------------------

def _refill(chs, probes=None, cc=None, prices=None, unlisted=(), state=None, sell=None, **envs):
    gw = GW(chs, probes, sell)
    cc = cc or CC()
    names = [f"FABLE 5.1 | {ch['name'].rsplit('-', 1)[-1]}" for ch in chs]
    state = {} if state is None else state
    defaults = {"REFILL_RETRY_MINUTES": "0", "MIN_ACTIVE_PINS": "2", "MIN_ACTIVE_PINS_BY_MODEL": ""}
    defaults.update(envs)
    with env(**defaults), market(prices, unlisted) as alerts, runtime(a6m=A6M(*names)):
        added = m.refill_active_pins(gw, cc, state, None, True)
    return gw, cc, added, state, alerts


def test_refill_skips_a_dead_standby_without_spending_a_check():
    chs = pool("2000", "6345")
    mid = ids(chs)
    gw, cc, added, state, _ = _refill(chs, probes={mid["2000"]: (False, None, "smart_route_no_active_candidates: 503")})
    assert (mid["6345"], 1) in gw.writes and (mid["2000"], 1) not in gw.writes, gw.writes
    assert len(cc.calls) == 1 and "6345" in cc.calls[0][1], cc.calls  # no check spent on 2000
    assert state["_standby_health"]["a6pin-fable-5-1-2000"]["ok"] is False


def test_refill_skips_a_slow_standby():
    chs = pool("5052")
    mid = ids(chs)
    gw, cc, added, _, _ = _refill(chs, probes={mid["5052"]: (True, 9200, "ok")})
    assert gw.writes == [] and cc.calls == [], (gw.writes, cc.calls)


def test_refill_skips_a_standby_under_the_margin_floor():
    chs = pool("9999", "6345")
    mid = ids(chs)
    gw, cc, added, state, _ = _refill(chs, prices={"9999": (100000, 1000000)})  # out 1.3x
    assert (mid["6345"], 1) in gw.writes and (mid["9999"], 1) not in gw.writes, gw.writes
    assert mid["9999"] not in gw.probed, gw.probed  # price gate runs before the probe
    assert any("9999" in g for g in state["_refill"].get(F51, {}).get("gated", [])) or added, state


def test_refill_custom_floor_and_probe_limit():
    chs = pool("5630")
    mid = ids(chs)
    # 5630 at 1.74x/1.81x: passes 1.5x, blocked at 2.0x.
    gw, _, _, _, _ = _refill(chs, prices={"5630": (144000, 720000)}, PIN_MIN_MARGIN="2.0")
    assert gw.writes == [], gw.writes
    gw, _, _, _, _ = _refill(chs, prices={"5630": (144000, 720000)})
    assert (mid["5630"], 1) in gw.writes, gw.writes
    # Probe limit raised: a 9s merchant passes.
    gw, _, _, _, _ = _refill(chs, probes={mid["5630"]: (True, 9000, "ok")}, PIN_MAX_PROBE_MS="10000")
    assert (mid["5630"], 1) in gw.writes, gw.writes


def test_refill_probe_can_be_disabled():
    chs = pool("6345")
    mid = ids(chs)
    gw, _, _, _, _ = _refill(chs, probes={mid["6345"]: (False, None, "dead")}, PIN_ENTRY_PROBE="false")
    assert (mid["6345"], 1) in gw.writes and gw.probed == [], (gw.writes, gw.probed)


def test_refill_still_runs_cctest_after_the_gate():
    chs = pool("5052", "6345")
    mid = ids(chs)
    gw, cc, _, state, _ = _refill(chs, cc=CC(verdicts={"5052": "attr_swapped"}))
    assert (mid["5052"], 1) not in gw.writes and (mid["6345"], 1) in gw.writes, gw.writes
    assert "a6pin-fable-5-1-5052" in state["bad_standbys"][F51]


def test_refill_target_three_for_a6_only_models():
    chs = pool("6345", "4038", active=("3825", "5630"))
    mid = ids(chs)
    gw, _, added, _, _ = _refill(chs, probes={mid["4038"]: (False, None, "model_not_allowed: 403")},
                                 MIN_ACTIVE_PINS_BY_MODEL="claude-fable-5-1:3")
    assert gw.writes == [(mid["6345"], 1)], gw.writes
    gw, _, _, _, _ = _refill(chs)  # target 2: already full, nothing probed
    assert gw.writes == [] and gw.probed == [], (gw.writes, gw.probed)


def test_refill_retry_pacing():
    chs = pool("2000")
    mid = ids(chs)
    dead = {mid["2000"]: (False, None, "503")}
    state = {}
    gw, _, _, state, _ = _refill(chs, probes=dead, state=state, REFILL_RETRY_MINUTES="30")
    assert gw.probed == [mid["2000"]] and state["_refill"][F51]["active"] == 1
    gw, _, _, _, _ = _refill(chs, probes=dead, state=state, REFILL_RETRY_MINUTES="30")
    assert gw.probed == [], gw.probed  # paced: skipped this tick
    state["_refill"][F51]["at"] = time.time() - 31 * 60
    gw, _, _, _, _ = _refill(chs, probes=dead, state=state, REFILL_RETRY_MINUTES="30")
    assert gw.probed == [mid["2000"]], gw.probed


def test_refill_clears_pacing_once_full():
    chs = pool("6345")
    state = {"_refill": {F51: {"at": 0, "active": 1, "target": 2}}}
    _, _, added, state, _ = _refill(chs, state=state)
    assert added and F51 not in state["_refill"], state


def test_refill_sell_price_failure_fails_open():
    chs = pool("6345")
    mid = ids(chs)
    gw = GW(chs)
    gw.sell_prices = lambda: (_ for _ in ()).throw(RuntimeError("pricing down"))
    with env(REFILL_RETRY_MINUTES="0", MIN_ACTIVE_PINS="2"), market(), runtime(a6m=A6M("FABLE 5.1 | 6345")):
        m.refill_active_pins(gw, CC(), {}, None, True)
    assert (mid["6345"], 1) in gw.writes, gw.writes


# ---------------------------------------------------------------------------
# promote_next_standby + gate
# ---------------------------------------------------------------------------

def _promote(chs, probes=None, cc=None, failed=None, prices=None):
    gw = GW(chs, probes)
    names = [f"FABLE 5.1 | {ch['name'].rsplit('-', 1)[-1]}" for ch in chs]
    state = {}
    with env(MIN_ACTIVE_PINS="2", MIN_ACTIVE_PINS_BY_MODEL=""), market(prices) as alerts, \
            runtime(a6m=A6M(*names)):
        m.promote_next_standby(gw, cc or CC(), failed, "https://vantyr.xyz", "sk-RELAY", F51,
                               True, None, state, gw.list_channels())
    return gw, state, alerts


def test_promote_picks_the_first_standby_that_passes_the_gate():
    chs = pool("2000", "6345")
    mid = ids(chs)
    gw, _, _ = _promote(chs, probes={mid["2000"]: (False, None, "503")})
    assert (mid["6345"], 1) in gw.writes and (mid["2000"], 1) not in gw.writes, gw.writes


def test_promote_refuses_when_no_standby_passes_and_model_is_served():
    chs = pool("2000")
    mid = ids(chs)
    gw, _, _ = _promote(chs, probes={mid["2000"]: (False, None, "503")})
    assert gw.writes == [], gw.writes


def test_promote_fails_open_when_nothing_serves_the_model():
    chs = pool("2000", active=())
    chs.insert(0, pin(39, "a6pin-fable-5-1-1111", F51, 2))  # the failed pin, already off
    mid = ids(chs)
    gw, _, _ = _promote(chs, probes={mid["2000"]: (False, None, "503")},
                        cc=CC(default=None), failed=chs[0])
    assert (mid["2000"], 1) in gw.writes, gw.writes


# ---------------------------------------------------------------------------
# Standby health sweep
# ---------------------------------------------------------------------------

def _sweep(chs, probes=None, state=None, unlisted=(), **envs):
    gw = GW(chs, probes)
    state = {} if state is None else state
    defaults = {"MIN_ACTIVE_PINS": "2", "MIN_ACTIVE_PINS_BY_MODEL": ""}
    defaults.update(envs)
    with env(**defaults), market(unlisted=unlisted) as alerts:
        summary = m.sweep_standby_health(gw, state, "hook")
    return gw, summary, state, alerts


def test_sweep_records_health_and_never_writes_status():
    chs = pool("6345", "4038", active=("3825", "5630"))
    mid = ids(chs)
    gw, summary, state, alerts = _sweep(chs, probes={mid["4038"]: (False, None, "model_not_allowed: 403")})
    assert gw.writes == [], gw.writes
    assert summary[F51]["usable_standbys"] == ["a6pin-fable-5-1-6345"], summary
    assert state["_standby_health"]["a6pin-fable-5-1-4038"]["ok"] is False
    assert state["_standby_health"]["a6pin-fable-5-1-6345"]["ms"] == 2000
    assert alerts == [], alerts  # 2/2 active, one usable spare


def test_sweep_alerts_once_when_no_spare_and_rearms():
    chs = pool("4038", active=("3825", "5630"))
    mid = ids(chs)
    dead = {mid["4038"]: (False, None, "403")}
    state = {}
    _, _, state, alerts = _sweep(chs, probes=dead, state=state)
    assert len(alerts) == 1 and "NO usable standby" in alerts[0], alerts
    _, _, state, alerts = _sweep(chs, probes=dead, state=state)
    assert alerts == [], alerts  # deduplicated
    _, _, state, alerts = _sweep(chs, state=state)  # recovers -> re-arms silently
    assert alerts == [], alerts
    _, _, state, alerts = _sweep(chs, probes=dead, state=state)
    assert len(alerts) == 1, alerts


def test_sweep_alerts_when_pool_is_below_target():
    chs = pool("6345", active=("3825",))
    _, _, _, alerts = _sweep(chs, MIN_ACTIVE_PINS_BY_MODEL="claude-fable-5-1:3")
    assert any("1/3 active" in a for a in alerts), alerts


def test_sweep_skips_permanent_and_delisted_standbys():
    chs = pool("5151", "2000", "6345", active=("3825", "5630"))
    state = {"a6pin-fable-5-1-5151": {"permanent": True}}
    gw, summary, state, _ = _sweep(chs, state=state, unlisted=("2000",))
    mid = ids(chs)
    assert mid["5151"] not in gw.probed and mid["2000"] not in gw.probed, gw.probed
    assert state["_standby_health"]["a6pin-fable-5-1-2000"]["detail"] == "delisted on A6"
    assert summary[F51]["usable_standbys"] == ["a6pin-fable-5-1-6345"]


def test_new_state_keys_are_reserved():
    for key in ("_standby_health", "_standby_alerts", "_refill", "_standby_sweep"):
        assert key in m.RESERVED_STATE_KEYS, key


# ---------------------------------------------------------------------------
# Gateway helpers
# ---------------------------------------------------------------------------

def test_sell_prices_converts_ratios():
    gw = m.Gateway("http://gw", "tok")
    gw._request = lambda method, path, body=None: ({
        "success": True, "group_ratio": {"default": 1},
        "data": [
            {"model_name": F51, "quota_type": 0, "model_ratio": 0.125, "completion_ratio": 5.2},
            {"model_name": "per-request", "quota_type": 1, "model_ratio": 0, "model_price": 0.01},
        ],
    }, 200)
    prices = gw.sell_prices()
    assert abs(prices[F51][0] - 0.25) < 1e-9 and abs(prices[F51][1] - 1.30) < 1e-9, prices
    assert "per-request" not in prices


def test_test_channel_parses_success_and_failure():
    gw = m.Gateway("http://gw", "tok")
    orig = m.http_json
    try:
        m.http_json = lambda *a, **kw: ({"success": True, "time": 2.746}, 200)
        assert gw.test_channel(75, F51) == (True, 2746, "ok")
        m.http_json = lambda *a, **kw: ({"success": False, "error_code": "model_not_allowed",
                                         "message": "bad response status code 403"}, 200)
        ok, ms, detail = gw.test_channel(84, F51)
        assert not ok and ms is None and detail.startswith("model_not_allowed"), detail
        m.http_json = lambda *a, **kw: ({"error": "timeout"}, 0)
        assert gw.test_channel(84, F51)[0] is False
    finally:
        m.http_json = orig


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for t in tests:
        try:
            t()
            print(f"ok {t.__name__}")
        except Exception as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - len(failed)}/{len(tests)} GATE TESTS PASSED")
    raise SystemExit(1 if failed else 0)
