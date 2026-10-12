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
    {"id": 1, "name": "selora-default-primary", "status": 1,
     "models": "claude-fable-5-1,gpt-6-astra,glm-5.3"},
    {"id": 2, "name": "a6-default-primary", "status": 1,
     "models": "claude-fable-5-1,gpt-6-astra"},
    {"id": 3, "name": "selora-default-fallback", "status": 1,
     "models": "claude-fable-5-1"},
    {"id": 4, "name": "selora-unlimited", "status": 1,
     "models": "claude-fable-5-1,claude-sonnet-5-5"},
    {"id": 5, "name": "a6-default-fallback", "status": 1,
     "models": "gpt-6-astra"},
    {"id": 6, "name": "a6-unlimited", "status": 1,
     "models": "claude-fable-5-1"},
    {"id": 7, "name": "mia-failover", "status": 1,
     "models": "claude-fable-5-1,claude-opus-5-5,claude-sonnet-5"},
]


class FakeGW:
    def __init__(self, channels):
        self.channels = channels
        self.writes = []

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
    state = {}
    gw = run([("selora", "https://x", "sk")], True, state)
    assert (1, 2) in gw.writes, gw.writes  # primary quarantined (threshold 1)
    assert state["selora-default-primary"]["quarantined"] is True
    # All three selora-* channels hit threshold 1 in the same cycle, so
    # every one of them is quarantined.
    assert all(state[n]["quarantined"] for n in state if n.startswith("selora"))


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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
