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
        return self.channels

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

    def count_logs(self, log_type, channel_id, window_minutes):
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


PIN_CHANNELS = [
    # active pin quarantined by us (status 2) + two standbys (status 2)
    {"id": 20, "name": "a6pin-fable-5", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
    {"id": 21, "name": "a6pin-fable-5-1169", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
    {"id": 22, "name": "a6pin-fable-5-3825", "status": 2, "group": "default",
     "models": "claude-fable-5", "model_mapping": ""},
]


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
            "quarantined": True, "model": "claude-fable-5"},
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

    gw = FakeGW(chs)
    m.run_cycle(gw, CleanNow(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    # 1169 was re-tried after cooldown, passed, stays enabled, mark cleared
    assert (21, 1) in gw.writes, gw.writes
    assert gw.channels[1]["status"] == 1
    marks = state.get("bad_standbys", {}).get("claude-fable-5", {})
    assert "a6pin-fable-5-1169" not in marks, marks


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
    m.run_cycle(gw, VerdictCC(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    assert gw.writes == [], gw.writes  # nothing promoted
    assert gw.channels[1]["status"] == 2  # both stay benched


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
    m.run_cycle(gw, KeySpy(), sellers, ("claude", "gpt"), 168, threshold_for, 3,
                True, None, state)
    # verification check + (benign) immediate re-verify of the promoted
    # standby's own entry later in the cycle — at most 2, never more
    assert 1 <= len(seen_keys) <= 2, seen_keys
    assert gw.channels[1]["status"] == 1
    assert (21, 1) in gw.writes, gw.writes


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
    assert re.search(r'\("a6pin",\s*max\(1,\s*int\(os\.environ\.get\("FAIL_THRESHOLD_A6PIN",\s*"1"\)\)\)\)', src), \
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


def test_last_verdicts_standby_verification():
    # The promote/verify standby path records into the standby's own state.
    chs = [dict(c) for c in PIN_CHANNELS] + [dict(c) for c in CHANNELS]
    state = {"a6pin-fable-5": {
        "rotation": ["claude-fable-5"], "idx": 0, "fails": 1,
        "quarantined": True, "model": "claude-fable-5"}}
    gw = FakeGW(chs)
    m.run_cycle(gw, VerdictCC(), [("a6pin-fable-5", "https://api.a6api.com", "sk-pin")],
                ("claude", "gpt"), 168, threshold_for, 3, True, None, state)
    entry = state["a6pin-fable-5-1169"]["last_verdicts"]["claude-fable-5"]
    assert entry["verdict"] == "unofficial", entry


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
    # Merchant-suffixed pins yield their merchant; plain-named legacy pins
    # (trailing digit is part of the model) yield None.
    assert m.pin_merchant("a6pin-fable-5-4665") == "4665"
    assert m.pin_merchant("a6pin-sonnet-5") is None
    # a6pin-opus-5-5 is genuinely ambiguous (opus-5-5 is itself a stem AND
    # "5" could be a merchant) — the stem check treats it as a merchant pin.
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
        # quarantine released: channel enabled + state cleared
        assert chs[0]["status"] == 1, chs
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
    # recorded; plain-named legacy pins (non-digit suffix) are left alone.
    chs = [
        {"id": 60, "name": "a6pin-6-astra-5942", "status": 1, "models": "gpt-6-astra"},   # has token
        {"id": 61, "name": "a6pin-6-astra-5312", "status": 1, "models": "gpt-6-astra"},   # phantom
        {"id": 62, "name": "a6pin-fable-5", "status": 1, "models": "claude-fable-5"},      # legacy plain name
        {"id": 63, "name": "a6pin-6-astra-2757", "status": 2, "models": "gpt-6-astra"},   # phantom but already off
    ]
    gw = SyncGW(chs)
    # A6 account only has merchant 5942.
    a6m = FakeA6M([{"id": 1, "name": "ASTRA 6 | 5942"}], reveals={1: "sk-x"})
    state = {}
    m.sync_a6_keys(gw, a6m, chs, state, None)
    # 5942 stays enabled; 5312 disabled; legacy a6pin-fable-5 untouched; 2757 untouched
    assert (61, 2) in gw.writes, gw.writes
    assert (60, 2) not in gw.writes, gw.writes
    assert (62, 2) not in gw.writes, gw.writes
    assert (63, 2) not in gw.writes, gw.writes
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

    def count_logs(self, log_type, channel_id, window_minutes):
        if log_type == 5:
            return self.error_counts.get(channel_id)
        return self.success_counts.get(channel_id)


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
        # released: enabled + state cleared
        assert (20, 1) in gw.writes, gw.writes
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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
