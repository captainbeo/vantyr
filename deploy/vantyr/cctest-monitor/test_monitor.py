"""Dry-run policy tests for monitor.py — no network, mocked gateway/cctest.

Run: python test_monitor.py
"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("monitor", os.path.join(os.path.dirname(__file__), "monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.STATE_PATH = os.path.join(os.environ.get("TEMP", "."), "state_test.json")


class FakeGW:
    def __init__(self):
        self.writes = []

    def find_channel(self, name):
        return 1, ["claude-fable-5-1", "gpt-6-astra", "glm-5.3"], m.CHANNEL_ENABLED

    def model_used_recently(self, cid, model, hours):
        return True

    def set_status(self, cid, status):
        self.writes.append((cid, status))
        return True


class FailCCTest:
    @staticmethod
    def check(b, k, mo):
        return {"category": "unofficial"}

    @staticmethod
    def verdict_category(r):
        return r["category"]


class PassCCTest:
    @staticmethod
    def check(b, k, mo):
        return {"category": "official"}

    @staticmethod
    def verdict_category(r):
        return r["category"]


class NoneCCTest:
    @staticmethod
    def check(b, k, mo):
        return None

    @staticmethod
    def verdict_category(r):
        return None


def run(name, sellers, enforce, state, cc=FailCCTest(), gw=None):
    gateway = gw or FakeGW()
    m.run_cycle(gateway, cc, sellers, ("claude", "gpt"), 168,
                {"selora-reseller": 1, "a6-marketplace": 2}, 3, enforce, None, state)
    return gateway


def test_parse():
    known = {"selora-reseller", "a6-marketplace"}
    good = m.parse_seller_channels(
        "selora-reseller|https://api.selora.lol|sk-abc , a6-marketplace|https://api.a6api.com|sk-xyz", known)
    assert good == [("selora-reseller", "https://api.selora.lol", "sk-abc"),
                    ("a6-marketplace", "https://api.a6api.com", "sk-xyz")], good
    assert m.parse_seller_channels("foo|https://x|k", known) == []
    assert m.parse_seller_channels("selora-reseller:https://api.selora.lol:sk-abc", known) == []
    assert m.CCTest.verdict_category({"verdict": "Not_Claude"}) == "not_claude"


def test_state_roundtrip():
    m.save_state({"selora-reseller": {"fails": 1}})
    assert m.load_state() == {"selora-reseller": {"fails": 1}}
    os.remove(m.STATE_PATH)


def test_enforce_quarantine():
    state = {}
    gw = run("q", [("selora-reseller", "https://x", "sk")], True, state)
    assert gw.writes == [(1, 2)], gw.writes
    assert state["selora-reseller"]["quarantined"] is True


def test_quarantine_release():
    # Gateway still shows status 2 (we quarantined it) → passing re-test
    # triggers the release write (status 1).
    state = {"selora-reseller": {"rotation": [], "idx": 0, "fails": 1,
                                 "quarantined": True, "model": "gpt-6-astra"}}

    class QuarantinedGW(FakeGW):
        def find_channel(self, name):
            return 1, ["gpt-6-astra"], m.CHANNEL_MANUALLY_DISABLED

    gw = run("r", [("selora-reseller", "https://x", "sk")], True, state, cc=PassCCTest(), gw=QuarantinedGW())
    assert (1, 1) in gw.writes, gw.writes
    assert state["selora-reseller"]["quarantined"] is False


def test_a6_threshold():
    state = {}
    gw = run("a6", [("a6-marketplace", "https://x", "sk")], True, state)
    assert gw.writes == [], gw.writes
    assert state["a6-marketplace"]["fails"] == 1


def test_permanent_no_recheck():
    state = {"a6-marketplace": {"rotation": [], "idx": 0, "fails": 3,
                                "quarantined": True, "permanent": True, "model": "gpt-6-astra"}}

    class DisabledGW(FakeGW):
        def find_channel(self, name):
            return 2, ["gpt-6-astra"], m.CHANNEL_MANUALLY_DISABLED

    class NoCall:
        @staticmethod
        def check(b, k, mo):
            raise AssertionError("should not be called")

        @staticmethod
        def verdict_category(r):
            return r["category"]

    gw = run("p", [("a6-marketplace", "https://x", "sk")], True, state, cc=NoCall(), gw=DisabledGW())
    assert gw.writes == []


def test_owner_reenable_clears_permanent():
    # Owner re-enables a permanently quarantined channel in the admin UI:
    # their call wins, our state clears, normal rotation resumes.
    state = {"a6-marketplace": {"rotation": [], "idx": 0, "fails": 3,
                                "quarantined": True, "permanent": True, "model": "gpt-6-astra"}}
    gw = run("op", [("a6-marketplace", "https://x", "sk")], True, state, cc=NoneCCTest())
    assert state["a6-marketplace"]["quarantined"] is False
    assert state["a6-marketplace"]["permanent"] is False


def test_owner_override():
    state = {"selora-reseller": {"rotation": [], "idx": 0, "fails": 3,
                                 "quarantined": True, "model": "x"}}
    gw = run("o", [("selora-reseller", "https://x", "sk")], False, state, cc=PassCCTest())
    assert state["selora-reseller"]["quarantined"] is False


def test_inconclusive_fail_open():
    state = {}
    gw = run("i", [("selora-reseller", "https://x", "sk")], True, state, cc=NoneCCTest())
    assert state["selora-reseller"]["fails"] == 0 and gw.writes == []


def test_observe_only_counts():
    state = {}
    gw = run("obs", [("selora-reseller", "https://x", "sk")], False, state)
    assert gw.writes == [] and state["selora-reseller"]["fails"] == 1


def test_traffic_gate_skips():
    class GateGW(FakeGW):
        def model_used_recently(self, cid, model, hours):
            return False

    state = {}
    gw = run("gate", [("selora-reseller", "https://x", "sk")], True, state, cc=NoneCCTest(), gw=GateGW())
    # Nothing checked (gate skipped all), no writes, no fails.
    assert gw.writes == [] and state["selora-reseller"]["fails"] == 0
    assert state["selora-reseller"]["idx"] == 1  # rotation still advances


def test_prefix_filter():
    state = {}
    gw = run("pf", [("selora-reseller", "https://x", "sk")], True, state)
    assert state["selora-reseller"]["rotation"] == ["claude-fable-5-1", "gpt-6-astra"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"ok {t.__name__}")
    print(f"ALL {len(tests)} DRY-RUN TESTS PASSED")
