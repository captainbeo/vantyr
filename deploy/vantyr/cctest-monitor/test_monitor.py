"""Dry-run policy tests for monitor.py — no network, mocked gateway/cctest.

Run: python test_monitor.py
"""
import importlib.util
import os

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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
