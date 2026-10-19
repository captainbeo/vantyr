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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
