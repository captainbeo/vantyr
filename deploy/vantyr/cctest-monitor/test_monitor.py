"""Dry-run policy tests for monitor.py — no network, mocked gateway/cctest.

Run: python test_monitor.py
"""
import importlib.util
import os
import time

spec = importlib.util.spec_from_file_location("monitor", os.path.join(os.path.dirname(__file__), "monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.STATE_PATH = os.path.join(os.environ.get("TEMP", "."), "state_test.json")

CHANNELS = [
    {"id": 1, "name": "selora-default-primary", "status": 1, "group": "default",
     "models": "claude-fable-5-1,gpt-6-astra,glm-5.3"},
    {"id": 2, "name": "a6-default-primary", "status": 1, "group": "default",
     "models": "claude-fable-5-1,gpt-6-astra"},
    {"id": 3, "name": "selora-default-fallback", "status": 1, "group": "default",
     "models": "claude-fable-5-1"},
    {"id": 4, "name": "selora-unlimited", "status": 1, "group": "unlimited",
     "models": "claude-fable-5-1,claude-sonnet-5-5"},
    {"id": 5, "name": "a6-default-fallback", "status": 1, "group": "default",
     "models": "gpt-6-astra"},
    {"id": 6, "name": "a6-unlimited", "status": 1, "group": "unlimited",
     "models": "claude-fable-5-1"},
    {"id": 7, "name": "mia-failover", "status": 1, "group": "default,unlimited",
     "models": "claude-fable-5-1,claude-opus-5-5,claude-sonnet-5"},
    {"id": 8, "name": "yingz-default", "status": 1, "group": "default",
     "models": "claude-opus-5,claude-sonnet-5,gpt-6-sol"},
]


class FakeGW:
    def __init__(self, channels):
        self.channels = channels
        self.writes = []
        self.model_edits = []

    def list_channels(self):
        # Deep-copy per call, matching the real Gateway client (which parses
        # fresh dicts from each HTTP response). Returning self.channels by
        # reference would mask snapshot-staleness bugs: a mid-cycle set_status
        # would be visible to a stale "snapshot" that should not see it.
        import copy
        return copy.deepcopy(self.channels)

    def model_used_recently(self, cid, model, hours):
        return True

    def set_status(self, cid, status):
        for ch in self.channels:
            if ch["id"] == cid:
                ch["status"] = status
        self.writes.append((cid, status))
        return True

    def fix_abilities(self):
        return True

    def update_channel_models(self, cid, models):
        # Track that the PUT body carries ONLY id + models (key safety).
        self.model_edits.append((cid, models))
        for ch in self.channels:
            if ch["id"] == cid:
                ch["models"] = models
        return True

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        # No traffic in the fake gateway — never sick.
        return 0


class VerdictCC:
    verdict = "unofficial"

    @staticmethod
    def check(b, k, mo):
        return {"verdict": VerdictCC.verdict, "responseModel": mo}

    @staticmethod
    def verdict_category(r):
        return r["verdict"]


def threshold_for(name):
    if name.startswith("selora"):
        return 1
    if name.startswith("a6") or name.startswith("mia"):
        return 2
    return 3


def run(sellers, enforce, state, cc=None, gw=None):
    gateway = gw or FakeGW([dict(c) for c in CHANNELS])
    m.run_cycle(gateway, cc or VerdictCC(), sellers, ("claude", "gpt"), 168,
                threshold_for, 3, enforce, None, state)
    return gateway


def test_parse():
    good = m.parse_seller_channels(
        "selora|https://api.selora.lol|sk-abc , a6|https://api.a6api.com|sk-xyz",
        known_prefixes=("selora", "a6"))
    assert good == [("selora", "https://api.selora.lol", "sk-abc"),
                    ("a6", "https://api.a6api.com", "sk-xyz")], good
    mia = m.parse_seller_channels(
        "mia|https://miarouter.online|sk-mia",
        known_prefixes=("selora", "a6", "mia"))
    assert mia == [("mia", "https://miarouter.online", "sk-mia")], mia
    assert m.parse_seller_channels("foo|https://x|k", known_prefixes=("selora", "a6", "mia")) == []
    assert m.CCTest.verdict_category({"verdict": "Not_Claude"}) == "not_claude"


def test_provider_for():
    assert m.provider_for("claude-fable-5-1") == "claude"
    assert m.provider_for("gpt-6-astra") == "codex"
    assert m.provider_for("GPT-6-Astra") == "codex"


def test_state_roundtrip():
    m.save_state({"selora-default-primary": {"fails": 1}})
    assert m.load_state() == {"selora-default-primary": {"fails": 1}}
    os.remove(m.STATE_PATH)


def test_expand_six_channels():
    # One selora seller entry expands to the 3 selora-* channels.
    state = {}
    gw = run([("selora", "https://x", "sk")], True, state, cc=VerdictCC())
    tested = [n for n in state if "selora" in n]
    assert tested == ["selora-default-primary", "selora-default-fallback", "selora-unlimited"], tested


def test_enforce_quarantine():
    # Quarantine is now escalation-only: triggered when the bad model is
    # the channel's only entry (no model to remove → failover impossible).
    chs = [dict(c) for c in CHANNELS]
    chs[2]["models"] = "claude-fable-5-1"  # fallback has ONLY the bad model
    state = {}
    gw = FakeGW(chs)
    m.run_cycle(gw, VerdictCC(), [("selora", "https://x", "sk")], ("claude", "gpt"), 168,
                threshold_for, 3, True, None, state)
    # selora-default-fallback (ch3) has only the bad model → quarantined.
    assert (3, 2) in gw.writes, gw.writes
    assert state["selora-default-fallback"]["quarantined"] is True
    # primary + unlimited had other models → model REMOVED instead.
    assert any(cid == 1 and "claude-fable-5-1" not in models for cid, models in gw.model_edits), gw.model_edits
    assert state["selora-default-primary"]["removed_models"]["claude-fable-5-1"]["verdict"] == "unofficial"


def test_a6_threshold():
    # One bad verdict on a6: no quarantine (threshold 2), fails=1.
    state = {}
    gw = run([("a6", "https://x", "sk")], True, state)
    a6_names = [n for n in state if n.startswith("a6")]
    assert gw.writes == [], gw.writes
    assert all(state[n]["fails"] == 1 for n in a6_names), state


def test_mia_threshold():
    # One bad verdict on mia: no quarantine (threshold 2), fails=1.
    state = {}
    gw = run([("mia", "https://x", "sk")], True, state)
    mia_names = [n for n in state if n.startswith("mia")]
    assert mia_names == ["mia-failover"], mia_names
    assert gw.writes == [], gw.writes
    assert all(state[n]["fails"] == 1 for n in mia_names), state


def test_yingz_parse():
    # yingz is an accepted SELLER_CHANNELS prefix alongside selora/a6/mia.
    good = m.parse_seller_channels(
        "yingz|https://api.yingzbot.com|sk-abc",
        known_prefixes=("selora", "a6", "mia", "yingz"))
    assert good == [("yingz", "https://api.yingzbot.com", "sk-abc")]
    bad = m.parse_seller_channels(
        "yingz|https://api.yingzbot.com|sk-abc",
        known_prefixes=("selora", "a6", "mia"))
    assert bad == []


def test_kiro_parse():
    # kiro is an accepted SELLER_CHANNELS prefix (the kiro-proxy sidecar pool).
    good = m.parse_seller_channels(
        "kiro|https://vantyr.xyz|sk-abc",
        known_prefixes=("selora", "a6", "a6pin", "mia", "yingz", "kiro"))
    assert good == [("kiro", "https://vantyr.xyz", "sk-abc")]
    bad = m.parse_seller_channels(
        "kiro|https://vantyr.xyz|sk-abc",
        known_prefixes=("selora", "a6", "a6pin", "mia", "yingz"))
    assert bad == []


PIN_CHANNELS = [
    # active pin quarantined by us (status 2) + two standbys (status 2)
    {"id": 20, "name": "a6pin-fable-5", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
    {"id": 21, "name": "a6pin-fable-5-1169", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
    {"id": 22, "name": "a6pin-fable-5-3825", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
]


import contextlib


@contextlib.contextmanager
def hermetic_market(health=None):
    """Patch A6Market.health_for for deterministic promote ordering.

    promote_next_standby ranks standbys by LIVE A6 marketplace telemetry
    (commit f06d2a29c). Without this patch, tests hit the real A6 API and
    the winner depends on today's live prices (observed 2026-10-24: live
    3825 price 72000 < 1169's 156000 → 3825 promoted, tests asserting
    channel-id order fail — and would flip back whenever the market moves).

    Default (health=None): every merchant equally healthy and equally
    priced, so the sort is stable and the pre-ranking channel order wins —
    matching the historical test expectations (1169 before 3825).
    """
    if health is None:
        def health(model, our_merchant_ids):
            return {
                str(x): {"healthy": True, "success_rate": 10000,
                         "sample_count": 100, "available": True,
                         "unlisted": False, "price_micros": 1,
                         "supplier": "test"}
                for x in our_merchant_ids
            }
    original = m.A6Market.health_for
    m.A6Market.health_for = lambda self, model, ids: health(model, ids)
    try:
        yield
    finally:
        m.A6Market.health_for = original


def test_pinned_fake_promotes_tested_standby():
    # Enable-first semantics: the standby is enabled, then verified; a
    # fake verification demotes it and marks it bad. The fake active pin
    # is never re-tested (deterministic, balance conservation).
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {}
    gw = FakeGW(chs)
    # active pin quarantined by us with its failing model recorded
    state["a6pin-fable-5"] = {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5",
    }
    with hermetic_market():
        m.run_cycle(gw, VerdictCC(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    # standby 1169 was promoted (enabled) then verified FAKE → demoted
    # (status 2 again) and marked bad WITH a timestamp
    assert (21, 1) in gw.writes, gw.writes   # enable happened
    assert (21, 2) in gw.writes, gw.writes   # demotion after fake verdict
    marks = state.get("bad_standbys", {}).get("claude-fable-5", {})
    assert set(marks.keys()) == {"a6pin-fable-5-1169"}, marks
    assert isinstance(marks["a6pin-fable-5-1169"], float)
    assert gw.channels[1]["status"] == 2  # 1169 demoted again


def test_pinned_standby_promotion_on_pass():
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {"a6pin-fable-5": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5"}}

    class StandbyPass:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    gw = FakeGW(chs)
    with hermetic_market():
        m.run_cycle(gw, StandbyPass(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    # standby 1169 promoted and verified → stays enabled, not marked bad
    assert (21, 1) in gw.writes, gw.writes
    assert (21, 2) not in gw.writes, gw.writes
    assert gw.channels[1]["status"] == 1
    assert "a6pin-fable-5-1169" not in state.get("bad_standbys", {}).get("claude-fable-5", {})


def test_pinned_cooldown_recovery():
    # Owner observation 2026-10-19: bad merchants come back clean. A bad
    # mark older than the cooldown makes the standby eligible again —
    # but it must re-verify (enable-first) before serving. Fresh
    # standbys are preferred over expired ones.
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    # both 1169 and 3825 marked bad long ago (expired); 1169 is first in
    # channel order so it gets re-tried first
    state = {
        "a6pin-fable-5": {
            "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
            "quarantined": True, "model": "claude-fable-5",
            "last_quarantine_check": time.time() - 3 * 3600},
        "bad_standbys": {"claude-fable-5": {
            "a6pin-fable-5-1169": time.time() - 48 * 3600,
            "a6pin-fable-5-3825": time.time() - 48 * 3600,
        }},
    }

    class CleanNow:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class NoKeyA6M:
        def list_tokens(self):
            return []

        def reveal_key(self, tid):
            return None

    gw = FakeGW(chs)
    m.RUNTIME = {"a6m": NoKeyA6M()}
    try:
        with hermetic_market():
            m.run_cycle(gw, CleanNow(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                        ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
        # Quarantined pin was re-checked directly (no A6 key → skipped) and
        # stayed quarantined; no standby was promoted (the quarantined pin
        # re-check happens first, then the promote path runs for the model).
        assert state["a6pin-fable-5"]["quarantined"] is True
        # 1169 was re-tried after cooldown via the promote path — but the
        # quarantined pin's re-check came first and it stayed quarantined.
        # The model still needs an active pin: 1169 was promoted.
        assert (21, 1) in gw.writes, gw.writes
    finally:
        m.RUNTIME = None


def test_pinned_cooldown_not_expired_keeps_benched():
    # Bad marks younger than the cooldown keep merchants benched even
    # when no fresh standbys remain (alert instead).
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {
        "a6pin-fable-5": {
            "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
            "quarantined": True, "model": "claude-fable-5"},
        "bad_standbys": {"claude-fable-5": {
            "a6pin-fable-5-1169": time.time() - 3600,   # 1h ago — fresh mark
            "a6pin-fable-5-3825": time.time() - 2 * 3600,
        }},
    }
    gw = FakeGW(chs)

    class NoKeyA6M:
        def list_tokens(self):
            return []

        def reveal_key(self, tid):
            return None

    m.RUNTIME = {"a6m": NoKeyA6M()}
    try:
        m.run_cycle(gw, VerdictCC(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
        # Nothing promoted — all standbys are in cooldown
        assert (21, 1) not in gw.writes, gw.writes
        assert (22, 1) not in gw.writes, gw.writes
    finally:
        m.RUNTIME = None


def test_pinned_no_standby_alerts():
    # No standbys left: alert, no crash, nothing enabled.
    chs = [dict(c) for c in PIN_CHANNELS]
    # remove standbys
    chs = [chs[0]] + [dict(c) for c in CHANNELS]
    state = {"a6pin-fable-5": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5"}}
    gw = FakeGW(chs)
    m.run_cycle(gw, VerdictCC(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    assert gw.writes == [], gw.writes


def test_pinned_standby_checked_with_own_key():
    # Enable-first semantics (A6 client-gating forces gateway-routed
    # checks; the router only picks enabled channels): the standby is
    # enabled first, then verified with the entry's seller key (in
    # production the shared relay token — the gateway applies its own
    # pin routing). The invariant: exactly ONE check runs (the
    # verification), and the standby ends enabled on a pass.
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {"a6pin-fable-5": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5"}}
    seen_keys = []

    class KeySpy:
        @staticmethod
        def check(b, k, mo):
            seen_keys.append(k)
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    gw = FakeGW(chs)
    sellers = [
        ("a6pin-fable-5", "https://vantyr.xyz", "sk-RELAY"),
        ("a6pin-fable-5-1169", "https://vantyr.xyz", "sk-RELAY"),
        ("a6pin-fable-5-3825", "https://vantyr.xyz", "sk-RELAY"),
    ]
    with hermetic_market():
        m.run_cycle(gw, KeySpy(), sellers, ("claude", "gpt"), 168, threshold_for, 3,
                    True, None, state)
    # verification check + (benign) immediate re-verify of the promoted
    # standby's own entry later in the cycle — at most 2, never more
    assert 1 <= len(seen_keys) <= 2, seen_keys
    assert gw.channels[1]["status"] == 1
    assert (21, 1) in gw.writes, gw.writes


def test_promotion_refused_when_pre_verify_inconclusive():
    """REGRESSION GUARD (2026-10-24). do_check used to return
    (verdict, prediction) and the pre-promotion verify assigned the whole
    tuple, so an inconclusive check (None, None) was truthy, matched no
    verdict set, and every standby was promoted as "PASSED pre-promotion
    verification". Live: a6pin-opus-5-5-4756 was re-promoted onto
    traffic failing 96% while the healthy pin was rotated away.

    Invariant: with the pin key available (a direct check IS possible), a
    standby is enabled ONLY on an explicit PASS verdict. Inconclusive and
    bad verdicts both refuse the promotion.
    """
    class NoVerdictCC:
        @staticmethod
        def check(b, k, mo):
            return None            # cctest unreachable / no answer

        @staticmethod
        def verdict_category(r):
            return None

    class FakeA6MWithKey:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 1169"}]

        def reveal_key(self, tid):
            return "sk-test-key"

    # Inconclusive direct check (key lacks the model / cctest unreachable)
    # must NOT be refused and must NOT be claimed as "pre-verified PASSED":
    # it falls back to the gateway-routed enable-then-verify path. The pin
    # is enabled, then verified through the real route, and demoted on a bad
    # gateway verdict.
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {"a6pin-fable-5": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5"}}
    gw = FakeGW(chs)
    m.RUNTIME = {"a6m": FakeA6MWithKey()}
    try:
        with hermetic_market():
            m.run_cycle(gw, NoVerdictCC(), [("a6pin", "https://api.a6api.com", "sk-pin")],
                        ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    finally:
        m.RUNTIME = None
    # Enabled (fallback). The gateway-routed verify also returned None
    # (inconclusive — not a pass, not a fail), so the pin STAYS enabled
    # pending the next cycle's re-check; it was NOT demoted, but critically
    # it was also NOT marked as a verified pass. This is the fail-open path
    # that keeps a model from going dark when the direct key can't check it.
    assert (21, 1) in gw.writes, gw.writes
    assert gw.channels[1]["status"] == 1, gw.channels[1]
    # and it must NOT be recorded as a genuine pass
    entry = (state.get("a6pin-fable-5-1169", {}).get("last_verdicts", {})
             .get("claude-fable-5", {}))
    assert entry.get("verdict") != "official", entry


def test_do_check_returns_verdict_not_tuple():
    """do_check must return a single value. Returning a tuple is what let a
    caller treat (None, None) as a truthy pass and promote an unverified
    merchant (2026-10-24)."""
    class CC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    out = m.do_check(CC(), "https://x", "sk", "claude-opus-5-5")
    assert not isinstance(out, tuple), out
    assert out == "official", out

    class NoneCC:
        @staticmethod
        def check(b, k, mo):
            return None

        @staticmethod
        def verdict_category(r):
            return None

    out = m.do_check(NoneCC(), "https://x", "sk", "claude-opus-5-5")
    assert not isinstance(out, tuple), out
    assert out is None, out


def test_pinned_standby_model_membership_not_prefix():
    # sonnet-5 and sonnet-5-5 are different models: a sonnet-5 standby set
    # must not include sonnet-5-5 pins (name-prefix collision).
    chs = [
        {"id": 30, "name": "a6pin-sonnet-5", "status": 2, "group": "default",
         "models": "claude-sonnet-5", "model_mapping": ""},
        {"id": 31, "name": "a6pin-sonnet-5-1204", "status": 2, "group": "default",
         "models": "claude-sonnet-5", "model_mapping": ""},
        {"id": 32, "name": "a6pin-sonnet-5-5-1204", "status": 2, "group": "default",
         "models": "claude-sonnet-5-5", "model_mapping": ""},
    ]
    # failed active = a6pin-sonnet-5-5 quarantined for claude-sonnet-5-5
    state = {"a6pin-sonnet-5-5-1204": {
        "rotation": ["claude-sonnet-5-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-sonnet-5-5"}}

    class FailAll:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "not_claude"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    # run with the sonnet-5-5 entry: its standby search must consider ONLY
    # claude-sonnet-5-5 pins (none here beyond the failed one) — the
    # sonnet-5 standby must NOT be tested or marked bad.
    gw = FakeGW(chs)
    m.run_cycle(gw, FailAll(), [("a6pin-sonnet-5-5-1204", "https://api.a6api.com", "k")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    bad = state.get("bad_standbys", {})
    # sonnet-5's pin name must never appear in sonnet-5-5's bad list
    assert "a6pin-sonnet-5-1204" not in bad.get("claude-sonnet-5-5", []), bad
    assert bad.get("claude-sonnet-5-5", []) == [], bad  # no other 5-5 standby exists


def test_a6pin_pinned_key_support():
    # Pinned A6 keys (one merchant+model per key): accepted prefix, exact
    # channel-name expansion (a6pin-fable-5 must NOT also match
    # a6pin-fable-5-1), and deterministic threshold 1.
    good = m.parse_seller_channels(
        "a6pin-fable-5|https://api.a6api.com|sk-pin",
        known_prefixes=("selora", "a6", "a6pin", "mia", "yingz"))
    assert good == [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")]

    channels = [
        {"name": "a6pin-fable-5"}, {"name": "a6-default-primary"},
        {"name": "a6pin-fable-5-1"},
    ]
    matched = m.expand_seller_to_channels(channels, "a6pin-fable-5", "u", "k")
    assert [c["name"] for c in matched] == ["a6pin-fable-5"], matched

    prefixes = (("a6pin", 1), ("selora", 1), ("a6", 2), ("mia", 2), ("yingz", 2))
    def threshold_for(name):
        for prefix, t in prefixes:
            if name.startswith(prefix):
                return t
        return 3
    assert threshold_for("a6pin-fable-5") == 1
    assert threshold_for("a6pin-fable-5-1") == 1
    assert threshold_for("a6-default-primary") == 2

    # production regression: main()'s known_prefixes includes a6pin
    import re
    src = open(os.path.join(os.path.dirname(__file__), "monitor.py"), encoding="utf-8").read()
    match = re.search(r'known_prefixes=\(("[^"]+"(?:,\s*"[^"]+")*)\)', src)
    assert match, "known_prefixes tuple not found"
    prefixes_in_src = tuple(p.strip() for p in match.group(1).replace('"', "").split(","))
    assert "a6pin" in prefixes_in_src, prefixes_in_src
    assert re.search(r'\("a6pin",\s*max\(1,\s*int\(os\.environ\.get\("FAIL_THRESHOLD_A6PIN",\s*"2"\)\)\)\)', src), \
        "a6pin threshold entry missing"


def test_yingz_in_production_prefixes():
    # main()'s own known_prefixes tuple must include yingz — the test in
    # test_yingz_parse passes prefixes explicitly, so it cannot catch a
    # production regression on its own. Parse main()'s source to extract
    # the literal tuple.
    import re
    src = open(os.path.join(os.path.dirname(__file__), "monitor.py"), encoding="utf-8").read()
    match = re.search(r'known_prefixes=\(("[^"]+"(?:,\s*"[^"]+")*)\)', src)
    assert match, "known_prefixes tuple not found in monitor.py source"
    prefixes = tuple(p.strip() for p in match.group(1).replace('"', "").split(","))
    assert "yingz" in prefixes, prefixes
    assert set(("selora", "a6", "mia")).issubset(prefixes), prefixes


def test_yingz_threshold_env_default():
    # The production threshold table must map yingz to a configurable
    # FAIL_THRESHOLD_YINGZ defaulting to 2 (not fall through to
    # permanent_fails), and env must override it.
    import re
    src = open(os.path.join(os.path.dirname(__file__), "monitor.py"), encoding="utf-8").read()
    assert re.search(r'\("yingz",\s*max\(1,\s*int\(os\.environ\.get\("FAIL_THRESHOLD_YINGZ",\s*"2"\)\)\)\)', src), \
        "yingz threshold entry missing from fail_threshold_prefixes"
    # Build the production table with a temp env and exercise it.
    table = []
    for prefix, env in (("selora", "FAIL_THRESHOLD_SELORA"), ("a6", "FAIL_THRESHOLD_A6"),
                        ("mia", "FAIL_THRESHOLD_MIA"), ("yingz", "FAIL_THRESHOLD_YINGZ")):
        table.append((prefix, max(1, int(os.environ.get(env, "2")))))
    # default 2 for every non-selora seller
    assert ("yingz", 2) in table
    assert dict(table)["yingz"] == 2


def test_yingz_threshold():
    # One bad verdict on yingz: no quarantine (threshold 2), fails=1 —
    # same noise tolerance as a6/mia until live verdicts say otherwise.
    state = {}
    gw = run([("yingz", "https://x", "sk")], True, state)
    yingz_names = [n for n in state if n.startswith("yingz")]
    assert yingz_names == ["yingz-default"], yingz_names
    assert gw.writes == [], gw.writes
    assert all(state[n]["fails"] == 1 for n in yingz_names), state


def test_traffic_gate_skips():
    class GateGW(FakeGW):
        def model_used_recently(self, cid, model, hours):
            return False

    state = {}
    gw = run([("selora", "https://x", "sk")], True, state, cc=NoneCC(), gw=GateGW(CHANNELS))
    assert gw.writes == [] and all(s.get("fails", 0) == 0 for s in state.values())


def test_observe_only_counts():
    state = {}
    gw = run([("selora", "https://x", "sk")], False, state)
    assert gw.writes == [] and state["selora-default-primary"]["fails"] == 1


def test_owner_override():
    # Our state says quarantined; gateway shows enabled (owner re-enabled).
    state = {"selora-default-primary": {"rotation": [], "idx": 0, "fails": 3,
                                        "quarantined": True, "model": "x"}}
    gw = run([("selora", "https://x", "sk")], False, state, cc=PassCC())
    assert state["selora-default-primary"]["quarantined"] is False


class PassCC:
    @staticmethod
    def check(b, k, mo):
        return {"verdict": "official"}

    @staticmethod
    def verdict_category(r):
        return r["verdict"]


class NoneCheck:
    @staticmethod
    def check(b, k, mo):
        return None

    @staticmethod
    def verdict_category(r):
        return None


class NoneCC(NoneCheck):
    @staticmethod
    def check(b, k, mo):
        return None

    @staticmethod
    def verdict_category(r):
        return None


class FailCC(VerdictCC):
    verdict = "not_claude"


def test_model_removal_key_safety():
    # The update_channel_models request must carry ONLY id + models —
    # never a key (which would overwrite or blank the channel key).
    class SpyGW(FakeGW):
        def __init__(self, channels):
            super().__init__(channels)
            self.put_bodies = []

        def update_channel_models(self, cid, models):
            self.put_bodies.append({"id": cid, "models": ",".join(models)})
            return True

    # run a real failover through the code path
    chs = [dict(c) for c in CHANNELS]
    gw = SpyGW(chs)
    state = {}
    m.run_cycle(gw, VerdictCC(), [("selora", "https://x", "sk")], ("claude", "gpt"), 168,
                threshold_for, 3, True, None, state)
    assert all(set(b.keys()) == {"id", "models"} for b in gw.put_bodies), gw.put_bodies
    assert all("key" not in b and "base_url" not in b for b in gw.put_bodies)


def test_coverage_gate_blocks_last_provider():
    # If removing the model would leave NO enabled channel serving it in
    # the group, removal is blocked and an alert is sent instead.
    class OnlyGptBad:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "not_claude" if mo == "gpt-6-astra" else "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    chs = [dict(c) for c in CHANNELS]
    # ch1 (selora-default-primary, group default) is the ONLY default-group
    # channel serving gpt-6-astra once ch2/ch3/ch5 drop it.
    chs[0]["models"] = "gpt-6-astra,claude-sonnet-5-5"
    chs[1]["models"] = "claude-fable-5-1"   # a6-default-primary drops gpt-6-astra
    chs[2]["models"] = "claude-fable-5-1,claude-sonnet-5-5"  # fallback drops it
    chs[4]["models"] = "claude-fable-5-1"   # a6-default-fallback drops it
    state = {}
    gw = FakeGW(chs)
    m.run_cycle(gw, OnlyGptBad(), [("selora", "https://x", "sk")], ("claude", "gpt"), 168,
                threshold_for, 3, True, None, state)
    ch1 = gw.channels[0]
    assert "gpt-6-astra" in ch1["models"], ch1["models"]
    assert gw.writes == [], gw.writes  # no status flip, no model edit
    assert not gw.model_edits, gw.model_edits


def test_removed_model_recovers():
    # After a model is removed, a passing re-test re-adds it.
    chs = [dict(c) for c in CHANNELS]
    chs[0]["models"] = "gpt-6-astra,glm-5.3"  # fable-5-1 was removed earlier
    state = {"selora-default-primary": {
        "rotation": ["gpt-6-astra", "glm-5.3"], "idx": 0,
        "fails": 0, "removed_models": {
            "claude-fable-5-1": {"verdict": "unofficial", "removed_at": "2026-10-13T00:00:00"}}}}
    gw = FakeGW(chs)
    m.run_cycle(gw, PassCC(), [("selora", "https://x", "sk")], ("claude", "gpt"), 168,
                threshold_for, 3, True, None, state)
    st = state["selora-default-primary"]
    assert "claude-fable-5-1" not in st["removed_models"], st
    assert any("claude-fable-5-1" in models for _, models in gw.model_edits), gw.model_edits


def test_last_verdicts_recorded():
    # Every verdict flowing through process_verdict is persisted per
    # (channel, model) for the Model Routing page.
    state = {}
    gw = run([("selora", "https://x", "sk")], True, state, cc=VerdictCC())
    st = state["selora-default-primary"]
    entry = st["last_verdicts"]["claude-fable-5-1"]
    assert entry["verdict"] == "unofficial", entry
    assert "T" in entry["at"], entry  # ISO 8601
    assert "_meta" in state and "last_cycle_at" in state["_meta"]


def test_last_verdicts_inconclusive():
    class NoneCC:
        @staticmethod
        def check(b, k, mo):
            return {}

        @staticmethod
        def verdict_category(r):
            return None

    state = {}
    run([("selora", "https://x", "sk")], True, state, cc=NoneCC())
    entry = state["selora-default-primary"]["last_verdicts"]["claude-fable-5-1"]
    assert entry["verdict"] == "inconclusive", entry


def test_quarantined_pin_rechecked_and_released():
    # A quarantined (non-permanent) pin is direct-checked against its own A6
    # key every 2h; a passing verdict releases it back to standby (not
    # active — another pin serves by now).
    chs = [
        {"id": 20, "name": "a6pin-fable-5-4665", "status": 2, "group": "default",
         "models": "claude-fable-5", "model_mapping": ""},
        {"id": 21, "name": "a6pin-fable-5-3825", "status": 1, "group": "default",
         "models": "claude-fable-5", "model_mapping": ""},
    ]
    state = {"a6pin-fable-5-4665": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5",
        "last_quarantine_check": 0,  # long ago — due for re-check
    }}
    gw = FakeGW(chs)

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class FakeA6MWithKey:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 4665"}]

        def reveal_key(self, tid):
            return "sk-test-key"

    m.RUNTIME = {"a6m": FakeA6MWithKey()}
    try:
        m.run_cycle(gw, PassCC(), [("a6pin", "https://api.a6api.com", "sk-pin")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
        # The quarantined pin was re-checked directly and released (state cleared).
        assert state["a6pin-fable-5-4665"]["quarantined"] is False
        # The pin's own verdict history records the passing re-check.
        entry = state["a6pin-fable-5-4665"]["last_verdicts"]["claude-fable-5"]
        assert entry["verdict"] == "official", entry
        # Release NEVER enables the channel (owner spec 2026-10-24: verify
        # only checks trueness + lifts the quarantine; pinning happens only
        # via "Use this merchant"). The pin stays benched (status 2) and
        # NO status writes occur.
        assert (20, 1) not in gw.writes, gw.writes
        assert (20, 2) not in gw.writes, gw.writes
    finally:
        m.RUNTIME = None


def test_sole_quarantined_pin_still_rechecked():
    # Single-pin model whose pin is quarantined (fake verdict or sick
    # rotation), no other standby exists. The no-active-pin branch must NOT
    # early-return after the (no-op) promote attempt — the pin's scheduled
    # re-check must still run, so a recovered merchant gets re-tested and
    # auto-released (owner then recovers the model with one "Use this
    # merchant" click).
    chs = [{"id": 20, "name": "a6pin-fable-5-4665", "status": 2,
            "group": "default", "models": "claude-fable-5", "model_mapping": ""}]
    state = {"a6pin-fable-5-4665": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5",
        "last_quarantine_check": 0,  # long ago — due for re-check
    }}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class FakeA6MWithKey:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 4665"}]

        def reveal_key(self, tid):
            return "sk-test-key"

    gw = FakeGW(chs)
    m.RUNTIME = {"a6m": FakeA6MWithKey()}
    try:
        m.run_cycle(gw, PassCC(), [("a6pin", "https://api.a6api.com", "sk-pin")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
        # The re-check ran (verdict recorded) and the pass released the
        # quarantine — recovery is possible via one promote click.
        entry = state["a6pin-fable-5-4665"]["last_verdicts"]["claude-fable-5"]
        assert entry["verdict"] == "official", entry
        assert state["a6pin-fable-5-4665"]["quarantined"] is False
        # Release never enables (owner spec); nothing was pinned.
        assert (20, 1) not in gw.writes, gw.writes
    finally:
        m.RUNTIME = None


def test_verdict_history_capped_newest_first():
    # record_verdict keeps the last HISTORY_DEPTH checks per (channel,
    # model), newest first, and mirrors the newest into last_verdicts.
    st = {}
    for v in ["official", "unofficial", "attr_match", "official"]:
        m.record_verdict(st, "claude-fable-5", v)
    hist = st["verdict_history"]["claude-fable-5"]
    assert len(hist) == m.HISTORY_DEPTH, hist
    assert [e["verdict"] for e in hist] == ["official", "attr_match", "unofficial"]
    # newest mirrors into last_verdicts
    assert st["last_verdicts"]["claude-fable-5"]["verdict"] == "official"
    for e in hist:
        assert "T" in e["at"], e  # ISO 8601


def test_verdict_history_inconclusive_recorded():
    # A None verdict (failed/blocked check) is recorded as inconclusive in
    # history too, so the page shows that a check happened.
    st = {}
    m.record_verdict(st, "gpt-6-sol", None)
    hist = st["verdict_history"]["gpt-6-sol"]
    assert hist[0]["verdict"] == "inconclusive"
    assert st["last_verdicts"]["gpt-6-sol"]["verdict"] == "inconclusive"


def test_status_payload_includes_history():
    state = {
        "a6pin-x-1": {
            "rotation": ["claude-fable-5"],
            "last_verdicts": {"claude-fable-5": {"verdict": "official", "at": "2026-10-19T00:00:00"}},
            "verdict_history": {"claude-fable-5": [
                {"verdict": "official", "at": "2026-10-19T00:00:00"},
                {"verdict": "unofficial", "at": "2026-10-18T00:00:00"},
            ]},
        },
        "_meta": {"last_cycle_at": "2026-10-19T00:10:00"},
    }
    payload = m.status_payload(state, {"enforce": True, "cycle_minutes": 60,
                                       "standby_cooldown_hours": 3,
                                       "permanent_fails": 3,
                                       "thresholds": {}})
    ch = payload["channels"]["a6pin-x-1"]
    assert "verdict_history" in ch, ch
    assert len(ch["verdict_history"]["claude-fable-5"]) == 2


def test_status_payload_projection():
    state = {
        "selora-default-primary": {"fails": 1, "last_verdicts": {"claude-fable-5-1": {"verdict": "official", "at": "2026-10-19T00:00:00"}}},
        "bad_standbys": {"claude-fable-5": {"a6pin-fable-5-1169": 1.0}},
        "_meta": {"last_cycle_at": "2026-10-19T00:10:00"},
    }
    payload = m.status_payload(state, {"enforce": True, "cycle_minutes": 60,
                                       "standby_cooldown_hours": 3,
                                       "permanent_fails": 3,
                                       "thresholds": {}})
    assert set(payload["channels"].keys()) == {"selora-default-primary"}, payload
    assert payload["bad_standbys"]["claude-fable-5"]["a6pin-fable-5-1169"] == 1.0
    assert payload["last_cycle_at"] == "2026-10-19T00:10:00"
    assert payload["enforce"] is True
    # empty state (fresh/parked) degrades cleanly
    empty = m.status_payload({}, m.read_display_config())
    assert empty["channels"] == {}
    assert empty["last_cycle_at"] is None


def test_status_server_auth():
    # Auth matrix against a stub gateway on an ephemeral port:
    # no header -> 401, low role -> 403, admin -> 200, dead gateway -> 503.
    import json as _json
    import threading as _threading
    import urllib.error as _ure
    import urllib.request as _ur
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class StubGW(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            token = (self.headers.get("Authorization") or "").split("Bearer ")[-1]
            role = 10 if token == "admin-token" else 1
            body = _json.dumps({"success": True, "data": {"role": role}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    gw = ThreadingHTTPServer(("127.0.0.1", 0), StubGW)
    _threading.Thread(target=gw.serve_forever, daemon=True).start()
    stub = m.ThreadingHTTPServer(("127.0.0.1", 0), m.StatusHandler)
    _threading.Thread(target=stub.serve_forever, daemon=True).start()

    old = {k: os.environ.get(k) for k in ("GATEWAY_URL", "STATE_PATH")}
    try:
        os.environ["GATEWAY_URL"] = f"http://127.0.0.1:{gw.server_address[1]}"
        os.environ["STATE_PATH"] = m.STATE_PATH
        m.save_state({"_meta": {"last_cycle_at": "2026-10-19T00:00:00"}})

        def hit(path, token=None):
            req = _ur.Request(f"http://127.0.0.1:{stub.server_address[1]}{path}")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            try:
                with _ur.urlopen(req, timeout=10) as resp:
                    return resp.status, _json.loads(resp.read().decode())
            except _ure.HTTPError as e:
                return e.code, {}

        # no token -> 401
        s, _ = hit("/api/cctest/status")
        assert s == 401, s
        # non-admin -> 403
        s, _ = hit("/api/cctest/status", "user-token")
        assert s == 403, s
        # admin -> 200 + payload
        s, payload = hit("/api/cctest/status", "admin-token")
        assert s == 200, s
        assert payload["data"]["last_cycle_at"] == "2026-10-19T00:00:00"
        # unauthenticated debug endpoint serves the same payload
        s, _ = hit("/status")
        assert s == 200, s
        # dead gateway -> 503
        os.environ["GATEWAY_URL"] = "http://127.0.0.1:9"
        s, _ = hit("/api/cctest/status", "admin-token")
        assert s == 503, s
        # unknown path -> 404
        os.environ["GATEWAY_URL"] = "unused"
        s, _ = hit("/nope", "admin-token")
        assert s == 404, s
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        gw.shutdown()
        stub.shutdown()


def test_action_verify():
    # POST verify runs the cycle path on demand and records the verdict.
    chs = [dict(c) for c in CHANNELS]
    state = {}
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": VerdictCC(),
        "sellers": [("selora", "https://x", "sk")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        status, payload = m.run_action_verify({"channel": "selora-default-primary", "model": "claude-fable-5-1"})
        assert status == 200, payload
        assert payload["data"]["verdict"] == "unofficial", payload
        entry = state["selora-default-primary"]["last_verdicts"]["claude-fable-5-1"]
        assert entry["verdict"] == "unofficial", entry
        # threshold 1 + enforce + bad verdict + covered → model removed
        # (model_edits records the REMAINING list, without the bad model)
        assert any(
            cid == 1 and "claude-fable-5-1" not in models
            for cid, models in m.RUNTIME["gateway"].model_edits
        ), m.RUNTIME["gateway"].model_edits
        assert "claude-fable-5-1" not in chs[0]["models"], chs[0]["models"]
        # unknown channel -> 404; missing body -> 400; parked -> 503
        status, _ = m.run_action_verify({"channel": "nope", "model": "x"})
        assert status == 404, status
        status, _ = m.run_action_verify({})
        assert status == 400, status
    finally:
        m.RUNTIME = None
    status, _ = m.run_action_verify({"channel": "x", "model": "y"})
    assert status == 503, status


def test_action_promote():
    # POST promote: quarantines the active pin, promotes + verifies the
    # next standby, reports the promoted name and verdict.
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1  # active pin enabled
    state = {}
    # Stub the marketplace health so the auto path has a healthy candidate.
    m.A6Market.health_for = lambda self, model, ids: {
        "1169": {"healthy": True, "success_rate": 10000, "price_micros": 1},
        "3825": {"healthy": True, "success_rate": 9000, "price_micros": 2},
    }
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": VerdictCC(),
        "sellers": [("a6pin-fable-5", "https://api.a6api.com", "sk-pin"),
                    ("a6pin-fable-5-1169", "https://api.a6api.com", "sk-1169"),
                    ("a6pin-fable-5-3825", "https://api.a6api.com", "sk-3825")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        status, payload = m.run_action_promote({"model": "claude-fable-5"})
        assert status == 200, payload
        assert payload["data"]["demoted"] == "a6pin-fable-5", payload
        # 1169 enabled first (fake verdict demotes it back; 3825 not yet
        # tried — one standby per promote call, next next cycle)
        assert (21, 1) in m.RUNTIME["gateway"].writes
        assert chs[1]["status"] == 2, chs[1]
        # active pin quarantined in state
        assert state["a6pin-fable-5"]["quarantined"] is True
        # standby verdict recorded
        entry = state["a6pin-fable-5-1169"]["last_verdicts"]["claude-fable-5"]
        assert entry["verdict"] == "unofficial", entry
        # promoted reported as None (both demoted, awaiting next cycle) or
        # a passing standby name — here the fake verdict demotes, so None
        assert payload["data"]["promoted"] is None, payload
        # observe-mode refuses
        m.RUNTIME["enforce"] = False
        status, _ = m.run_action_promote({"model": "claude-fable-5"})
        assert status == 409, status
    finally:
        m.RUNTIME = None


def test_action_promote_manual_pick():
    # POST promote {merchant}: promotes THAT specific standby, not the next
    # in channel order — the owner's manual merchant pick.
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1  # a6pin-fable-5 active; 1169 + 3825 standbys
    state = {}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    m.A6Market.health_for = lambda self, model, ids: {}
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": PassCC(),
        "sellers": [("a6pin-fable-5", "https://api.a6api.com", "sk-pin"),
                    ("a6pin-fable-5-1169", "https://api.a6api.com", "sk-1169"),
                    ("a6pin-fable-5-3825", "https://api.a6api.com", "sk-3825")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        status, payload = m.run_action_promote({"model": "claude-fable-5", "merchant": "3825"})
        assert status == 200, payload
        # 3825 specifically promoted + verified (not 1169, which is first)
        assert (22, 1) in m.RUNTIME["gateway"].writes, m.RUNTIME["gateway"].writes
        assert (21, 1) not in m.RUNTIME["gateway"].writes, m.RUNTIME["gateway"].writes
        assert payload["data"]["promoted"] == "a6pin-fable-5-3825", payload
        assert chs[2]["status"] == 1, chs[2]
        # unknown merchant refused
        m.RUNTIME["gateway"] = FakeGW([dict(c) for c in PIN_CHANNELS] + [{"id": 30, "name": "a6pin-fable-5-XXXX", "status": 2, "models": "claude-fable-5"}])
        status, payload = m.run_action_promote({"model": "claude-fable-5", "merchant": "9999"})
        assert status == 409, (status, payload)
    finally:
        m.RUNTIME = None


def test_action_promote_manual_pick_no_active_pin():
    # Regression for the 2026-10-22 gpt-6-sol bug: when the model has NO
    # active pin (all disabled), run_action_promote passes the chosen standby
    # as failed_channel — which then excluded it from the standby set, so the
    # preferred pick was "not a standby" and nothing promoted. The pick must
    # be promoted even when it is the failed_channel fallback.
    chs = [dict(c) for c in PIN_CHANNELS]
    for c in chs:
        c["status"] = 2  # NO active pin — all standby
    state = {}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    m.A6Market.health_for = lambda self, model, ids: {}
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": PassCC(),
        "sellers": [("a6pin-fable-5", "https://api.a6api.com", "sk-pin"),
                    ("a6pin-fable-5-1169", "https://api.a6api.com", "sk-1169"),
                    ("a6pin-fable-5-3825", "https://api.a6api.com", "sk-3825")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        status, payload = m.run_action_promote({"model": "claude-fable-5", "merchant": "1169"})
        assert status == 200, payload
        assert payload["data"]["promoted"] == "a6pin-fable-5-1169", payload
        assert chs[1]["status"] == 1, chs[1]  # 1169 enabled
    finally:
        m.RUNTIME = None


def test_action_promote_manual_pick_overrides_stale_mark():
    # Regression for the 2026-10-22 sonnet-5-5 incident: a manual pick of a
    # merchant that is bad-marked (even long past cooldown) must be honored
    # when fresh pins also exist. Previously fresh pins won the candidate set
    # and the marked pick was refused, while the active pin had already been
    # quarantined — leaving the model with zero serving pins.
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1  # a6pin-fable-5 active
    state = {}
    import time as _time
    # 1169 marked as bad, 70h ago (well past the 3h cooldown); 3825 is fresh.
    state["bad_standbys"] = {"claude-fable-5": {"a6pin-fable-5-1169": _time.time() - 70 * 3600}}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    m.A6Market.health_for = lambda self, model, ids: {}
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": PassCC(),
        "sellers": [("a6pin-fable-5", "https://api.a6api.com", "sk-pin"),
                    ("a6pin-fable-5-1169", "https://api.a6api.com", "sk-1169"),
                    ("a6pin-fable-5-3825", "https://api.a6api.com", "sk-3825")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        # Manual pick of the MARKED 1169 must promote it (operator override),
        # not refuse because fresh 3825 exists.
        status, payload = m.run_action_promote({"model": "claude-fable-5", "merchant": "1169"})
        assert status == 200, payload
        assert payload["data"]["promoted"] == "a6pin-fable-5-1169", payload
        assert chs[1]["status"] == 1, chs[1]  # 1169 enabled
        # the stale mark is cleared on pass
        assert "a6pin-fable-5-1169" not in state["bad_standbys"]["claude-fable-5"]
    finally:
        m.RUNTIME = None


def test_pool_prefix_expansion():
    # The bare "a6pin" seller entry covers EVERY pin channel (pool
    # auto-discovery); exact-name entries still match exactly.
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    chs.append({"id": 23, "name": "a6pin-fable-5-9999", "status": 2,
                "group": "default", "models": "claude-fable-5", "model_mapping": ""})
    pool = m.expand_seller_to_channels(chs, "a6pin", "https://vantyr.xyz", "sk-RELAY")
    names = {c["name"] for c in pool}
    assert "a6pin-fable-5" in names and "a6pin-fable-5-9999" in names, names
    # general sellers unchanged: prefix expansion, no a6pin grab
    gen = m.expand_seller_to_channels(chs, "selora", "https://x", "sk")
    assert all(c["name"].startswith("selora") for c in gen), gen
    # legacy exact-name entry: exact only
    exact = m.expand_seller_to_channels(chs, "a6pin-fable-5", "https://vantyr.xyz", "sk")
    assert [c["name"] for c in exact] == ["a6pin-fable-5"], exact


def test_parse_a6_key_name():
    sku, merchant, name = m.parse_a6_key_name("FABLE 5 | 4665")
    assert (sku, merchant, name) == ("claude-fable-5", "4665", "a6pin-fable-5-4665")
    assert m.parse_a6_key_name("Fable 5.1 | 3825") == ("claude-fable-5-1", "3825", "a6pin-fable-5-1-3825")
    # GPT stems keep their family-suffix: gpt-6-sol → a6pin-6-sol-<m>
    assert m.parse_a6_key_name("SOL | 123") == ("gpt-6-sol", "123", "a6pin-6-sol-123")
    assert m.parse_a6_key_name("6.1 SOL | 5942") == ("gpt-6-1-sol", "5942", "a6pin-6-1-sol-5942")
    assert m.parse_a6_key_name("OPUS 5.5 | 4756") == ("claude-opus-5-5", "4756", "a6pin-opus-5-5-4756")
    assert m.parse_a6_key_name("WHAT MODEL | 1") == (None, None, None)
    assert m.parse_a6_key_name("") == (None, None, None)
    assert m.parse_a6_key_name("no pipe here") == (None, None, None)


class FakeA6M:
    def __init__(self, tokens, reveals=None):
        self.tokens = tokens
        self.revealed = []
        self.reveals = reveals or {}

    def list_tokens(self):
        return self.tokens

    def reveal_key(self, token_id):
        self.revealed.append(token_id)
        if token_id not in self.reveals:
            raise RuntimeError("no key")
        return self.reveals[token_id]


class SyncGW(FakeGW):
    def __init__(self, channels):
        super().__init__(channels)
        self.created = []

    def create_channel(self, name, key, models, group, base_url, priority=20,
                       model_mapping=None):
        self.created.append({
            "name": name, "key": key, "models": models, "group": group,
            "base_url": base_url, "priority": priority,
            "model_mapping": model_mapping,
        })
        return True


def test_sync_creates_standby_pins():
    chs = [dict(c) for c in PIN_CHANNELS]  # a6pin-fable-5(-1169/-3825) exist
    gw = SyncGW(chs)
    a6m = FakeA6M(
        [
            {"id": 1, "name": "FABLE 5 | 4665"},      # new → create
            {"id": 2, "name": "OPUS 5 | 851"},        # new → create
            {"id": 3, "name": "FABLE 5 | 1169"},      # exists → skip
            {"id": 4, "name": "WEIRD NAME"},          # unmapped → skipped+noted
        ],
        reveals={1: "sk-a", 2: "sk-b"},
    )
    state = {}
    m.sync_a6_keys(gw, a6m, chs, state, None)
    created_names = [c["name"] for c in gw.created]
    assert created_names == ["a6pin-fable-5-4665", "a6pin-opus-5-851"], created_names
    body = gw.created[0]
    assert body["models"] == ["claude-fable-5"]
    assert body["model_mapping"] is None  # non-6.1-sol pins get no mapping
    assert body["group"] == "default,unlimited"
    assert body["base_url"] == "https://api.a6api.com"
    assert body["priority"] == 20
    assert state["_sync"]["created"] == created_names
    assert state["_sync"]["skipped_existing"] == 1
    assert state["_sync"]["unmatched"] == ["WEIRD NAME"]
    # idempotent: re-run with the created channels in the list → no creates
    chs2 = chs + [
        {"id": 40, "name": "a6pin-fable-5-4665", "models": "claude-fable-5"},
        {"id": 41, "name": "a6pin-opus-5-851", "models": "claude-opus-5"},
    ]
    gw2 = SyncGW(chs2)
    m.sync_a6_keys(gw2, a6m, chs2, {}, None)
    assert gw2.created == [], gw2.created


def test_sync_creates_61_sol_pin_with_both_aliases():
    # A "6.1 SOL | <merchant>" key becomes ONE pin serving both spellings
    # (gpt-6-1-sol + gpt-6.1-sol) with the upstream mapping — the unified pool.
    chs = [dict(c) for c in PIN_CHANNELS]
    gw = SyncGW(chs)
    a6m = FakeA6M([{"id": 9, "name": "6.1 SOL | 7777"}], reveals={9: "sk-x"})
    m.sync_a6_keys(gw, a6m, chs, {}, None)
    assert len(gw.created) == 1, gw.created
    body = gw.created[0]
    assert body["name"] == "a6pin-6-1-sol-7777"
    assert body["models"] == ["gpt-6-1-sol", "gpt-6.1-sol"]
    assert body["model_mapping"] == {"gpt-6-1-sol": "gpt-6.1-sol", "gpt-6.1-sol": "gpt-6.1-sol"}


def test_pin_merchant():
    # Longest-stem match: merchant-suffixed pins yield their merchant;
    # plain-named legacy pins (trailing digit is part of the model) → None.
    assert m.pin_merchant("a6pin-fable-5-4665") == "4665"
    assert m.pin_merchant("a6pin-sonnet-5") is None
    assert m.pin_merchant("a6pin-sonnet-5-5") is None
    assert m.pin_merchant("a6pin-opus-5-5") is None
    assert m.pin_merchant("a6pin-fable-5-1") is None
    assert m.pin_merchant("a6pin-fable-5-1-3825") == "3825"
    assert m.pin_merchant("a6pin-opus-5-5-3859") == "3859"
    assert m.pin_merchant("a6pin-6-1-sol-5950") == "5950"
    assert m.pin_merchant("mia-failover") is None


def test_action_verify_legacy_pin_can_release():
    # A plain-named legacy pin (no merchant) is gateway-verifiable and a
    # passing verdict releases its quarantine (2026-10-23: these pins were
    # stuck forever because only direct checks could release, and legacy
    # pins can never be direct-checked).
    chs = [{"id": 12, "name": "a6pin-sonnet-5", "status": 2,
            "models": "claude-sonnet-5", "model_mapping": ""}]

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    state = {"a6pin-sonnet-5": {"rotation": ["claude-sonnet-5"], "idx": 0,
                                  "fails": 0, "quarantined": True, "permanent": True,
                                  "model": "claude-sonnet-5"}}
    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": PassCC(),
        "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {},
    }
    try:
        status, payload = m.run_action_verify({"channel": "a6pin-sonnet-5", "model": "claude-sonnet-5"})
        assert status == 200, (status, payload)
        assert payload["data"]["verdict"] == "official", payload
        # Quarantine released but the channel is NOT enabled (owner spec
        # 2026-10-24: verify only checks trueness + lifts the quarantine;
        # pinning happens exclusively via "Use this merchant").
        assert chs[0]["status"] == 2, chs
        assert state["a6pin-sonnet-5"]["quarantined"] is False
    finally:
        m.RUNTIME = None


def test_model_pool_names_alias():
    # gpt-6-1-sol and gpt-6.1-sol share one pool; other models are singletons.
    assert m.model_pool_names("gpt-6-1-sol") == {"gpt-6-1-sol", "gpt-6.1-sol"}
    assert m.model_pool_names("gpt-6.1-sol") == {"gpt-6-1-sol", "gpt-6.1-sol"}
    assert m.model_pool_names("claude-fable-5") == {"claude-fable-5"}


def test_action_verify_unverifiable_phantom_pin():
    # A pinned merchant with NO A6 token (phantom) must NOT be verified by
    # borrowing the active pin's verdict via gateway routing — it returns an
    # honest "unverifiable" 409 instead (the 2026-10-22 phantom-5312 bug).
    chs = [{"id": 50, "name": "a6pin-6-astra-5312", "status": 2,
            "models": "gpt-6-astra", "model_mapping": "", "base_url": "https://api.a6api.com"}]

    class NoMatchA6M:
        def list_tokens(self):
            return [{"id": 1, "name": "ASTRA 6 | 5942"}]  # no 5312

        def reveal_key(self, tid):
            return "sk-other"

    m.RUNTIME = {
        "gateway": FakeGW(chs),
        "cctest": VerdictCC(),
        "sellers": [("a6pin", "https://api.a6api.com", "sk-active")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": {}, "seller_registry": {}, "a6m": NoMatchA6M(),
    }
    try:
        status, payload = m.run_action_verify({"channel": "a6pin-6-astra-5312", "model": "gpt-6-astra"})
        assert status == 409, (status, payload)
        assert payload["verdict"] == "unverifiable", payload
        assert "5312" in payload["error"], payload
        # and it did NOT record a borrowed verdict for the phantom
        assert "a6pin-6-astra-5312" not in m.RUNTIME["state"], m.RUNTIME["state"]
    finally:
        m.RUNTIME = None


def test_sync_prunes_phantom_pins():
    # A pin whose merchant has no A6 token is disabled (not deleted) and
    # recorded; plain-named legacy pins (non-digit suffix) are left alone;
    # the ACTIVE pin is never pruned (would strand the model).
    chs = [
        {"id": 60, "name": "a6pin-6-astra-5942", "status": 1, "models": "gpt-6-astra"},   # has token
        {"id": 61, "name": "a6pin-6-astra-5312", "status": 3, "models": "gpt-6-astra"},   # phantom standby (auto-disabled, not our quarantine)
        {"id": 62, "name": "a6pin-fable-5", "status": 1, "models": "claude-fable-5"},      # legacy plain name
        {"id": 63, "name": "a6pin-6-astra-2757", "status": 2, "models": "gpt-6-astra"},   # phantom but already off
        {"id": 64, "name": "a6pin-6-astra-3016", "status": 1, "models": "gpt-6-astra"},   # phantom + ACTIVE
    ]
    gw = SyncGW(chs)
    # A6 account only has merchant 5942.
    a6m = FakeA6M([{"id": 1, "name": "ASTRA 6 | 5942"}], reveals={1: "sk-x"})
    state = {}
    m.sync_a6_keys(gw, a6m, chs, state, None)
    # Phantom standby 5312 disabled; 5942 untouched; legacy a6pin-fable-5 untouched;
    # already-off 2757 untouched; ACTIVE phantom 3016 left live (never stranded).
    assert (61, 2) in gw.writes, gw.writes
    assert (60, 2) not in gw.writes, gw.writes
    assert (62, 2) not in gw.writes, gw.writes
    assert (63, 2) not in gw.writes, gw.writes
    assert (64, 2) not in gw.writes, gw.writes  # active pin never pruned
    assert state["_sync"]["pruned_phantoms"] == ["a6pin-6-astra-5312"], state["_sync"]


def test_sync_reveal_budget_and_failure():
    # reveal failure or budget (5/cycle) stops creating; never fatal
    chs = [{"id": 1, "name": "a6pin-fable-5", "models": "claude-fable-5"}]
    gw = SyncGW(chs)
    tokens = [{"id": i, "name": f"FABLE 5 | {i}"} for i in range(100, 112)]
    a6m = FakeA6M(tokens, reveals={i: f"sk-{i}" for i in range(100, 105)})
    state = {}
    m.sync_a6_keys(gw, a6m, chs, state, None)
    assert len(gw.created) == 5, len(gw.created)  # reveal budget
    # reveal failure: one bad reveal → stop for the cycle, no exception
    gw2 = SyncGW(chs)
    a6m2 = FakeA6M([{"id": 5, "name": "FABLE 5 | 555"}], reveals={})
    m.sync_a6_keys(gw2, a6m2, chs, state, None)
    assert gw2.created == []


def test_sync_a6_list_failure_is_nonfatal():
    class BrokenA6M:
        def list_tokens(self):
            raise RuntimeError("A6 down")

    chs = [dict(c) for c in PIN_CHANNELS]
    gw = SyncGW(chs)
    m.sync_a6_keys(gw, BrokenA6M(), chs, {}, None)  # must not raise
    assert gw.created == []


class SickGW(FakeGW):
    def __init__(self, channels, error_counts, success_counts):
        super().__init__(channels)
        self.error_counts = error_counts
        self.success_counts = success_counts

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        if log_type == 5:
            return self.error_counts.get(channel_id)
        return self.success_counts.get(channel_id)


class LatencyGW(SickGW):
    """Fake gateway whose consume logs carry `other` JSON with frt +
    stream_status.end_reason, and whose error logs carry `content` with a
    status code — the data pin_latency_sick scores. error_contents maps
    channel_id -> list of content strings (default: all hard 502s)."""

    def __init__(self, error_counts, success_counts, rows, error_contents=None):
        super().__init__([], error_counts, success_counts)
        self.rows = rows
        self.error_contents = error_contents or {}

    def recent_consume_logs(self, channel_id, window_minutes, limit=50):
        return self.rows

    def recent_error_logs(self, channel_id, window_minutes, limit=100):
        if channel_id not in self.error_contents:
            return [{"content": "status_code=502, 智能路由候选均请求失败。"}] * (self.error_counts.get(channel_id) or 0)
        return [{"content": c} for c in self.error_contents[channel_id]]


def _row(end_reason=None, frt=None):
    import json as _json
    ss = {"end_reason": end_reason} if end_reason else None
    # end_reason=None means a NON-STREAMING request: no stream_status key
    # at all, and frt logged as -1000 (not applicable).
    payload = {"frt": frt}
    if ss is not None:
        payload["stream_status"] = ss
    return {"other": _json.dumps(payload)}


def test_pin_latency_sick():
    cfg = {"enabled": True, "min_samples": 20, "frt_ms_threshold": 10000,
           "client_gone_ratio": 0.20, "hang_threshold": 3,
           "error_ratio_threshold": 0.05}
    # ch52 profile: ~46% client_gone, high frt → sick
    rows = [_row("client_gone", 13000)] * 9 + [_row("eof", 15000)] * 11
    gw = LatencyGW({52: 0}, {52: len(rows)}, rows)
    assert m.pin_is_sick(gw, 52, 60, latency_cfg=cfg) is True
    # healthy fleet profile: 0% gone, sub-second frt → healthy
    rows = [_row("eof", 900)] * 25
    gw = LatencyGW({9: 0}, {9: len(rows)}, rows)
    assert m.pin_is_sick(gw, 9, 60, latency_cfg=cfg) is False
    # thin traffic (< min_samples) → None, never rotate on weak evidence
    gw = LatencyGW({9: 0}, {9: 3}, [_row("eof", 900)] * 3)
    assert m.pin_is_sick(gw, 9, 60, latency_cfg=cfg) is None
    # ch40 profile: 8% gone but 11 streaming frt=-1000 hangs → sick on hangs
    rows = [_row("client_gone", -1000)] * 11 + [_row("eof", 4800)] * 127
    gw = LatencyGW({40: 0}, {40: len(rows)}, rows)
    assert m.pin_is_sick(gw, 40, 60, latency_cfg=cfg) is True
    # hangs do NOT inflate the client_gone ratio: 4 hang rows + 46 clean
    # rows → gone=4 (8% < 20%, counted once per row), hangs=4 >= 3 → sick
    # via the hang threshold, NOT via the ratio.
    rows = [_row("client_gone", -1000)] * 4 + [_row("eof", 2000)] * 46
    gw = LatencyGW({40: 0}, {40: len(rows)}, rows)
    assert m.pin_is_sick(gw, 40, 60, latency_cfg=cfg) is True  # hangs
    # ch25 profile (2026-10-22 false positive): mostly NON-STREAMING rows
    # (no stream_status, frt=-1000) which are ordinary successes — must NOT
    # count as hangs. 40 non-stream + 25 healthy stream rows → ok.
    rows = [_row(None, -1000)] * 40 + [_row("eof", 4000)] * 25
    gw = LatencyGW({25: 0}, {25: len(rows)}, rows)
    assert m.pin_is_sick(gw, 25, 60, latency_cfg=cfg) is False
    # non-stream rows alone: stream axis fails open (0 < min_samples) but
    # the error axis has 30 clean rows (0 hard errors) → healthy, not sick.
    gw = LatencyGW({25: 0}, {25: 30}, [_row(None, -1000)] * 30)
    assert m.pin_is_sick(gw, 25, 60, latency_cfg=cfg) is False
    # thin evidence on BOTH axes → None (no verdict, fail-open)
    gw = LatencyGW({25: 0}, {25: 5}, [_row(None, -1000)] * 5)
    assert m.pin_is_sick(gw, 25, 60, latency_cfg=cfg) is None
    # ch74 profile (opus-5 2026-10-23): 25 hard 502s interleaved with 465
    # successes → 5.1% HARD-error ratio trips error_sick
    rows = [_row("eof", 3000)] * 465
    gw = LatencyGW({74: 25}, {74: 465}, rows)
    assert m.pin_is_sick(gw, 74, 60, latency_cfg=cfg) is True
    # benign errors (429 / client aborts, status_code=4xx) do NOT trip:
    # 465 ok + 25 4xx errors → 5.1% total-error but 0% hard-error → ok
    gw = LatencyGW({74: 25}, {74: 465}, rows,
                   error_contents={74: ["status_code=429, rate limited"] * 25})
    assert m.pin_is_sick(gw, 74, 60, latency_cfg=cfg) is False
    # query failure on either log kind → None (fail-open)
    class FailGW(LatencyGW):
        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return None
    assert m.pin_is_sick(FailGW({9: 0}, {9: 5}, []), 9, 60, latency_cfg=cfg) is None
    class FailErrGW(LatencyGW):
        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return None
    assert m.pin_is_sick(FailErrGW({9: 5}, {9: 5}, [_row("eof", 100)] * 25), 9, 60, latency_cfg=cfg) is None
    # latency disabled → existing error/success behavior untouched
    rows = [_row("client_gone", 13000)] * 30
    gw = LatencyGW({9: 0}, {9: len(rows)}, rows)
    assert m.pin_is_sick(gw, 9, 60, latency_cfg=None) is False


def test_pin_is_sick():
    # errors>0 and successes==0 → sick
    assert m.pin_is_sick(SickGW([], {9: 3}, {9: 0}), 9, 60) is True
    # errors with some successes → healthy (degraded but serving)
    assert m.pin_is_sick(SickGW([], {9: 3}, {9: 2}), 9, 60) is False
    # no traffic at all → not sick
    assert m.pin_is_sick(SickGW([], {9: 0}, {9: 0}), 9, 60) is False
    # query failure → None (never rotate on missing evidence)
    assert m.pin_is_sick(SickGW([], {}, {9: 2}), 9, 60) is None
    assert m.pin_is_sick(SickGW([], {9: 1}, {}), 9, 60) is None


def test_promote_skips_delisted_merchant():
    # 2026-10-23 sonnet-5 outage: the cycle promoted merchant 1204, which was
    # delisted from the A6 marketplace (503 dead). promote_next_standby must
    # rank a delisted candidate last and promote the healthy one instead.
    chs = [
        {"id": 20, "name": "a6pin-fable-5", "status": 2, "models": "claude-fable-5"},
        {"id": 21, "name": "a6pin-fable-5-1169", "status": 2, "models": "claude-fable-5"},  # delisted
        {"id": 22, "name": "a6pin-fable-5-3825", "status": 2, "models": "claude-fable-5"},  # healthy
    ]
    gw = FakeGW(chs)
    state = {}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    # 1169 is unlisted (delisted from the marketplace), 3825 is healthy.
    delisted_health = {
        "1169": {"healthy": False, "success_rate": None, "available": False, "unlisted": True, "price_micros": None, "sample_count": 0, "supplier": None},
        "3825": {"healthy": True, "success_rate": 10000, "available": True, "unlisted": False, "price_micros": 1, "sample_count": 100, "supplier": "x"},
    }
    with hermetic_market(lambda model, ids: delisted_health):
        m.promote_next_standby(gw, PassCC(), chs[0], "https://api.a6api.com", "sk",
                               "claude-fable-5", True, None, state, chs, {})
    # The healthy 3825 was promoted (enabled), not the delisted 1169.
    # The context manager restores the ORIGINAL A6Market.health_for — no
    # leak into later tests.
    assert (22, 1) in gw.writes, gw.writes
    assert (21, 1) not in gw.writes, gw.writes


def test_sick_pin_rotation_in_cycle():
    # An active pin with errors-only traffic is quarantined and a standby
    # promoted within the cycle (same path as a confirmed fake).
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1  # a6pin-fable-5 active
    chs[0]["id"] = 20
    gw = SickGW(chs, {20: 4}, {20: 0})
    # 1169 must be healthy for promotion (its check passes)
    state = {"a6pin-fable-5": {"rotation": ["claude-fable-5"], "idx": 0, "fails": 0, "quarantined": False}}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    m.run_cycle(
        gw, PassCC(),
        [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        ("claude", "gpt"), 168, threshold_for, 3, True, None, state,
    )
    # active pin quarantined (status 2 + state)
    assert chs[0]["status"] == 2, chs[0]
    assert state["a6pin-fable-5"]["quarantined"] is True
    # standby promoted (enabled first) — promotion requires enforce
    assert (21, 1) in gw.writes, gw.writes
    # healthy pins are NOT rotated: run again with successes present
    chs2 = [dict(c) for c in PIN_CHANNELS]
    chs2[0]["status"] = 1
    chs2[0]["id"] = 20
    gw2 = SickGW(chs2, {20: 4}, {20: 5})
    state2 = {}
    m.run_cycle(
        gw2, PassCC(),
        [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        ("claude", "gpt"), 168, threshold_for, 3, True, None, state2,
    )
    assert chs2[0]["status"] == 1, chs2[0]  # still active


def test_circuit_breaker_ignores_sparse_benign_errors():
    """REGRESSION GUARD (audit finding 2026-10-24): the breaker's severe-only
    promise would be void if the pin_is_sick early-return fired first. A
    healthy pin with a handful of benign 429s in a quiet window must NOT be
    rotated by the breaker. Raw type=5 counts include 429s and client aborts;
    only hard 5xx evidence may trip the severe path."""

    cfg = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
           "client_gone_ratio": 0.50, "hang_threshold": 10**9,
           "error_ratio_threshold": 0.80}

    class QuietBenignGW(FakeGW):
        # A healthy pin having a quiet window: a couple of benign 429s among
        # successful traffic. NOTE (audit H5): with ZERO successes this would
        # no longer be "benign noise" — it would be a total failure, which the
        # all-failures rule rotates (see
        # test_all_failures_rotates_even_with_benign_errors_when_armed). So a
        # benign-errors test necessarily has successes present, and what it
        # guards is that the RATIO checks ignore 4xx noise.
        def __init__(self, channels, ch_id):
            super().__init__(channels)
            self._cid = ch_id

        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            if channel_id != self._cid:
                return 0
            return 2 if log_type == 5 else 40

        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return [{"content": "status_code=429, rate limited"}] * 2

        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return [_row("eof", 900)]

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1
    chs[0]["id"] = 20
    gw = QuietBenignGW(chs, 20)
    state = {}
    m.RUNTIME = {
        "gateway": gw, "cctest": PassCC(),
        "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        "enforce": True, "discord": None, "state": state, "seller_registry": {},
    }
    try:
        with hermetic_market():
            m.circuit_breaker_tick(cfg, 15)
    finally:
        m.RUNTIME = None
    # healthy pin must still be active; nothing was rotated
    assert chs[0]["status"] == 1, chs[0]
    assert (21, 1) not in gw.writes, gw.writes


def test_recent_error_logs_paginates_past_one_page():
    """REGRESSION GUARD (audit H1, 2026-10-25). A single capped page
    undercounted hard errors while the ratio denominator used the TRUE success
    count, so the 80%-severe breaker could never trip on a busy channel
    (200 errors / 40 successes / 83% failing read as 'not sick'). This tests
    the pagination itself, not a fake that bypasses it."""

    class PagingGateway(m.Gateway):
        """Serves 200 error rows across pages of 100, like the real API."""
        def __init__(self):
            super().__init__("http://x", "tok")
            self.pages_requested = 0

        def _request(self, method, path, body=None):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(path).query)
            page = int(q.get("p", ["1"])[0])
            size = int(q.get("page_size", ["100"])[0])
            self.pages_requested += 1
            total = 200
            start = (page - 1) * size
            n = max(0, min(size, total - start))
            items = [{"content": "status_code=502"}] * n
            return {"success": True, "data": {"items": items, "total": total}}, 200

    gw = PagingGateway()
    rows = gw.recent_error_logs(1, 15, limit=100)
    assert rows is not None
    assert len(rows) == 200, f"paginated {len(rows)} rows, want 200 — page cap truncates"
    assert gw.pages_requested >= 2, gw.pages_requested


def test_dual_spelling_pin_can_be_quarantined():
    """REGRESSION GUARD (audit H4, 2026-10-25). sync_a6_keys creates pins
    listing BOTH spellings (gpt-6-1-sol + gpt-6.1-sol). Removing one spelling
    left the other, so the pin never reached the quarantine branch; the
    model-removal path was then blocked by its own channel and looped
    forever. A confirmed-fake dual-spelling pin served indefinitely."""
    # A pin listing both aliases.
    ch = {"id": 70, "name": "a6pin-6-1-sol-5151", "status": 1,
          "group": "default", "models": "gpt-6-1-sol,gpt-6.1-sol"}
    gw = FakeGW([ch])
    ch_state = {"model_fails": {"gpt-6-1-sol": 2, "gpt-6.1-sol": 2}}
    state = {}
    m.failover_model(
        gw, ch, ch_state, "a6pin-6-1-sol-5151", "gpt-6-1-sol", "attr_swapped",
        True, None, [ch], cctest=None, base_url="https://x", seller_key="sk",
        state=state, seller_registry={},
    )
    # Must QUARANTINE (disable the channel), not attempt a model removal.
    assert (70, 2) in gw.writes, gw.writes
    assert gw.model_edits == [], gw.model_edits
    assert ch_state.get("quarantined") is True, ch_state


def test_breaker_does_not_refresh_cycle_freshness():
    """REGRESSION GUARD (audit M2, 2026-10-25). The _meta.last_cycle_at
    freshness stamp lived in _run_sick_rotation, which the 5-minute breaker
    also calls — so a dead hourly cycle looked alive whenever the breaker was
    running. last_cycle_at is the admin page's only external 'cycle is stale'
    signal."""
    class HealthyGW(FakeGW):
        # Healthy pin (errors + successes). Must implement the log helpers
        # pin_latency_sick calls, or the tick crashes before reaching the
        # freshness write and the test proves nothing.
        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            return 0 if log_type == 5 else 100

        def recent_error_logs(self, channel_id, window_minutes, limit=100, max_rows=1000):
            return []

        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return []

    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1
    chs[0]["id"] = 20
    gw = HealthyGW(chs)
    state = {"_meta": {"last_cycle_at": "2026-10-01T00:00:00+00:00"}}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    m.RUNTIME = {
        "gateway": gw, "cctest": PassCC(),
        "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        "enforce": True, "discord": None, "state": state, "seller_registry": {},
    }
    cfg = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
           "client_gone_ratio": 0.50, "hang_threshold": 10**9,
           "error_ratio_threshold": 0.80}
    try:
        with hermetic_market():
            m.circuit_breaker_tick(cfg, 15)
    finally:
        m.RUNTIME = None
    # The breaker must NOT have moved the cycle stamp.
    assert state["_meta"]["last_cycle_at"] == "2026-10-01T00:00:00+00:00", state["_meta"]


def test_active_pin_verify_bad_verdict_is_not_discarded():
    """REGRESSION GUARD (audit M3, 2026-10-25). Verify on an ACTIVE pin that
    returned a bad verdict only turned the UI red: the pin stayed enabled and
    the fail counter was never touched, because process_verdict is skipped for
    direct checks. A confirmed-bad active pin must count toward the normal
    fail threshold."""
    ch = {"id": 70, "name": "a6pin-fable-5-4665", "status": 1,
          "group": "default", "models": "claude-fable-5", "model_mapping": ""}
    standby = {"id": 71, "name": "a6pin-fable-5-3825", "status": 2,
               "group": "default", "models": "claude-fable-5", "model_mapping": ""}
    gw = FakeGW([ch, standby])
    state = {}

    class BadCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "attr_swapped"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class A6M:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 4665"}]

        def reveal_key(self, tid):
            return "sk-fable"

    m._PIN_KEY_CACHE.clear()
    m.RUNTIME = {"gateway": gw, "cctest": BadCC(), "sellers": [],
                 "enforce": True, "discord": None, "state": state,
                 "seller_registry": {}, "a6m": A6M(),
                 "threshold_for": lambda name: 1}
    try:
        status, payload = m.run_action_verify({"model": "claude-fable-5",
                                               "channel": "a6pin-fable-5-4665"})
    finally:
        m.RUNTIME = None
    assert status == 200, (status, payload)
    # The confirmed failure was recorded on the active pin (not discarded).
    fails = state.get("a6pin-fable-5-4665", {}).get("fails", 0)
    assert fails >= 1, state.get("a6pin-fable-5-4665")


def test_cycle_channel_processing_respects_mutation_lock():
    """REGRESSION GUARD (audit BLOCKER 2026-10-25). The cycle's dedup and
    per-channel processing used to run WITHOUT the mutation lock, so an
    operator promote or circuit-breaker tick landing mid-loop raced it — the
    auditor reproduced two enabled pins for one model.

    Scenario: two pins enabled for one model (dedup WOULD disable the extra).
    While another thread holds the lock, the cycle must skip and write
    nothing."""
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1
    chs[0]["id"] = 20
    chs[1]["status"] = 1                     # the duplicate dedup should remove
    chs[1]["id"] = 21
    chs[1]["name"] = "a6pin-fable-5-1169"
    gw = FakeGW(chs)
    state = {}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    # Control: without the lock held, the cycle DOES dedup (proves the
    # scenario would write, so the assertion below is meaningful).
    m.run_cycle(gw, PassCC(), [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, {})
    assert (21, 2) in gw.writes, gw.writes

    # Now hold the lock as a competing rotation would, and run again on a
    # fresh duplicate pair: no writes may happen.
    chs2 = [dict(c) for c in PIN_CHANNELS]
    chs2[0]["status"] = 1
    chs2[0]["id"] = 20
    chs2[1]["status"] = 1
    chs2[1]["id"] = 21
    chs2[1]["name"] = "a6pin-fable-5-1169"
    gw2 = FakeGW(chs2)

    assert m._MUTATION_LOCK.acquire(blocking=False)
    try:
        m.run_cycle(gw2, PassCC(), [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
                    ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    finally:
        m._MUTATION_LOCK.release()

    assert gw2.writes == [], gw2.writes
    assert gw2.model_edits == [], gw2.model_edits


def test_pin_reveal_key_matches_the_pin_model_not_just_merchant():
    """REGRESSION GUARD (audit BLOCKER 2026-10-25). Merchant ids are reused
    across models — the same merchant sells several SKUs and list_tokens()
    returns them in API order. Matching on the merchant suffix alone revealed
    a pin with ANOTHER MODEL's key: the check then reported a swap against the
    wrong model, refused a healthy pin and bad-marked it, and an operator
    promote could quarantine the active pin then refuse the standby, leaving
    the model with zero enabled pins."""
    m._PIN_KEY_CACHE.clear()

    class A6M:
        """Merchant 4756 sells BOTH fable-5 and opus-5-5; the opus token is
        listed first, exactly the ordering that used to win."""
        def list_tokens(self):
            return [
                {"id": 1, "name": "OPUS 5.5 | 4756"},
                {"id": 2, "name": "FABLE 5 | 4756"},
            ]

        def reveal_key(self, tid):
            return {1: "sk-opus55", 2: "sk-fable5"}[tid]

    # The fable pin must get the fable key, not the opus one.
    assert m._pin_reveal_key(A6M(), "a6pin-fable-5-4756", "claude-fable-5") == "sk-fable5"
    m._PIN_KEY_CACHE.clear()
    # And the opus pin gets the opus key.
    assert m._pin_reveal_key(A6M(), "a6pin-opus-5-5-4756", "claude-opus-5-5") == "sk-opus55"
    m._PIN_KEY_CACHE.clear()
    # A pin whose model has no matching token must NOT borrow another
    # model's key — it returns None so the caller falls back.
    assert m._pin_reveal_key(A6M(), "a6pin-sonnet-5-4756", "claude-sonnet-5") is None
    m._PIN_KEY_CACHE.clear()


def test_all_failures_rotates_even_with_benign_errors_when_armed():
    """REGRESSION GUARD (audit H2, regression introduced 2026-10-24). When
    the latency flag was armed, pin_is_sick deferred to pin_latency_sick
    FIRST — which only counts hard 5xx content — so a pin failing 100% of
    requests with 429 / 401 / transport errors was never rotated. That made
    arming the catastrophic-detection feature DISABLE catastrophic
    detection for expired keys and quota exhaustion.

    The all-failures rule (errors > 0 AND zero successes) must apply on the
    armed path too, whatever the error content."""
    cfg = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
           "client_gone_ratio": 0.50, "hang_threshold": 10**9,
           "error_ratio_threshold": 0.05}

    for label, content in (
        ("429 rate limit", "status_code=429, rate limited"),
        ("401 expired key", "status_code=401, invalid api key"),
        ("transport reset", "upstream connection reset"),
        ("502 hard error", "status_code=502, pool exhausted"),
    ):
        class TotalFailGW(FakeGW):
            def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
                return 200 if log_type == 5 else 0   # errors, ZERO successes
            def recent_error_logs(self, channel_id, window_minutes, limit=100):
                return [{"content": content}] * 100  # page cap, as prod
            def recent_consume_logs(self, channel_id, window_minutes, limit=50):
                return []

        assert m.pin_is_sick(TotalFailGW([]), 1, 60, latency_cfg=cfg) is True,             f"{label}: a 100%-failing pin must be sick even when armed"

    # ...and a healthy pin with a few benign errors stays healthy.
    class HealthyGW(FakeGW):
        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            return 2 if log_type == 5 else 60
        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return [{"content": "status_code=429"}] * 2
        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return []
    assert m.pin_is_sick(HealthyGW([]), 1, 60, latency_cfg=cfg) is False


class _PrimaryGW(FakeGW):
    def __init__(self, channels, err, ok):
        super().__init__(channels)
        self._err, self._ok = err, ok

    def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
        return self._err if log_type == 5 else self._ok

    def recent_error_logs(self, channel_id, window_minutes, limit=100):
        return [{"content": "status_code=502"}] * self._err

    def recent_consume_logs(self, channel_id, window_minutes, limit=50):
        return []


PRIMARY_CFG = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
               "client_gone_ratio": 0.50, "hang_threshold": 10**9,
               "error_ratio_threshold": 0.10}


def _primary_ch(status):
    return {"id": 95, "name": "kiro-pool", "status": status,
            "group": "default", "models": "claude-opus-5-5", "model_mapping": ""}


def _run_primary(gw, state, probe=None):
    m.RUNTIME = {"gateway": gw, "cctest": None, "sellers": [], "enforce": True,
                 "discord": None, "state": state, "seller_registry": {},
                 "primary_channels": ("kiro-pool",),
                 "primary_probe": probe or {"base_url": "http://kiro:8080",
                                            "api_key": "sk-x",
                                            "model": "claude-sonnet-5"}}
    try:
        return m.sweep_primary_channels(PRIMARY_CFG, 15, 30)
    finally:
        m.RUNTIME = None
        # The sweep calls save_state(), which persists to the shared
        # state_test.json. Drop it so this test's _primary/kiro-pool state
        # cannot leak into a later test (observed: broke
        # test_last_verdicts_recorded only when run in-suite).
        try:
            os.remove(m.STATE_PATH)
        except OSError:
            pass


def test_primary_channel_fails_over_when_degraded():
    """Owner decision 2026-10-25: kiro-pool is the primary and the a6pin pins
    are the backup. Because the primary outranks the pins, failover = disable
    it so priority routing falls through to the already-enabled pin."""
    ch = _primary_ch(1)
    gw = _PrimaryGW([ch], err=90, ok=10)          # 90% hard errors
    state = {}
    assert _run_primary(gw, state) == 1
    assert ch["status"] == 2, ch                 # disabled
    assert state["_primary"]["kiro-pool"]["disabled_at"] is not None
    # NO promotion happened — the pins were already enabled below it
    assert not gw.writes or all(w[0] != 21 for w in gw.writes), gw.writes


def test_min_errors_prevents_small_sample_trip():
    """Owner decision 2026-10-25: a percentage alone let 3 failures in a
    quiet 30-request window read as 10% and disable the primary on noise.
    The absolute floor must make that impossible."""
    cfg = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
           "client_gone_ratio": 0.50, "hang_threshold": 10**9,
           "error_ratio_threshold": 0.10, "min_errors": 10}

    class GW(FakeGW):
        def __init__(self, err, ok):
            super().__init__([])
            self._e, self._o = err, ok
        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            return self._e if log_type == 5 else self._o
        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return [{"content": "status_code=500, upstream stream ended before any output"}] * self._e
        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return []

    # The live incident: 3 errors / 27 successes = 10% → must NOT trip.
    assert m.pin_is_sick(GW(3, 27), 95, 15, latency_cfg=cfg) is False
    # A real outage: 40 errors / 60 successes = 40% and >= 10 errors → trips.
    assert m.pin_is_sick(GW(40, 60), 95, 15, latency_cfg=cfg) is True


def test_post_restore_grace_ignores_pre_restore_errors():
    """The 5-minute disable/restore flap (2026-10-25): after a restore, the
    same errors that caused the outage were still inside the 15m window, so
    the next tick disabled Kiro again. During the grace window the sweep must
    judge only evidence collected SINCE the restore."""
    now = time.time()
    ch = _primary_ch(1)
    state = {"_primary": {"kiro-pool": {
        "disabled_at": None, "healthy_since": None,
        "restored_at": now - 60,          # restored a minute ago
        "last_restore": {"at": "x", "down_seconds": 300, "attempts": 1, "probe": "ok"},
    }}}

    class GraceGW(_PrimaryGW):
        """Pre-restore window is catastrophic; since-restore is clean."""
        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            if since_ts:                  # since-restore slice: healthy
                return 0 if log_type == 5 else 20
            return 90 if log_type == 5 else 10   # full window: looks terrible

        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return []                     # nothing since the restore

    gw = GraceGW([ch], err=0, ok=0)
    _run_primary(gw, state)
    # Grace respected → still ENABLED, no flap.
    assert ch["status"] == 1, ch

    # After the grace window expires, the full window counts again.
    state["_primary"]["kiro-pool"]["restored_at"] = now - 20 * 60
    gw2 = _PrimaryGW([ch], err=90, ok=10)
    _run_primary(gw2, state)
    assert ch["status"] == 2, ch


def test_primary_restore_requires_live_probe_pass():
    """Restore is proven by a LIVE request, not by an empty log window
    (owner decision 2026-10-25, option B). A disabled primary serves no
    traffic, so absence of errors proves nothing — the old code re-enabled
    on silence and flapped."""
    ch = _primary_ch(2)
    state = {"_primary": {"kiro-pool": {"disabled_at": time.time() - 3600,
                                        "healthy_since": None}}}
    gw = _PrimaryGW([ch], err=0, ok=0)            # silent: no traffic either way

    calls = []

    def failing_probe(base_url, api_key, model, timeout=60):
        calls.append(model)
        return False, "http 429"

    original = m.probe_primary_live
    m.probe_primary_live = failing_probe
    try:
        _run_primary(gw, state)
        # Failing probe → stays disabled, no clock started
        assert ch["status"] == 2, ch
        assert calls == ["claude-sonnet-5"], calls
        assert state["_primary"]["kiro-pool"]["healthy_since"] is None
        assert state["_primary"]["kiro-pool"]["last_probe"]["ok"] is False

        # Passing probe → restores immediately (owner: ONE proof)
        m.probe_primary_live = lambda *a, **k: (True, "ok (out=1)")
        _run_primary(gw, state)
        assert ch["status"] == 1, ch
        assert state["_primary"]["kiro-pool"]["disabled_at"] is None
        assert state["_primary"]["kiro-pool"]["last_restore"]["probe"] == "ok (out=1)"
    finally:
        m.probe_primary_live = original


def test_primary_restore_refuses_without_probe_config():
    """With no probe configured the monitor cannot prove recovery, so it
    must NOT restore on silence — it stays on the backup (safe)."""
    ch = _primary_ch(2)
    state = {"_primary": {"kiro-pool": {"disabled_at": time.time() - 3600,
                                        "healthy_since": None}}}
    gw = _PrimaryGW([ch], err=0, ok=0)
    _run_primary(gw, state, probe={"base_url": "", "api_key": "", "model": "x"})
    assert ch["status"] == 2, ch


def test_primary_left_alone_when_not_ours():
    ch = _primary_ch(2)
    st = {}
    gw = _PrimaryGW([ch], err=0, ok=100)
    _run_primary(gw, st)
    assert ch["status"] == 2, ch
    assert st["_primary"]["kiro-pool"]["disabled_at"] is None


def test_circuit_breaker_rotates_catastrophic_pin_only():
    """The severe-degradation watchdog (circuit_breaker_tick) reuses the
    rotation path with severe-only thresholds: it rotates a pin failing
    ~everything, and leaves a merely-marginal pin for the hourly cycle."""

    class CatastrophicGW(SickGW):
        # 90% hard errors, well over the 80% breaker threshold.
        def __init__(self, channels, ch_id):
            super().__init__(channels, {ch_id: 90}, {ch_id: 10})

        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return [{"content": "status_code=502"}] * (self.error_counts.get(channel_id) or 0)

        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return []

    class MarginalGW(FakeGW):
        # 25% errors — under the 80% breaker threshold (would trip the hourly
        # 5% error_ratio rule, but NOT the breaker).
        def __init__(self, channels, ch_id):
            super().__init__(channels)
            self._cid = ch_id

        def count_logs(self, log_type, channel_id, window_minutes, since_ts=None):
            return 25 if (log_type == 5 and channel_id == self._cid) else 100

        def recent_error_logs(self, channel_id, window_minutes, limit=100):
            return [{"content": "status_code=502"}] * 25

        def recent_consume_logs(self, channel_id, window_minutes, limit=50):
            return []

    cfg = {"enabled": True, "min_samples": 15, "frt_ms_threshold": 10**12,
           "client_gone_ratio": 0.50, "hang_threshold": 10**9,
           "error_ratio_threshold": 0.80}

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    def run_once(gw_cls):
        chs = [dict(c) for c in PIN_CHANNELS]
        chs[0]["status"] = 1
        chs[0]["id"] = 20
        gw = gw_cls(chs, 20)
        state = {}
        m.RUNTIME = {
            "gateway": gw, "cctest": PassCC(),
            "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
            "enforce": True, "discord": None, "state": state, "seller_registry": {},
        }
        try:
            with hermetic_market():
                m.circuit_breaker_tick(cfg, 15)
        finally:
            m.RUNTIME = None
        return chs[0], gw

    # catastrophic pin rotates
    ch0, gw = run_once(CatastrophicGW)
    assert ch0["status"] == 2, ch0
    assert (21, 1) in gw.writes, gw.writes
    # marginal pin does NOT rotate on the breaker (hourly cycle owns it)
    ch1, gw2 = run_once(MarginalGW)
    assert ch1["status"] == 1, ch1
    assert (21, 1) not in gw2.writes, gw2.writes


def test_cycle_dedupes_multiple_active_pins():
    # Owner rule: exactly ONE enabled pin per model. When a second pin is
    # manually enabled (e.g. via the channels page), the cycle disables it
    # back to standby and keeps the first-seen pin active.
    chs = [dict(c) for c in PIN_CHANNELS]
    chs[0]["status"] = 1  # a6pin-fable-5 active
    chs[0]["id"] = 20
    # Manually enable a second pin for the same model (the bug scenario).
    chs[1]["status"] = 1
    chs[1]["id"] = 21
    chs[1]["name"] = "a6pin-fable-5-1169"
    gw = FakeGW(chs)

    class PassCC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    state = {}
    m.run_cycle(
        gw, PassCC(),
        [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        ("claude", "gpt"), 168, threshold_for, 3, True, None, state,
    )
    # The extra pin (1169) is disabled back to standby; the first stays active.
    assert (21, 2) in gw.writes, gw.writes
    assert (20, 2) not in gw.writes, gw.writes


def test_auto_release_green_history():
    # A quarantined pin whose latest verdict is a pass is auto-released at
    # cycle start — a green verdict from any prior path (manual verify,
    # cooldown re-check) means the quarantine is stale.
    chs = [
        {"id": 20, "name": "a6pin-fable-5-4665", "status": 2, "models": "claude-fable-5"},
        {"id": 21, "name": "a6pin-fable-5-3825", "status": 1, "models": "claude-fable-5"},
    ]
    state = {
        "a6pin-fable-5-4665": {
            "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
            "quarantined": True, "model": "claude-fable-5",
            "last_verdicts": {"claude-fable-5": {"verdict": "official", "at": "2026-10-23T00:00:00"}},
        },
    }
    gw = FakeGW(chs)
    m.run_cycle(gw, VerdictCC(), [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    # Auto-release clears the quarantine but NEVER writes channel status
    # (owner spec 2026-10-24: release = standby, not pinned; the other pin
    # keeps serving).
    assert (20, 1) not in gw.writes, gw.writes
    assert (20, 2) not in gw.writes, gw.writes
    assert state["a6pin-fable-5-4665"]["quarantined"] is False


def test_cycle_dedupes_alias_active_pins():
    # gpt-6-1-sol and gpt-6.1-sol are the SAME pool — two enabled pins
    # serving different spellings of the same model are still a duplicate.
    chs = [
        {"id": 20, "name": "a6pin-6-1-sol-5950", "status": 1, "models": "gpt-6-1-sol"},
        {"id": 21, "name": "a6pin-6.1-sol-1416", "status": 1, "models": "gpt-6.1-sol"},
    ]
    gw = FakeGW(chs)
    state = {}
    m.run_cycle(
        gw, VerdictCC(),
        [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        ("claude", "gpt"), 168, threshold_for, 3, True, None, state,
    )
    # One of them was disabled (the second-seen).
    assert (21, 2) in gw.writes, gw.writes
    assert (20, 2) not in gw.writes, gw.writes


def test_status_payload_includes_sync():
    state = {"_meta": {"last_cycle_at": "x"}, "_sync": {"last_sync_at": "y", "created": ["a6pin-a-1"]}}
    payload = m.status_payload(state, m.read_display_config())
    assert payload["last_sync_at"] == "y"
    assert "_sync" not in payload["channels"]


def test_action_verify_releases_quarantine_on_pass():
    # Re-verifying a quarantined pin that now passes must RELEASE it (the
    # merchant recovered) — the live 2026-10-21 complaint "re-verify still
    # quarantined".
    chs = [{"id": 20, "name": "a6pin-fable-5-4756", "status": 2, "group": "default",
            "models": "claude-fable-5"}]
    gw = FakeGW(chs)
    state = {"a6pin-fable-5-4756": {"rotation": ["claude-fable-5"], "idx": 0,
                                    "fails": 1, "quarantined": True, "model": "claude-fable-5"}}

    class DirectPass:
        # A direct pin check calls check(base=pin base, key=<revealed>, model)
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "official"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class FakeA6:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 4756"}]

        def reveal_key(self, tid):
            return "sk-pin"

    m._PIN_KEY_CACHE.clear()
    m.RUNTIME = {
        "gateway": gw, "cctest": DirectPass(),
        "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {}, "a6m": FakeA6(),
    }
    try:
        status, payload = m.run_action_verify({"channel": "a6pin-fable-5-4756", "model": "claude-fable-5"})
        assert status == 200, payload
        assert payload["data"]["verdict"] == "official", payload
        # Released: quarantine state cleared, but the channel is NOT enabled
        # (owner spec 2026-10-24: verify checks trueness and lifts the
        # quarantine only; pinning happens exclusively via "Use this
        # merchant" — the 2026-10-22 sol double-pin root cause).
        assert (20, 1) not in gw.writes, gw.writes
        assert chs[0]["status"] == 2, chs
        assert state["a6pin-fable-5-4756"]["quarantined"] is False, state
    finally:
        m.RUNTIME = None
        m._PIN_KEY_CACHE.clear()


def test_action_verify_fail_keeps_quarantine():
    # A failing re-check of a quarantined pin does NOT release it.
    chs = [{"id": 20, "name": "a6pin-fable-5-4756", "status": 2, "group": "default",
            "models": "claude-fable-5"}]
    gw = FakeGW(chs)
    state = {"a6pin-fable-5-4756": {"rotation": ["claude-fable-5"], "idx": 0,
                                    "fails": 1, "quarantined": True, "model": "claude-fable-5"}}

    class DirectBad:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "attr_swapped"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

    class FakeA6:
        def list_tokens(self):
            return [{"id": 1, "name": "FABLE 5 | 4756"}]

        def reveal_key(self, tid):
            return "sk-pin"

    m._PIN_KEY_CACHE.clear()
    m.RUNTIME = {
        "gateway": gw, "cctest": DirectBad(),
        "sellers": [("a6pin", "https://vantyr.xyz", "sk-RELAY")],
        "enforce": True, "threshold_for": threshold_for, "discord": None,
        "state": state, "seller_registry": {}, "a6m": FakeA6(),
    }
    try:
        status, payload = m.run_action_verify({"channel": "a6pin-fable-5-4756", "model": "claude-fable-5"})
        assert status == 200, payload
        assert payload["data"]["verdict"] == "attr_swapped", payload
        assert (20, 1) not in gw.writes, gw.writes  # no release
        assert state["a6pin-fable-5-4756"]["quarantined"] is True, state
    finally:
        m.RUNTIME = None
        m._PIN_KEY_CACHE.clear()


def test_tier_stem_normalization():
    # SKU spellings, prefixes, case, the cctest dot alias all reduce to stems.
    assert m._tier_stem("claude-opus-5-5") == "opus-5-5"
    assert m._tier_stem("claude-fable-5-1") == "fable-5-1"
    assert m._tier_stem("gpt-6-astra") == "6-astra"
    assert m._tier_stem("gpt-6-sol") == "6-sol"
    assert m._tier_stem("gpt-6-1-sol") == "6-1-sol"
    assert m._tier_stem("gpt-6.1-sol") == "6-1-sol"  # cctest dropdown spelling
    assert m._tier_stem("Claude-Opus-5") == "opus-5"
    assert m._tier_stem("claude-opus-4-6") == "opus-4-6"  # legacy prediction name
    assert m._tier_stem("") is None
    assert m._tier_stem(None) is None


def test_accepted_upgrade_claude_ladder():
    # claude ladder: sonnet-5 < sonnet-5-5 < opus-5 < opus-5-5 < fable-5 < fable-5-1
    # opus-5-5 accepts fable-5, fable-5-1
    assert m.accepted_upgrade("claude-opus-5-5", "claude-fable-5") is True
    assert m.accepted_upgrade("claude-opus-5-5", "claude-fable-5-1") is True
    # opus-5-5 rejects everything at-or-below (incl. itself and lower rungs)
    assert m.accepted_upgrade("claude-opus-5-5", "claude-opus-5-5") is False
    assert m.accepted_upgrade("claude-opus-5-5", "claude-opus-5") is False
    assert m.accepted_upgrade("claude-opus-5-5", "claude-sonnet-5-5") is False
    assert m.accepted_upgrade("claude-opus-5-5", "claude-sonnet-5") is False
    # sonnet-5-5 accepts opus-5, opus-5-5, fable-5, fable-5-1
    for p in ("claude-opus-5", "claude-opus-5-5", "claude-fable-5", "claude-fable-5-1"):
        assert m.accepted_upgrade("claude-sonnet-5-5", p) is True
    # sonnet-5 accepts opus-5, opus-5-5, fable-5, fable-5-1
    for p in ("claude-opus-5", "claude-opus-5-5", "claude-fable-5", "claude-fable-5-1"):
        assert m.accepted_upgrade("claude-sonnet-5", p) is True
    assert m.accepted_upgrade("claude-sonnet-5", "claude-sonnet-5-5") is True
    # fable-5 accepts fable-5-1 only
    assert m.accepted_upgrade("claude-fable-5", "claude-fable-5-1") is True
    assert m.accepted_upgrade("claude-fable-5", "claude-opus-5-5") is False
    # fable-5-1 is the top: accepts nothing (owner ruling 2026-10-23)
    assert m.accepted_upgrade("claude-fable-5-1", "claude-fable-5") is False
    assert m.accepted_upgrade("claude-fable-5-1", "claude-opus-5-5") is False


def test_accepted_upgrade_gpt_ladder():
    # gpt ladder: sol < 6-1-sol < astra
    assert m.accepted_upgrade("gpt-6-sol", "gpt-6-1-sol") is True
    assert m.accepted_upgrade("gpt-6-sol", "gpt-6-astra") is True
    assert m.accepted_upgrade("gpt-6-sol", "gpt-6-sol") is False
    assert m.accepted_upgrade("gpt-6-1-sol", "gpt-6-astra") is True
    assert m.accepted_upgrade("gpt-6-1-sol", "gpt-6-sol") is False
    # astra is the top: exact match only
    assert m.accepted_upgrade("gpt-6-astra", "gpt-6-astra") is False
    assert m.accepted_upgrade("gpt-6-astra", "gpt-6-1-sol") is False
    # cctest dot spelling of 6.1-sol compares equal
    assert m.accepted_upgrade("gpt-6-1-sol", "gpt-6.1-sol") is False


def test_accepted_upgrade_no_cross_family():
    # A Claude pin never accepts a GPT prediction and vice versa.
    assert m.accepted_upgrade("claude-opus-5-5", "gpt-6-astra") is False
    assert m.accepted_upgrade("gpt-6-astra", "claude-fable-5-1") is False
    # Unparseable / unknown models are not upgrades.
    assert m.accepted_upgrade("claude-opus-5-5", None) is False
    assert m.accepted_upgrade("claude-opus-5-5", "glm-5.3") is False
    assert m.accepted_upgrade("glm-5.3", "claude-opus-5-5") is False


def _upgrade_cctest(expected_served):
    """Fake cctest returning attr_swapped with the given prediction."""
    class CC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "attr_swapped",
                    "attribution": {"prediction": expected_served}}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]

        @staticmethod
        def prediction(r):
            return r["attribution"]["prediction"]
    return CC()


def test_do_check_reclassifies_upgrade():
    # attr_swapped whose prediction is a strictly higher tier -> attr_upgraded (PASS).
    # do_check returns the verdict alone; the prediction is internal to its
    # tier logic (refactor 2026-10-24 — returning a tuple let a caller treat
    # (None, None) as truthy and promote an unverified merchant).
    verdict = m.do_check(_upgrade_cctest("claude-fable-5-1"),
                         "https://x", "sk", "claude-opus-5-5")
    assert verdict == "attr_upgraded", verdict
    assert verdict in m.PASS_VERDICTS


def test_do_check_downgrade_stays_swapped():
    # fable-5-1 served fable-5 is a DOWNGRADE: still attr_swapped (owner ruling).
    verdict = m.do_check(_upgrade_cctest("claude-fable-5"),
                         "https://x", "sk", "claude-fable-5-1")
    assert verdict == "attr_swapped", verdict
    assert verdict in m.BAD_VERDICTS


def test_do_check_top_of_ladder_stays_swapped():
    # astra and fable-5-1 accept nothing; any swap on them is real.
    verdict = m.do_check(_upgrade_cctest("gpt-6-1-sol"), "https://x", "sk", "gpt-6-astra")
    assert verdict == "attr_swapped", verdict
    verdict = m.do_check(_upgrade_cctest("claude-opus-5-5"), "https://x", "sk", "claude-fable-5-1")
    assert verdict == "attr_swapped", verdict


def test_do_check_no_prediction_stays_swapped():
    class CC:
        @staticmethod
        def check(b, k, mo):
            return {"verdict": "attr_swapped"}

        @staticmethod
        def verdict_category(r):
            return r["verdict"]
    verdict = m.do_check(CC(), "https://x", "sk", "claude-opus-5-5")
    assert verdict == "attr_swapped", verdict


def test_do_check_gpt_upgrade():
    # gpt-6-sol served gpt-6-astra -> upgrade.
    verdict = m.do_check(_upgrade_cctest("gpt-6-astra"), "https://x", "sk", "gpt-6-sol")
    assert verdict == "attr_upgraded", verdict


def test_do_check_alias_prediction_is_match_not_swap():
    # cctest's dropdown spells gpt-6-1-sol with a dot: a check for
    # gpt-6-1-sol whose prediction is gpt-6.1-sol (the SAME model) must not
    # stay attr_swapped — quarantining for a spelling alias is a false
    # positive (audit 2026-10-23).
    verdict = m.do_check(_upgrade_cctest("gpt-6.1-sol"), "https://x", "sk", "gpt-6-1-sol")
    assert verdict == "attr_match", verdict
    assert verdict in m.PASS_VERDICTS
    # and the reverse direction: upstream name with dot, prediction without
    verdict = m.do_check(_upgrade_cctest("gpt-6-1-sol"), "https://x", "sk", "gpt-6.1-sol")
    assert verdict == "attr_match", verdict
    # a same-rung Claude prediction likewise: exact stem equality after
    # normalization is a match, not an upgrade or a swap
    verdict = m.do_check(_upgrade_cctest("claude-opus-5-5"), "https://x", "sk", "claude-opus-5-5")
    assert verdict == "attr_match", verdict



def test_gateway_watchdog_alerts_once_then_reports_recovery():
    """The 2026-10-26 gap: a dead gateway produced only repeated
    `[primary] sweep failed` lines and no page. The watchdog must page after
    the sustained-down window and again on recovery — exactly twice for one
    outage, never once per tick."""
    alerts = []
    probes = [False, False, False, False, False, True]   # down, then up
    clock = [1000.0]

    def fake_liveness(base_url, timeout=10.0):
        return probes.pop(0) if probes else True

    real_liveness, real_sleep, real_alert, real_time = (
        m.gateway_liveness, m.time.sleep, m.discord_alert, m.time.time)
    m.gateway_liveness = fake_liveness
    m.discord_alert = lambda webhook, text: alerts.append(text)
    # Each probe advances 30s; stop the loop once the scripted probes run out
    # and one more tick has confirmed recovery.
    def fake_sleep(_seconds):
        clock[0] += 30.0
        if not probes:
            raise SystemExit
    m.time.sleep = fake_sleep
    m.time.time = lambda: clock[0]
    try:
        try:
            m.gateway_watchdog_loop("http://gateway:3000", "https://hook",
                                    interval=30, down_after=120)
        except SystemExit:
            pass
    finally:
        m.gateway_liveness, m.time.sleep = real_liveness, real_sleep
        m.discord_alert, m.time.time = real_alert, real_time

    assert len(alerts) == 2, alerts
    assert "GATEWAY DOWN" in alerts[0], alerts[0]
    assert "is back" in alerts[1], alerts[1]


def test_gateway_watchdog_silent_when_healthy():
    """A healthy gateway must never page — this runs every 30s forever."""
    alerts = []
    calls = [0]

    def fake_liveness(base_url, timeout=10.0):
        calls[0] += 1
        return True

    def fake_sleep(_seconds):
        if calls[0] >= 5:
            raise SystemExit

    real_liveness, real_sleep, real_alert = (
        m.gateway_liveness, m.time.sleep, m.discord_alert)
    m.gateway_liveness = fake_liveness
    m.discord_alert = lambda webhook, text: alerts.append(text)
    m.time.sleep = fake_sleep
    try:
        try:
            m.gateway_watchdog_loop("http://gateway:3000", "https://hook",
                                    interval=30, down_after=120)
        except SystemExit:
            pass
    finally:
        m.gateway_liveness, m.time.sleep = real_liveness, real_sleep
        m.discord_alert = real_alert

    assert alerts == [], alerts


def test_gateway_watchdog_short_blip_does_not_page():
    """Down for one tick then back: below the sustained window, so no page.
    Flapping must not turn into an alert storm."""
    alerts = []
    probes = [False, True, True]

    def fake_liveness(base_url, timeout=10.0):
        return probes.pop(0) if probes else True

    def fake_sleep(_seconds):
        if not probes:
            raise SystemExit

    real_liveness, real_sleep, real_alert = (
        m.gateway_liveness, m.time.sleep, m.discord_alert)
    m.gateway_liveness = fake_liveness
    m.discord_alert = lambda webhook, text: alerts.append(text)
    m.time.sleep = fake_sleep
    try:
        try:
            m.gateway_watchdog_loop("http://gateway:3000", "https://hook",
                                    interval=30, down_after=120)
        except SystemExit:
            pass
    finally:
        m.gateway_liveness, m.time.sleep = real_liveness, real_sleep
        m.discord_alert = real_alert

    assert alerts == [], alerts



if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
