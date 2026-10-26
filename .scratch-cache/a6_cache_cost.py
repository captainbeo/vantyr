"""A6 cost check: what does A6 actually bill us for cached tokens?

Reads our own A6 account log (/api/log/self) for the last WINDOW_H hours and,
per (model, merchant), reports:
  - the merchant's listed prices ($/1M): input, output, cache read, cache write
  - cache read as a % of input
  - token mix (uncached input / cache read / cache write / output)
  - what A6 charged (quota) vs. what the listed prices predict, so we can see
    whether cached tokens are billed at the cache-read price or full input.
Prints no key material.
"""
import json
import os
import time
import urllib.request
from collections import defaultdict

WINDOW_H = int(os.environ.get("WINDOW_H", "48"))
MAX_PAGES = int(os.environ.get("MAX_PAGES", "60"))
QUOTA_PER_USD = 500_000

base = os.environ.get("A6_MANAGE_BASE", "https://a6api.com").rstrip("/")
headers = {
    "Authorization": f"Bearer {os.environ['A6_MANAGE_TOKEN']}",
    "New-Api-User": os.environ["A6_MANAGE_USER"],
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def get(path):
    req = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


since = time.time() - WINDOW_H * 3600
rows = []
for page in range(1, MAX_PAGES + 1):
    payload = get(f"/api/log/self?p={page}&page_size=100&type=2")
    items = (payload.get("data") or {}).get("items") or []
    if not items:
        break
    rows.extend(i for i in items if (i.get("created_at") or 0) >= since)
    if (items[-1].get("created_at") or 0) < since:
        break
    time.sleep(0.3)

print(f"rows in last {WINDOW_H}h: {len(rows)}")

# One sample of the `other` keys, so we know which token fields exist.
for r in rows:
    try:
        o = json.loads(r.get("other") or "{}")
    except ValueError:
        continue
    if o.get("cache_tokens"):
        print("other keys (sample with cache):", sorted(o.keys()))
        break

agg = defaultdict(lambda: defaultdict(float))
listing = {}
for r in rows:
    try:
        o = json.loads(r.get("other") or "{}")
    except ValueError:
        continue
    if o.get("marketplace_price_charge_type") not in (None, "per_token"):
        continue
    key = (r.get("model_name"), str(o.get("marketplace_supplier_id") or r.get("channel")))
    inp = o.get("marketplace_price_input_micros") or 0
    if not inp:
        continue
    listing[key] = {
        "in": inp / 1e6,
        "out": (o.get("marketplace_price_output_micros") or 0) / 1e6,
        "cr": (o.get("marketplace_price_cache_read_micros") or 0) / 1e6,
        "cw": (o.get("marketplace_price_cache_write_micros") or 0) / 1e6,
        "cw1h": (o.get("marketplace_price_cache_write_1h_micros") or 0) / 1e6,
        "name": r.get("channel_name") or "",
    }
    a = agg[key]
    p = r.get("prompt_tokens") or 0
    c = r.get("completion_tokens") or 0
    cr = o.get("cache_tokens") or 0
    cw = o.get("cache_creation_tokens") or 0
    a["n"] += 1
    a["prompt"] += p
    a["out"] += c
    a["cr"] += cr
    a["cw"] += cw
    a["quota"] += r.get("quota") or 0
    L = listing[key]
    # Two readings of prompt_tokens: (A) excludes cache tokens (Anthropic
    # semantics), (B) includes them (OpenAI semantics). Predict the charge
    # both ways in $ and see which matches what A6 actually billed.
    pred_a = (p * L["in"] + cr * L["cr"] + cw * L["cw"] + c * L["out"]) / 1e6
    unc = max(p - cr - cw, 0)
    pred_b = (unc * L["in"] + cr * L["cr"] + cw * L["cw"] + c * L["out"]) / 1e6
    # Worst case for us: cache billed at FULL input price.
    pred_full = ((p if p >= cr + cw else p + cr + cw) * L["in"] + c * L["out"]) / 1e6
    a["pred_a"] += pred_a
    a["pred_b"] += pred_b
    a["pred_full"] += pred_full
    a["cache_read_usd"] += cr * L["cr"] / 1e6

print()
hdr = (f"{'model':<18} {'merchant':<8} {'n':>5} {'in$/M':>7} {'cr$/M':>8} {'cr%in':>6} "
       f"{'cw$/M':>7} | {'prompt':>10} {'cache_rd':>10} {'cache_wr':>9} {'out':>8} | "
       f"{'billed$':>8} {'predA$':>8} {'predB$':>8} {'full$':>8}")
print(hdr)
print("-" * len(hdr))
for key in sorted(agg, key=lambda k: (k[0] or "", -agg[k]["n"])):
    a, L = agg[key], listing[key]
    pct = (L["cr"] / L["in"] * 100) if L["in"] else 0
    print(f"{(key[0] or '')[:18]:<18} {key[1][:8]:<8} {int(a['n']):>5} {L['in']:>7.4f} {L['cr']:>8.5f} "
          f"{pct:>5.1f}% {L['cw']:>7.4f} | {int(a['prompt']):>10} {int(a['cr']):>10} {int(a['cw']):>9} "
          f"{int(a['out']):>8} | {a['quota']/QUOTA_PER_USD:>8.4f} {a['pred_a']:>8.4f} "
          f"{a['pred_b']:>8.4f} {a['pred_full']:>8.4f}")

# Per-model rollup: share of A6 cost that is cache read, and token mix.
print()
print("per-model rollup (last %dh):" % WINDOW_H)
models = defaultdict(lambda: defaultdict(float))
for (model, _), a in agg.items():
    for k, v in a.items():
        models[model][k] += v
for model, a in sorted(models.items(), key=lambda kv: -kv[1]["quota"]):
    billed = a["quota"] / QUOTA_PER_USD
    share = (a["cache_read_usd"] / billed * 100) if billed else 0
    print(f"  {model:<18} reqs={int(a['n']):>5} billed=${billed:.4f} "
          f"cache_read_tokens={int(a['cr']):>10} cache_read_cost=${a['cache_read_usd']:.4f} ({share:.1f}% of bill)")
