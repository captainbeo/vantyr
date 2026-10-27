"""Tests for the 2026-10-27 pin-pool upgrades in monitor.py:

  - post-promotion grace also applies to error ROWS (the ch51 fable-5 bench)
  - the 5-minute breaker / primary sweep are no longer starved by the hourly
    cycle holding the mutation lock
  - a pin answering a streak of A6 pool errors is benched fast (never the
    model's last pin)
  - while a model is still served, only a PASS-verified standby is enabled
  - every pool is topped up to its pin target (MIN_ACTIVE_PINS, per-model
    MIN_ACTIVE_PINS_BY_MODEL) with own-key-verified standbys
  - active pins are checked with their own A6 key, not through the gateway
  - haiku A6 keys map to a pin

Own file so concurrent sessions editing the other test files cannot drop
these. Run: python test_monitor_pool.py
"""
import contextlib
import copy
import importlib.util
import os
import threading
import time

spec = importlib.util.spec_from_file_location("monitor", os.path.join(os.path.dirname(__file__), "monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.STATE_PATH = os.path.join(os.environ.get("TEMP", "."), "state_pool_test.json")

POOL_ERR = "status_code=502, 智能路由候选均请求失败。 原因：个人池候选均已尝试，没有成功。"
POOL_EMPTY = "status_code=503, 个人智能路由池没有活跃候选。 原因：订阅池中没有可进入路由的活跃商家。"
PLATFORM_503 = "status_code=503, 请求暂时无法处理。 原因：平台的计费数据库通道已达并发上限，本次请求在扣费之前被挡下"

SELLERS = [("a6pin", "https://vantyr.xyz", "sk-RELAY")]
A6_BASE = "https://api.a6api.com"
CIRCUIT_CFG = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
               "client_gone_ratio": 0.50, "hang_threshold": 10**9,
               "error_ratio_threshold": 0.10, "min_errors": 10}


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
def quiet():
    """Hermetic A6 market (every merchant listed and healthy) + captured alerts."""
    alerts = []
    orig_health, orig_alert = m.A6Market.health_for, m.discord_alert
    m.A6Market.health_for = lambda self, model, ids: {
        str(x): {"healthy": True, "success_rate": 10000, "sample_count": 100,
                 "available": True, "unlisted": False, "price_micros": 1, "supplier": "t"}
        for x in ids
    }
    m.discord_alert = lambda hook, text: alerts.append(text)
    m._PIN_KEY_CACHE.clear()
    try:
        yield alerts
    finally:
        m.A6Market.health_for, m.discord_alert = orig_health, orig_alert
        m._PIN_KEY_CACHE.clear()


def pin(cid, name, models, status, mapping=""):
    return {"id": cid, "name": name, "status": status, "models": models,
            "group": "default,unlimited", "model_mapping": mapping, "base_url": A6_BASE}


SOL61 = "gpt-6-1-sol,gpt-6.1-sol"
SOL61_MAP = '{"gpt-6-1-sol":"gpt-6.1-sol","gpt-6.1-sol":"gpt-6.1-sol"}'


class GW:
    """Fake gateway with timestamped log rows. errors/ok: {channel_id:
    [created_at, ...]}; error rows carry `content` from `contents` (default
    an A6 pool error). recent_error_logs ignores since_ts, like the real API."""

    def __init__(self, channels, errors=None, ok=None, contents=None):
        self.channels = channels
        self.errors = errors or {}
        self.ok = ok or {}
        self.contents = contents or {}
        self.writes = []
        self.last_channel_calls = 0

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

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        src = self.errors if log_type == 5 else self.ok
        start = since_ts if since_ts else time.time() - window_minutes * 60
        return sum(1 for t in src.get(channel_id, []) if t >= start)

    def recent_error_logs(self, channel_id, window_minutes, limit=50, max_rows=1000):
        start = time.time() - window_minutes * 60
        contents = self.contents.get(channel_id)
        rows = [{"created_at": int(t), "content": contents[i] if contents else POOL_ERR}
                for i, t in enumerate(self.errors.get(channel_id, [])) if t >= start]
        return sorted(rows, key=lambda r: -r["created_at"])

    def recent_consume_logs(self, channel_id, window_minutes, limit=50):
        start = time.time() - window_minutes * 60
        rows = [{"created_at": int(t), "other": "{}"} for t in self.ok.get(channel_id, []) if t >= start]
        return sorted(rows, key=lambda r: -r["created_at"])[:limit]

    def last_channel_for_model(self, model, window_minutes=10):
        self.last_channel_calls += 1
        return None


class A6M:
    """A6 management fake: reveal_key returns sk-<merchant>-<token id>."""

    def __init__(self, *names):
        self.tokens = [{"id": i, "name": n} for i, n in enumerate(names)]

    def list_tokens(self):
        return list(self.tokens)

    def reveal_key(self, tid):
        return f"sk-{self.tokens[tid]['name'].split('|')[1].strip()}-{tid}"


class CC:
    """cctest fake: verdict by merchant (parsed from sk-<merchant>-<id>),
    `default` otherwise. A None verdict = inconclusive."""

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


def cycle(gw, cc, state=None):
    m.run_cycle(gw, cc, SELLERS, ("claude", "gpt"), 168, lambda name: 1, 3, True, None,
                {} if state is None else state)


# ---------------------------------------------------------------------------
# Post-promotion grace must slice the error rows too
# ---------------------------------------------------------------------------

def test_grace_ignores_error_rows_from_before_promotion():
    """Live 2026-10-27 14:01: fable-5's only pin (ch51) was benched with
    hard_err=30 ok=3 while "in post-promotion grace". The success count was
    sliced to the promotion time but the error rows were not, so 30 errors
    from the pin's previous stint were scored against 3 fresh successes."""
    now = time.time()
    promoted = now - 1800
    cfg = {"enabled": True, "min_samples": 20, "frt_ms_threshold": 15000,
           "client_gone_ratio": 0.75, "hang_threshold": 3, "error_ratio_threshold": 0.05}
    gw = GW([], errors={51: [now - 3 * 3600] * 30}, ok={51: [now - 600] * 3})
    assert m.pin_is_sick(gw, 51, 360, latency_cfg=cfg, since_ts=promoted) is not True
    # Control: outside the grace the same rows still count.
    assert m.pin_is_sick(gw, 51, 360, latency_cfg=cfg) is True
    # Errors since the promotion still count inside the grace.
    gw = GW([], errors={51: [now - 600] * 25}, ok={51: [now - 600] * 3})
    assert m.pin_is_sick(gw, 51, 360, latency_cfg=cfg, since_ts=promoted) is True


def test_grace_starts_at_a_manual_enable_too():
    """Live 2026-10-27 17:29: ch9 (fable-5-4756) was enabled through the
    gateway API at ~17:05 (no monitor promotion, so no promoted_at) and the
    hourly cycle benched it on 20 errors from its 12:54 stint, inside the 6h
    sick window. The gateway stamps other_info.status_time on every status
    change; the grace window starts there as well."""
    now = time.time()
    cfg = {"enabled": True, "min_samples": 20, "frt_ms_threshold": 15000,
           "client_gone_ratio": 0.75, "hang_threshold": 3, "error_ratio_threshold": 0.05}
    enabled_at = int(now - 1800)
    ch = pin(9, "a6pin-fable-5-4756", "claude-fable-5", 1)
    ch["other_info"] = '{"status_reason":"manual operation","status_time":%d}' % enabled_at
    gw = GW([ch, pin(51, "a6pin-fable-5-5630", "claude-fable-5", 1)],
            errors={9: [now - 4 * 3600] * 20 + [now - 300]},
            ok={9: [now - 4 * 3600] * 80 + [now - 600] * 25})
    active = {"claude-fable-5": [c for c in gw.list_channels()]}
    with quiet():
        m._run_sick_rotation(gw, CC(), SELLERS, active, {}, None, True, 360, {}, latency_cfg=cfg)
    assert (9, 2) not in gw.writes, gw.writes
    assert m._pin_enabled_at(ch) == enabled_at
    assert m._pin_enabled_at(pin(1, "a6pin-x-1", "m", 1)) is None
    bad = dict(ch, other_info="not json")
    assert m._pin_enabled_at(bad) is None
    # Control: the same evidence without the enable stamp is sick.
    gw = GW([pin(9, "a6pin-fable-5-4756", "claude-fable-5", 1), pin(51, "a6pin-fable-5-5630", "claude-fable-5", 1)],
            errors={9: [now - 4 * 3600] * 20 + [now - 300]},
            ok={9: [now - 4 * 3600] * 80 + [now - 600] * 25})
    active = {"claude-fable-5": [c for c in gw.list_channels()]}
    with quiet():
        m._run_sick_rotation(gw, CC(), SELLERS, active, {}, None, True, 360, {}, latency_cfg=cfg)
    assert (9, 2) in gw.writes, gw.writes


# ---------------------------------------------------------------------------
# Fast ticks vs the hourly cycle's mutation lock
# ---------------------------------------------------------------------------

def test_fast_tick_gets_the_lock_between_cycle_channels():
    """The hourly cycle holds the mutation lock through each channel's
    cctest check (30-150s), and the 5-minute breaker took it non-blocking, so
    it skipped whenever the cycle was running (13 skipped primary sweeps in
    24h, 09:22-09:32 in a row). A waiting fast tick must get the lock at the
    cycle's next channel boundary, and the cycle must still check every
    channel."""
    chs = [pin(27, "a6pin-opus-5-5-3859", "claude-opus-5-5", 1),
           pin(25, "a6pin-opus-5-5-4756", "claude-opus-5-5", 1)]
    gw = GW(chs)
    result = {}

    class SlowCC(CC):
        def check(self, base_url, key, model):
            if not self.calls:
                # A breaker tick fires while the cycle is mid-check.
                t = threading.Thread(target=lambda: result.setdefault(
                    "n", m.circuit_breaker_tick(CIRCUIT_CFG, 15)))
                t.start()
                result["thread"] = t
                time.sleep(0.5)
            return super().check(base_url, key, model)

    cc = SlowCC()
    with quiet(), runtime(gateway=gw, cctest=cc, sellers=SELLERS, enforce=True,
                          discord=None, state={}, seller_registry={}):
        cycle(gw, cc)
        result["thread"].join(10)
    assert result.get("n") == 2, result      # the tick ran instead of skipping
    assert len(cc.calls) == 2, cc.calls      # and the cycle skipped no channel


def test_cycle_still_skips_when_the_lock_stays_busy():
    chs = [pin(27, "a6pin-opus-5-5-3859", "claude-opus-5-5", 1)]
    gw = GW(chs)
    cc = CC()
    with env(CYCLE_LOCK_WAIT_SECONDS="0"):
        assert m._MUTATION_LOCK.acquire(blocking=False)
        try:
            cycle(gw, cc)
        finally:
            m._MUTATION_LOCK.release()
    assert cc.calls == [] and gw.writes == [], (cc.calls, gw.writes)


# ---------------------------------------------------------------------------
# Fast bench on a streak of A6 pool errors
# ---------------------------------------------------------------------------

def test_pool_dead_needs_a_streak_after_the_last_success():
    now = time.time()
    errs = [now - 60, now - 50, now - 40]
    assert m.pin_pool_dead(GW([], errors={9: errs}, ok={9: [now - 300]}), 9, 15, 3) is True
    # A success after the errors breaks the streak.
    assert m.pin_pool_dead(GW([], errors={9: errs}, ok={9: [now - 30]}), 9, 15, 3) is False
    # Fewer pool errors than the streak.
    assert m.pin_pool_dead(GW([], errors={9: errs[:2]}), 9, 15, 3) is False
    # A6 platform-side 503s (billing DB saturation) are not the merchant's pool.
    gw = GW([], errors={9: errs}, contents={9: [PLATFORM_503] * 3})
    assert m.pin_pool_dead(gw, 9, 15, 3) is False
    # Pool-empty 503s count; rows from before since_ts do not.
    gw = GW([], errors={9: errs}, contents={9: [POOL_EMPTY] * 3})
    assert m.pin_pool_dead(gw, 9, 15, 3) is True
    assert m.pin_pool_dead(gw, 9, 15, 3, since_ts=now - 45) is False

    class Broken(GW):
        def recent_error_logs(self, *a, **k):
            return None
    assert m.pin_pool_dead(Broken([]), 9, 15, 3) is None


def _pool_dead_tick(sibling_status):
    """ch9 answers its last three requests with A6 pool errors after 20
    earlier successes: under the breaker's ratio + 10-error floor, so only the
    streak rule can catch it."""
    now = time.time()
    chs = [pin(51, "a6pin-fable-5-5630", "claude-fable-5", sibling_status),
           pin(9, "a6pin-fable-5-4756", "claude-fable-5", 1)]
    gw = GW(chs, errors={9: [now - 60, now - 50, now - 40]},
            ok={9: [now - 600] * 20, 51: [now - 30] * 20})
    cfg = dict(CIRCUIT_CFG, pool_error_streak=3)
    with quiet() as alerts, runtime(gateway=gw, cctest=CC(), sellers=SELLERS, enforce=True,
                                    discord=None, state={}, seller_registry={}):
        m.circuit_breaker_tick(cfg, 15)
    return gw, alerts


def test_breaker_benches_a_pool_dead_pin_while_another_pin_serves():
    gw, alerts = _pool_dead_tick(sibling_status=1)
    assert (9, 2) in gw.writes, gw.writes
    assert (51, 2) not in gw.writes, gw.writes
    assert any("pool error" in a for a in alerts), alerts


def test_breaker_never_benches_the_last_pin_on_a_pool_streak():
    gw, _ = _pool_dead_tick(sibling_status=2)
    assert (9, 2) not in gw.writes, gw.writes


def test_pool_streak_off_without_config():
    now = time.time()
    chs = [pin(51, "a6pin-fable-5-5630", "claude-fable-5", 1),
           pin(9, "a6pin-fable-5-4756", "claude-fable-5", 1)]
    gw = GW(chs, errors={9: [now - 60, now - 50, now - 40]}, ok={9: [now - 600] * 20})
    with quiet(), runtime(gateway=gw, cctest=CC(), sellers=SELLERS, enforce=True,
                          discord=None, state={}, seller_registry={}):
        m.circuit_breaker_tick(CIRCUIT_CFG, 15)
    assert gw.writes == [], gw.writes


def test_circuit_tick_scores_a_dual_spelling_pin_once():
    chs = [pin(59, "a6pin-6-1-sol-5110", SOL61, 1, SOL61_MAP)]
    seen = []
    orig = m.pin_is_sick
    m.pin_is_sick = lambda gw, cid, *a, **k: seen.append(cid) or False
    try:
        with quiet(), runtime(gateway=GW(chs), cctest=CC(), sellers=SELLERS, enforce=True,
                              discord=None, state={}, seller_registry={}):
            m.circuit_breaker_tick(CIRCUIT_CFG, 15)
    finally:
        m.pin_is_sick = orig
    assert seen == [59], seen


# ---------------------------------------------------------------------------
# PASS-only promotion while the model is still served
# ---------------------------------------------------------------------------

def _promote(chs, cc, a6m, failed=None, model="claude-fable-5", **kw):
    gw = GW(chs)
    state = {}
    with quiet() as alerts, runtime(a6m=a6m):
        m.promote_next_standby(gw, cc, failed, "https://vantyr.xyz", "sk-RELAY", model,
                               True, None, state, gw.list_channels(), **kw)
    return gw, state, alerts


def test_inconclusive_standby_not_enabled_while_model_is_served():
    chs = [pin(51, "a6pin-fable-5-5630", "claude-fable-5", 1),
           pin(9, "a6pin-fable-5-4756", "claude-fable-5", 2)]
    gw, _, _ = _promote(chs, CC(default=None), A6M("FABLE 5 | 4756"))
    assert (9, 1) not in gw.writes, gw.writes


def test_unrevealable_standby_not_enabled_while_model_is_served():
    chs = [pin(51, "a6pin-fable-5-5630", "claude-fable-5", 1),
           pin(9, "a6pin-fable-5-4756", "claude-fable-5", 2)]
    gw, _, _ = _promote(chs, CC(), A6M())
    assert (9, 1) not in gw.writes, gw.writes


def test_inconclusive_standby_still_enabled_when_model_has_no_pin():
    """The 2026-10-24 sonnet-5-5 deadlock guard stays: with nothing serving
    the model, an inconclusive direct check falls back to enable-then-verify."""
    chs = [pin(63, "a6pin-fable-5-4665", "claude-fable-5", 2),
           pin(9, "a6pin-fable-5-4756", "claude-fable-5", 2)]
    gw, _, _ = _promote(chs, CC(default=None), A6M("FABLE 5 | 4756"), failed=chs[0])
    assert (9, 1) in gw.writes, gw.writes


def test_pre_verify_asks_a6_for_the_upstream_spelling():
    """A6 registers gpt-6.1-sol; asking for our SKU gpt-6-1-sol is a 403
    model_not_allowed, i.e. an inconclusive check."""
    chs = [pin(59, "a6pin-6-1-sol-5110", SOL61, 1, SOL61_MAP),
           pin(54, "a6pin-6-1-sol-5132", SOL61, 2, SOL61_MAP)]
    cc = CC()
    gw, _, _ = _promote(chs, cc, A6M("6.1 SOL | 5132"), model="gpt-6-1-sol")
    assert cc.calls and cc.calls[0][2] == "gpt-6.1-sol", cc.calls
    assert (54, 1) in gw.writes, gw.writes


# ---------------------------------------------------------------------------
# Pin targets and refill
# ---------------------------------------------------------------------------

def test_min_active_for_per_model_overrides():
    with env(MIN_ACTIVE_PINS="2",
             MIN_ACTIVE_PINS_BY_MODEL="claude-fable-5-1:3, gpt-6.1-sol:3, junk, claude-opus-5:x"):
        assert m.min_active_for("claude-fable-5-1") == 3
        assert m.min_active_for("gpt-6-1-sol") == 3      # alias spelling
        assert m.min_active_for("claude-opus-5") == 2    # malformed entry ignored
        assert m.min_active_for("claude-sonnet-5") == 2
    with env(MIN_ACTIVE_PINS="bogus", MIN_ACTIVE_PINS_BY_MODEL=""):
        assert m.min_active_for("claude-sonnet-5") == 2


def test_dedup_keeps_each_models_own_target():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 1),
           pin(43, "a6pin-fable-5-1-2000", "claude-fable-5-1", 1),
           pin(20, "a6pin-opus-5-851", "claude-opus-5", 1),
           pin(22, "a6pin-opus-5-1204", "claude-opus-5", 1),
           pin(23, "a6pin-opus-5-3456", "claude-opus-5", 1)]
    gw = GW(chs)
    with env(MIN_ACTIVE_PINS="2", MIN_ACTIVE_PINS_BY_MODEL="claude-fable-5-1:3"), quiet():
        cycle(gw, CC())
    disabled = [cid for cid, s in gw.writes if s == 2]
    assert disabled == [23], gw.writes


def test_refill_adds_a_verified_second_pin():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2),
           pin(41, "a6pin-fable-5-1-5052", "claude-fable-5-1", 2)]
    gw, cc = GW(chs), CC()
    with quiet() as alerts, runtime(a6m=A6M("FABLE 5.1 | 5630", "FABLE 5.1 | 5052")):
        added = m.refill_active_pins(gw, cc, {}, None, True)
    enabled = [cid for cid, s in gw.writes if s == 1]
    assert len(enabled) == 1 and len(added) == 1, (gw.writes, added)
    assert cc.calls and all(c[0] == A6_BASE for c in cc.calls), cc.calls  # own-key checks
    assert any("refill" in a for a in alerts), alerts


def test_refill_tries_the_next_standby_after_a_bad_one():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2),
           pin(41, "a6pin-fable-5-1-5052", "claude-fable-5-1", 2)]
    gw = GW(chs)
    with quiet(), runtime(a6m=A6M("FABLE 5.1 | 5630", "FABLE 5.1 | 5052")):
        m.refill_active_pins(gw, CC(verdicts={"5630": "attr_swapped"}), {}, None, True)
    assert (41, 1) in gw.writes and (42, 1) not in gw.writes, gw.writes


def test_refill_never_enables_an_inconclusive_standby():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2)]
    gw = GW(chs)
    with quiet(), runtime(a6m=A6M("FABLE 5.1 | 5630")):
        m.refill_active_pins(gw, CC(default=None), {}, None, True)
    assert gw.writes == [], gw.writes


def test_refill_leaves_a_pool_with_no_active_pin_to_failover():
    chs = [pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2)]
    gw, cc = GW(chs), CC()
    with quiet(), runtime(a6m=A6M("FABLE 5.1 | 5630")):
        m.refill_active_pins(gw, cc, {}, None, True)
    assert gw.writes == [] and cc.calls == [], (gw.writes, cc.calls)


def test_refill_skips_quarantined_standbys():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(75, "a6pin-fable-5-1-6345", "claude-fable-5-1", 2)]
    gw, cc = GW(chs), CC()
    state = {"a6pin-fable-5-1-6345": {"quarantined": True, "model": "claude-fable-5-1"}}
    with quiet(), runtime(a6m=A6M("FABLE 5.1 | 6345")):
        m.refill_active_pins(gw, cc, state, None, True)
    assert gw.writes == [] and cc.calls == [], (gw.writes, cc.calls)


def test_refill_without_a6_management_does_nothing():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2)]
    gw, cc = GW(chs), CC()
    with quiet(), runtime(a6m=None):
        m.refill_active_pins(gw, cc, {}, None, True)
    assert gw.writes == [] and cc.calls == [], (gw.writes, cc.calls)


def test_refill_honours_a_per_model_target_of_three():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 1),
           pin(41, "a6pin-fable-5-1-5052", "claude-fable-5-1", 2)]
    for target, expect in (("", []), ("claude-fable-5-1:3", [(41, 1)])):
        gw = GW(copy.deepcopy(chs))
        with env(MIN_ACTIVE_PINS_BY_MODEL=target), quiet(), runtime(a6m=A6M("FABLE 5.1 | 5052")):
            m.refill_active_pins(gw, CC(), {}, None, True)
        assert gw.writes == expect, (target, gw.writes)


def test_cycle_refills_after_its_checks():
    chs = [pin(40, "a6pin-fable-5-1-3825", "claude-fable-5-1", 1),
           pin(42, "a6pin-fable-5-1-5630", "claude-fable-5-1", 2)]
    gw = GW(chs)
    with quiet(), runtime(a6m=A6M("FABLE 5.1 | 3825", "FABLE 5.1 | 5630")):
        cycle(gw, CC())
    assert (42, 1) in gw.writes, gw.writes


# ---------------------------------------------------------------------------
# Active pins are checked with their own key
# ---------------------------------------------------------------------------

def test_active_pin_checked_with_its_own_key():
    """For Kiro-backed models the gateway-routed check landed on kiro-pool,
    so their A6 pins went 13-35h without a verdict of their own."""
    chs = [pin(27, "a6pin-opus-5-5-3859", "claude-opus-5-5", 1),
           {"id": 95, "name": "kiro-pool", "status": 1, "models": "claude-opus-5-5",
            "group": "default,unlimited", "model_mapping": ""}]
    gw, cc, state = GW(chs), CC(), {}
    with quiet(), runtime(a6m=A6M("OPUS 5.5 | 3859")):
        cycle(gw, cc, state)
    assert cc.calls == [(A6_BASE, "sk-3859-0", "claude-opus-5-5")], cc.calls
    assert gw.last_channel_calls == 0, "no gateway attribution hop for a direct check"
    assert state["a6pin-opus-5-5-3859"]["last_verdicts"]["claude-opus-5-5"]["verdict"] == "attr_match"


def test_direct_check_uses_the_upstream_spelling():
    chs = [pin(59, "a6pin-6-1-sol-5110", SOL61, 1, SOL61_MAP)]
    gw, cc = GW(chs), CC()
    with env(MIN_ACTIVE_PINS="1"), quiet(), runtime(a6m=A6M("6.1 SOL | 5110")):
        cycle(gw, cc)
    assert cc.calls and cc.calls[0][2] == "gpt-6.1-sol", cc.calls


def test_bad_direct_verdict_quarantines_the_active_pin():
    chs = [pin(27, "a6pin-opus-5-5-3859", "claude-opus-5-5", 1),
           pin(25, "a6pin-opus-5-5-4756", "claude-opus-5-5", 1)]
    gw = GW(chs)
    with quiet(), runtime(a6m=A6M("OPUS 5.5 | 3859", "OPUS 5.5 | 4756")):
        cycle(gw, CC(verdicts={"3859": "attr_swapped"}))
    assert (27, 2) in gw.writes and (25, 2) not in gw.writes, gw.writes


def test_active_pin_without_key_falls_back_to_the_gateway_check():
    chs = [pin(27, "a6pin-opus-5-5-3859", "claude-opus-5-5", 1)]
    gw, cc = GW(chs), CC()
    with quiet(), runtime(a6m=A6M()):
        cycle(gw, cc)
    assert cc.calls == [("https://vantyr.xyz", "sk-RELAY", "claude-opus-5-5")], cc.calls
    assert gw.last_channel_calls == 1


# ---------------------------------------------------------------------------
# Haiku
# ---------------------------------------------------------------------------

def test_haiku_keys_map_to_a_pin():
    assert m.parse_a6_key_name("HAIKU 5.5 | 3999") == ("claude-haiku-5-5", "3999", "a6pin-haiku-5-5-3999")
    assert m.pin_merchant("a6pin-haiku-5-5-3999") == "3999"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for t in tests:
        try:
            t()
            print(f"ok {t.__name__}")
        except Exception as e:  # report every failure, not just the first
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - len(failed)}/{len(tests)} POOL TESTS PASSED")
    raise SystemExit(1 if failed else 0)
