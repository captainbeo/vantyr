"""Randomized failover simulation for the pin pool (2026-10-28, owner ask:
"heavy test the standby > pinned and pinned > standby mechanism").

A fake world holds merchants whose hidden truth changes over time (alive /
dead, genuine / swapped, fast / slow, A6 price, listed / delisted). Every
simulated 5 minutes customer traffic is written to a fake gateway log, then
the monitor's REAL code runs against it exactly as production schedules it:

  every tick (5m)   circuit_breaker_tick   (fast bench + sick rotation)
  every tick (5m)   refill_active_pins     (fast refill thread, locked=False)
  every 6 ticks     sweep_standby_health   (30-minute standby sweep)
  every 12 ticks    run_cycle              (hourly cctest cycle)
  ~1% of ticks      run_action_promote     (operator "use this merchant")

After every step the invariants below are checked. Phase B repeats the run
with injected gateway / cctest faults.

Invariants (each violation is reported with seed, tick and context):
  I1  a pool never has more active pins than its target
  I2  a monitor enable while the pool is still served goes only to a merchant
      that is alive, genuine, inside the probe limit, inside the margin floor,
      listed, not quarantined and not bad-marked
  I3  the standby sweep never changes a channel's status
  I4  a fake active pin is benched within 2 hourly cycles
  I5  a dead active pin is benched within 4 ticks while another pin serves
  I6  a pool is never dark for more than 3 ticks while a good, eligible
      standby exists
  I7  a short pool with enough good eligible standbys reaches its target
  I8  no unexpected exception (phase A: none at all)
  I9  state stays JSON-serializable

Run: python test_monitor_sim.py [seeds] [ticks]
"""
import importlib.util
import json
import logging
import os
import random
import sys
import types

spec = importlib.util.spec_from_file_location("monitor", os.path.join(os.path.dirname(__file__), "monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.STATE_PATH = os.path.join(os.environ.get("TEMP", "/tmp"), "state_sim_test.json")

TICK = 300
SELLERS = [("a6pin", "https://vantyr.xyz", "sk-RELAY")]
LATENCY_CFG = {"enabled": True, "min_samples": 20, "frt_ms_threshold": 15000,
               "client_gone_ratio": 0.75, "hang_threshold": 3, "error_ratio_threshold": 0.05,
               "min_errors": 5}
CIRCUIT_CFG = {"enabled": True, "min_samples": 15, "client_gone_ratio": 0.50,
               "frt_ms_threshold": 10**12, "hang_threshold": 10**9,
               "error_ratio_threshold": 0.10, "min_errors": 10, "pool_error_streak": 3}
ENV = {
    "MIN_ACTIVE_PINS": "2",
    "MIN_ACTIVE_PINS_BY_MODEL": "claude-fable-5-1:3,gpt-6-astra:3,gpt-6-1-sol:3",
    "REFILL_MAX_CHECKS": "2", "REFILL_RETRY_MINUTES": "30", "STANDBY_COOLDOWN_HOURS": "3",
    "PIN_MIN_MARGIN": "1.5", "PIN_MAX_PROBE_MS": "15000", "PIN_ENTRY_PROBE": "true",
    "QUARANTINE_RECHECK_HOURS": "2", "QUARANTINE_RECHECK_PERMANENT_HOURS": "3",
    "USAGE_WINDOW_HOURS": "7", "FAST_TICK_LOCK_WAIT_SECONDS": "0",
}
POOL_ERR = "status_code=502, 智能路由候选均请求失败。 原因：个人池候选均已尝试，没有成功。"
LOWER = {"claude-fable-5-1": "claude-opus-5-5", "gpt-6-astra": "gpt-6-1-sol",
         "gpt-6-1-sol": "gpt-6-sol", "claude-opus-5-5": "claude-sonnet-5-5"}

# pool sku -> (A6 key-name model part, sell $/1M in/out, target, merchants, starting actives)
# merchant spec: (id, upstream spelling) — the spelling A6 lists and permits for the key.
POOLS = {
    "claude-fable-5-1": ("FABLE 5.1", (0.25, 1.30), 3,
                         [("3825", "claude-fable-5-1"), ("5630", "claude-fable-5-1"),
                          ("6345", "claude-fable-5-1"), ("4038", "claude-fable-5.1"),
                          ("7001", "claude-fable-5-1"), ("7002", "claude-fable-5.1")], 2),
    "gpt-6-astra": ("ASTRA 6", (0.20, 0.70), 3,
                    [("5703", "gpt-6-astra"), ("5942", "gpt-6-astra"), ("4848", "gpt-6-astra"),
                     ("5961", "gpt-6-astra"), ("5132", "gpt-6-astra"), ("5940", "gpt-6-astra")], 2),
    "gpt-6-1-sol": ("6.1 SOL", (0.10, 0.20), 3,
                    [("5110", "gpt-6.1-sol"), ("5132", "gpt-6.1-sol"), ("5950", "gpt-6.1-sol"),
                     ("1416", "gpt-6.1-sol"), ("5942", "gpt-6.1-sol"), ("5312", "gpt-6.1-sol")], 2),
    "claude-opus-5-5": ("OPUS 5.5", (0.10, 0.45), 2,
                        [("3859", "claude-opus-5-5"), ("535", "claude-opus-5-5"),
                         ("4756", "claude-opus-5-5"), ("6484", "claude-opus-5-5"),
                         ("5828", "claude-opus-5-5")], 2),
}
SOL_MAP = '{"gpt-6-1-sol":"gpt-6.1-sol","gpt-6.1-sol":"gpt-6.1-sol"}'


class Fault(RuntimeError):
    """Injected failure (phase B)."""


class Clock:
    def __init__(self):
        self.now = 1_793_000_000.0

    def time(self):
        return self.now

    def sleep(self, _s):
        return None


class Merchant:
    def __init__(self, pool, mid, upstream, rng, good=False):
        self.pool, self.mid, self.upstream = pool, mid, upstream
        self.alive = good or rng.random() < 0.85
        self.genuine = good or rng.random() < 0.80
        self.latency = rng.choice([1200, 2500, 4000, 7000]) if good else rng.choice([800, 2500, 6000, 12000, 21000])
        sell_in, sell_out = POOLS[pool][1]
        margin = 2.2 if good else rng.choice([1.2, 1.6, 2.0, 2.6])
        self.price_in = sell_in / margin * 1e6
        self.price_out = sell_out / margin * 1e6
        self.listed = good or rng.random() < 0.92

    @property
    def margin(self):
        sell_in, sell_out = POOLS[self.pool][1]
        return min(sell_in / (self.price_in / 1e6), sell_out / (self.price_out / 1e6))

    def good(self, gate):
        return (self.alive and self.genuine and self.listed
                and self.latency <= gate["max_probe_ms"] and self.margin >= gate["min_margin"])


class World:
    """Fake gateway + A6 marketplace + A6 management + cctest."""

    def __init__(self, seed, faults=False):
        self.rng = random.Random(seed)
        self.clock = Clock()
        self.faults = faults
        self.channels, self.by_id, self.merchant = [], {}, {}
        self.rows = {}           # channel id -> [row, ...] (append order = time order)
        self.writes = []         # (t, cid, status, actor)
        self.tokens = []         # A6 management tokens
        self.actor = "monitor"
        self.cc_calls = 0
        cid = 100
        for pool, (keyname, _sell, _target, merchants, start_active) in POOLS.items():
            for i, (mid, upstream) in enumerate(merchants):
                name = m.parse_a6_key_name(f"{keyname} | {mid}")[2]
                assert name, (keyname, mid)
                mer = Merchant(pool, mid, upstream, self.rng, good=i < start_active)
                models, mapping = pool, ""
                if pool == "gpt-6-1-sol":
                    models, mapping = "gpt-6-1-sol,gpt-6.1-sol", SOL_MAP
                elif upstream != pool:
                    mapping = json.dumps({pool: upstream})
                ch = {"id": cid, "name": name, "status": 1 if i < start_active else 2,
                      "models": models, "model_mapping": mapping, "group": "default,unlimited",
                      "base_url": "https://api.a6api.com",
                      "other_info": json.dumps({"status_time": int(self.clock.now) - 86400})}
                self.channels.append(ch)
                self.by_id[cid] = ch
                self.merchant[cid] = mer
                self.rows[cid] = []
                self.tokens.append({"id": len(self.tokens), "name": f"{keyname} | {mid}", "cid": cid})
                cid += 1

    # ----- helpers -------------------------------------------------------
    def pool_of(self, ch):
        return sorted(m.model_pool_names(ch["models"].split(",")[0].strip()))[0]

    def actives(self, pool):
        return [c for c in self.channels if c["status"] == 1 and self.pool_of(c) == pool]

    def maybe_fault(self, p=0.04):
        if self.faults and self.rng.random() < p:
            raise Fault("injected")

    def log(self, cid, typ, model, frt=None, content="", token="cust"):
        other = {}
        if frt is not None:
            other = {"frt": frt, "stream_status": {"end_reason": "eof"}}
        self.rows[cid].append({"created_at": int(self.clock.now), "type": typ, "channel": cid,
                               "model_name": model, "content": content, "token_name": token,
                               "other": json.dumps(other), "prompt_tokens": 400})

    # ----- world dynamics --------------------------------------------------
    def evolve(self):
        for mer in self.merchant.values():
            r = self.rng.random()
            if r < 0.006:
                mer.alive = not mer.alive
            elif r < 0.010:
                mer.genuine = not mer.genuine
            elif r < 0.013:
                mer.latency = self.rng.choice([1500, 3000, 9000, 22000])
            elif r < 0.014:
                mer.listed = not mer.listed

    def traffic(self, per_pool=6):
        start = self.clock.now - TICK
        for pool in POOLS:
            act = self.actives(pool)
            if not act:
                continue
            for k in range(per_pool):
                ch = act[k % len(act)]
                mer = self.merchant[ch["id"]]
                saved, self.clock.now = self.clock.now, start + (k + 1) * TICK / (per_pool + 1)
                if mer.alive:
                    self.log(ch["id"], 2, pool, frt=mer.latency)
                else:
                    self.log(ch["id"], 5, pool, content=POOL_ERR)
                self.clock.now = saved

    # ----- Gateway API (monitor.Gateway surface) ---------------------------
    def list_channels(self):
        self.maybe_fault()
        return json.loads(json.dumps(self.channels))

    def set_status(self, cid, status):
        self.maybe_fault(0.02)
        ch = self.by_id[int(cid)]
        # Pins of the same pool serving at the moment of this write (I2 needs
        # the instant, not the step start: a bench + fail-open in one step).
        self.others_at_write = sum(1 for c in self.channels
                                   if c["status"] == 1 and c["id"] != ch["id"]
                                   and self.pool_of(c) == self.pool_of(ch))
        # Quarantine flag at the instant of the write: a pin re-checked and
        # released earlier in the same step is a legitimate candidate.
        quarantined_now = bool((getattr(self, "state", None) or {}).get(ch["name"], {}).get("quarantined"))
        if ch["status"] != status:
            ch["status"] = status
            ch["other_info"] = json.dumps({"status_time": int(self.clock.now)})
        self.writes.append((self.clock.now, int(cid), status, self.actor, self.others_at_write,
                            quarantined_now))
        return True

    def fix_abilities(self):
        return True

    def _rows(self, cid, typ, window_minutes, since_ts=None):
        start = int(since_ts) if since_ts else int(self.clock.now) - int(window_minutes) * 60
        return [r for r in self.rows.get(int(cid), []) if r["type"] == typ and r["created_at"] >= start]

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        self.maybe_fault(0.01)
        return len(self._rows(channel_id, log_type, window_minutes, since_ts))

    def count_probe_logs(self, channel_id, window_minutes, since_ts=None):
        return sum(1 for r in self._rows(channel_id, 2, window_minutes, since_ts)
                   if r["token_name"] == m.CHANNEL_TEST_TOKEN_NAME)

    def recent_consume_logs(self, channel_id, window_minutes, limit=50):
        return list(reversed(self._rows(channel_id, 2, window_minutes)))[:limit]

    def recent_error_logs(self, channel_id, window_minutes, limit=50, max_rows=1000):
        return list(reversed(self._rows(channel_id, 5, window_minutes)))[:max_rows]

    def last_channel_for_model(self, model, window_minutes=10):
        best = None
        for cid, rows in self.rows.items():
            for r in rows:
                if r["type"] == 2 and r["model_name"] == model and r["created_at"] >= self.clock.now - window_minutes * 60:
                    if best is None or r["created_at"] > best[0]:
                        best = (r["created_at"], cid)
        return best[1] if best else None

    def model_used_recently(self, *a, **kw):
        return True

    def update_channel_models(self, cid, models):
        self.by_id[int(cid)]["models"] = ",".join(models)
        return True

    def test_channel(self, channel_id, model, timeout=90.0):
        self.maybe_fault(0.02)
        ch = self.by_id[int(channel_id)]
        mer = self.merchant[int(channel_id)]
        upstream = m.parse_model_mapping(ch.get("model_mapping")).get(model, model)
        if upstream != mer.upstream:
            return False, None, "model_not_allowed: 403"
        if not mer.alive:
            return False, None, "smart_route_no_active_candidates: 503"
        self.log(int(channel_id), 2, model, frt=mer.latency, token=m.CHANNEL_TEST_TOKEN_NAME)
        return True, mer.latency, "ok"

    def sell_prices(self):
        self.maybe_fault(0.02)
        return {p: v[1] for p, v in POOLS.items()}

    # ----- A6 marketplace (A6Market.search) ---------------------------------
    def search(self, spelling):
        items = []
        for mer in self.merchant.values():
            if mer.listed and mer.upstream == spelling:
                items.append({"channel_id": int(mer.mid), "listing_availability": 1,
                              "recent_success_rate": 10000 if mer.alive else 8000,
                              "sample_count": 100, "input_price_micros": mer.price_in,
                              "output_price_micros": mer.price_out, "supplier_name": "sim"})
        return items

    # ----- A6 management ----------------------------------------------------
    def list_tokens(self):
        self.maybe_fault(0.01)
        return [{"id": t["id"], "name": t["name"]} for t in self.tokens]

    def reveal_key(self, tid):
        return f"sk-tok{tid}"

    # ----- cctest -----------------------------------------------------------
    def cc_check(self, base_url, key, model):
        self.cc_calls += 1
        if self.faults and self.rng.random() < 0.05:
            return None
        if key == "sk-RELAY":
            act = self.actives(sorted(m.model_pool_names(model))[0])
            if not act:
                return None
            cid = act[0]["id"]
        else:
            cid = self.tokens[int(key[len("sk-tok"):])]["cid"]
        mer = self.merchant[cid]
        if key != "sk-RELAY" and model != mer.upstream:
            return None              # A6 403 model_not_allowed -> inconclusive
        if not mer.alive:
            return None              # A6 503 -> inconclusive
        if not mer.genuine:
            return {"verdict": "attr_swapped", "prediction": LOWER[mer.pool]}
        if mer.upstream == "claude-fable-5.1":
            # cctest names the dash rung for a dot request: must read as a match.
            return {"verdict": "attr_swapped", "prediction": "claude-fable-5-1"}
        return {"verdict": "attr_match", "prediction": model}


class CCAdapter:
    def __init__(self, world):
        self.w = world

    def check(self, base_url, key, model):
        return self.w.cc_check(base_url, key, model)

    @staticmethod
    def verdict_category(result):
        return result.get("verdict")

    @staticmethod
    def prediction(result):
        return result.get("prediction")


class MgmtAdapter:
    def __init__(self, world):
        self.w = world

    def list_tokens(self):
        return self.w.list_tokens()

    def reveal_key(self, tid):
        return self.w.reveal_key(tid)


class ErrorCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def threshold_for(name):
    return 2 if name.startswith("a6pin") else 1


def run_seed(seed, ticks, faults=False):
    w = World(seed, faults)
    gate = None
    state = {}
    w.state = state  # set_status reads the quarantine flag at the write instant
    m._PIN_KEY_CACHE.clear()
    saved = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    orig = {"time": m.time, "search": m.A6Market.search, "alert": m.discord_alert,
            "save": m.save_state, "runtime": m.RUNTIME}
    m.time = types.SimpleNamespace(time=w.clock.time, sleep=w.clock.sleep)
    # datetime.now must follow the fake clock too: quarantined_since and
    # verdict timestamps are compared against time.time() deadlines.
    real_dt = m.datetime

    class _SimDatetime(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt.fromtimestamp(w.clock.now, tz)

    m.datetime = _SimDatetime
    m.A6Market.search = lambda self, model: w.search(model)
    alerts = []
    m.discord_alert = lambda hook, text: alerts.append(text)
    m.save_state = lambda st: None
    cap = ErrorCapture()
    m.LOG.addHandler(cap)
    debug_buf = None
    dbg = None
    if os.environ.get("SIM_DEBUG"):
        debug_buf = []

        class _Dbg(logging.Handler):
            def emit(self, record):
                debug_buf.append(f"t={int((w.clock.now - 1_793_000_000) // TICK)} "
                                 f"{record.levelname[0]} {record.getMessage()}")
                del debug_buf[:-400]

        dbg = _Dbg(level=logging.INFO)
        m.LOG.addHandler(dbg)
    m.LOG.setLevel(logging.INFO)
    m.LOG.propagate = False
    cc = CCAdapter(w)
    m.RUNTIME = {"gateway": w, "cctest": cc, "sellers": SELLERS, "enforce": True,
                 "threshold_for": threshold_for, "discord": None, "state": state,
                 "seller_registry": {}, "a6m": MgmtAdapter(w), "primary_channels": (),
                 "primary_probe": {}}
    violations, stats = [], {"enables": 0, "fail_open": 0, "operator": 0, "benches": 0,
                             "dark_ticks": 0, "short_ticks": 0, "cc_calls": 0}
    fake_since, dead_since, dark_since, short_since = {}, {}, {}, {}

    def viol(tag, text):
        violations.append(f"seed {seed} tick {t} {tag}: {text}")
        if debug_buf is not None and tag in os.environ.get("SIM_DEBUG", "").split(","):
            pool_hint = os.environ.get("SIM_DEBUG_POOL", "")
            print(f"--- {tag} seed {seed} tick {t}: {text}")
            for line in debug_buf[-120:]:
                if not pool_hint or pool_hint in line:
                    print("    ", line)
            debug_buf.clear()

    def eligible_good(pool):
        cooldown = int(ENV["STANDBY_COOLDOWN_HOURS"]) * 3600
        marks = {}
        for sp in m.model_pool_names(pool):
            if isinstance((state.get("bad_standbys") or {}).get(sp), dict):
                marks.update(state["bad_standbys"][sp])
        out = []
        for ch in w.channels:
            if ch["status"] != 2 or w.pool_of(ch) != pool:
                continue
            st = state.get(ch["name"]) or {}
            if st.get("quarantined") or (ch["name"] in marks and w.clock.now - marks[ch["name"]] < cooldown):
                continue
            if w.merchant[ch["id"]].good(gate):
                out.append(ch)
        return out

    try:
        gate = m._gate_cfg()
        for t in range(1, ticks + 1):
            w.clock.now += TICK
            w.evolve()
            w.traffic()
            before_status = {c["id"]: c["status"] for c in w.channels}
            snapshot_actives = {p: {c["id"] for c in w.actives(p)} for p in POOLS}
            pre_state = json.loads(json.dumps(state))
            n_writes = len(w.writes)
            # Breaker, then the fast refill as its own step (fast_refill_loop:
            # unlocked probes/checks, lock only around each enable).
            steps = [("breaker", lambda: m.circuit_breaker_tick(CIRCUIT_CFG, 15)),
                     ("refill", lambda: m.refill_active_pins(w, cc, state, None, True, locked=False))]
            if t % 6 == 0:
                steps.append(("sweep", lambda: m.sweep_standby_health(w, state, None)))
            if t % 12 == 0:
                steps.append(("cycle", lambda: m.run_cycle(
                    w, cc, SELLERS, ("claude", "gpt"), 168, threshold_for, 3, True, None, state,
                    None, None, 360, latency_cfg=LATENCY_CFG)))
            if w.rng.random() < 0.01:
                pool = w.rng.choice(list(POOLS))
                stand = [c for c in w.channels if c["status"] == 2 and w.pool_of(c) == pool]
                if stand:
                    pick = w.rng.choice(stand)["name"].rsplit("-", 1)[-1]
                    steps.append(("operator", lambda pool=pool, pick=pick: m.run_action_promote(
                        {"model": pool, "merchant": pick})))
            for label, fn in steps:
                w.actor = "operator" if label == "operator" else label
                if label == "operator":
                    stats["operator"] += 1
                mark = len(w.writes)
                pool_actives = {p: len(w.actives(p)) for p in POOLS}
                quarantined_before = {n for n, s in state.items() if isinstance(s, dict) and s.get("quarantined")}
                try:
                    fn()
                except Fault:
                    pass
                except Exception as e:
                    viol("I8", f"{label} raised {type(e).__name__}: {e}")
                for (_t, cid, status, actor, others_at_write, quarantined_now) in w.writes[mark:]:
                    ch = w.by_id[cid]
                    pool = w.pool_of(ch)
                    if label == "sweep":
                        viol("I3", f"sweep wrote status {status} on {ch['name']}")
                    if status == 2 and snapshot_actives[pool] and cid in snapshot_actives[pool]:
                        stats["benches"] += 1
                    if status != 1 or label == "operator":
                        continue
                    stats["enables"] += 1
                    others = [c for c in w.channels if c["status"] == 1 and w.pool_of(c) == pool and c["id"] != cid]
                    # "Still served" is judged at the instant of the enable: a
                    # step that benches the last pin and then fails open is a
                    # fail-open, not a gated promotion.
                    served_before = others_at_write > 0
                    mer = w.merchant[cid]
                    if not served_before:
                        stats["fail_open"] += 1
                        continue
                    problems = []
                    if not mer.alive:
                        problems.append("dead")
                    if not mer.genuine:
                        problems.append("fake")
                    if not mer.listed:
                        problems.append("delisted")
                    if mer.latency > gate["max_probe_ms"]:
                        problems.append(f"slow {mer.latency}ms")
                    if mer.margin < gate["min_margin"] - 1e-9:
                        problems.append(f"margin {mer.margin:.2f}x")
                    # Quarantine is judged at the instant of the enable: a pin
                    # re-checked, passed and released earlier in the same step
                    # is a legitimate candidate.
                    if quarantined_now:
                        problems.append("quarantined")
                    if problems:
                        viol("I2", f"{label} enabled {ch['name']} ({', '.join(problems)}) with "
                                   f"{len(others)} other pin(s) serving {pool}")
            for rec in cap.records:
                if rec.exc_info and not (faults and rec.exc_info[0] is Fault):
                    viol("I8", f"logged exception: {rec.getMessage()} ({rec.exc_info[1]!r})")
            cap.records.clear()
            try:
                json.dumps(state)
            except (TypeError, ValueError) as e:
                viol("I9", f"state not serializable: {e}")
            # Pool-level invariants.
            for pool in POOLS:
                target = m.min_active_for(pool)
                act = w.actives(pool)
                if len(act) > target:
                    viol("I1", f"{pool} has {len(act)} active pins > target {target}")
                for ch in act:
                    mer = w.merchant[ch["id"]]
                    if not mer.genuine:
                        fake_since.setdefault(ch["id"], t)
                        # 2 bad verdicts on 2 hourly cycles (+ the partial
                        # cycle it turned fake in). Phase B may lose a whole
                        # cycle to an injected channel-list fault: one more.
                        if t - fake_since[ch["id"]] > (38 if faults else 26):
                            viol("I4", f"fake {ch['name']} active for {t - fake_since[ch['id']]} ticks")
                            fake_since[ch["id"]] = t
                    else:
                        fake_since.pop(ch["id"], None)
                    if not mer.alive and len(act) > 1:
                        dead_since.setdefault(ch["id"], t)
                        if t - dead_since[ch["id"]] > 4:
                            viol("I5", f"dead {ch['name']} active for {t - dead_since[ch['id']]} ticks "
                                       f"with {len(act) - 1} other pin(s)")
                            dead_since[ch["id"]] = t
                    else:
                        dead_since.pop(ch["id"], None)
                for cid in list(fake_since):
                    if w.by_id[cid]["status"] != 1:
                        fake_since.pop(cid)
                for cid in list(dead_since):
                    if w.by_id[cid]["status"] != 1:
                        dead_since.pop(cid)
                good = eligible_good(pool)
                serving = [c for c in act if w.merchant[c["id"]].alive]
                if not serving and good:
                    stats["dark_ticks"] += 1
                    dark_since.setdefault(pool, t)
                    if t - dark_since[pool] > 3:
                        viol("I6", f"{pool} dark {t - dark_since[pool]} ticks with good standby "
                                   f"{', '.join(c['name'] for c in good)}")
                        if os.environ.get("SIM_DEBUG") and debug_buf is not None:
                            print(f"--- DEBUG seed {seed} tick {t} {pool}")
                            for c in w.channels:
                                if w.pool_of(c) == pool:
                                    mer = w.merchant[c["id"]]
                                    print(f"  {c['name']} status={c['status']} alive={mer.alive} "
                                          f"genuine={mer.genuine} listed={mer.listed} lat={mer.latency} "
                                          f"margin={mer.margin:.2f} state={ {k: v for k, v in (state.get(c['name']) or {}).items() if k in ('quarantined', 'permanent', 'promoted_at')} } "
                                          f"health={(state.get('_standby_health') or {}).get(c['name'])}")
                            print(f"  refill={state.get('_refill', {}).get(pool)} "
                                  f"bad={(state.get('bad_standbys') or {}).get(pool)}")
                            stem = pool.replace("claude-", "").replace("gpt-", "")
                            for line in [x for x in debug_buf if stem in x][-25:]:
                                print("   log:", line)
                        dark_since[pool] = t
                else:
                    dark_since.pop(pool, None)
                if act and len(act) < target and len(good) >= target - len(act):
                    stats["short_ticks"] += 1
                    short_since.setdefault(pool, t)
                    if t - short_since[pool] > 14:
                        viol("I7", f"{pool} at {len(act)}/{target} for {t - short_since[pool]} ticks "
                                   f"with good standby {', '.join(c['name'] for c in good)}; "
                                   f"refill={state.get('_refill', {}).get(pool)}")
                        short_since[pool] = t
                else:
                    short_since.pop(pool, None)
        stats["cc_calls"] = w.cc_calls
    finally:
        m.time, m.A6Market.search, m.discord_alert = orig["time"], orig["search"], orig["alert"]
        m.datetime = real_dt
        m.save_state, m.RUNTIME = orig["save"], orig["runtime"]
        m.LOG.removeHandler(cap)
        if dbg is not None:
            m.LOG.removeHandler(dbg)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return violations, stats


def main():
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 288 * 2
    logging.basicConfig(level=logging.CRITICAL)
    all_v = []
    for phase, faults in (("A (no faults)", False), ("B (injected faults)", True)):
        tot = {}
        pv = []
        for s in range(seeds):
            v, st = run_seed(1000 * (2 if faults else 1) + s, ticks, faults)
            pv.extend(v)
            for k, x in st.items():
                tot[k] = tot.get(k, 0) + x
        days = seeds * ticks * TICK / 86400
        print(f"phase {phase}: {seeds} seeds x {ticks} ticks ({days:.0f} simulated days) "
              f"-> {len(pv)} violation(s); {tot}")
        for line in pv[:25]:
            print("  ", line)
        all_v.extend(pv)
    raise SystemExit(1 if all_v else 0)


if __name__ == "__main__":
    main()
