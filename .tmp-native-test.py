#!/usr/bin/env python3
"""Test BEpusdt's NATIVE create-order API: EpusdtSign = sorted non-empty
k=v&k=v (excluding signature) + token, MD5. Creates an order with
currencies=USDT,USDC (no trade_type) → cashier should offer network
reselect. Inspects the response + the pay/info 'reselect' flag."""
import hashlib
import json
import time
import urllib.request

key = open("/tmp/at.txt").read().strip()

params = {
    "order_id": f"NATIVEPROBE{int(time.time())}",
    "notify_url": "https://vantyr.xyz/api/user/epay/notify",
    "redirect_url": "https://vantyr.xyz/usage-logs",
    "amount": 1.00,
    "name": "TUC1",
    "fiat": "USD",
    "currencies": "USDT,USDC",
    "timeout": 900,
}
# EpusdtSign: exclude 'signature', sorted keys, skip empty/nil, k=v joined by &
sign_str = "&".join(
    f"{k}={params[k]}" for k in sorted(params) if params[k] != "" and params[k] is not None
)
sign = hashlib.md5((sign_str + key).encode()).hexdigest()
body = {**params, "signature": sign}

req = urllib.request.Request(
    "https://pay2.vantyr.xyz/api/v1/order/create-order",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    resp = urllib.request.urlopen(req, timeout=20)
    data = json.loads(resp.read())
    d = data.get("data", {})
    print("status:", resp.status, "trade_id:", d.get("trade_id"))
    print("payment_url:", d.get("payment_url"))
    trade_id = d.get("trade_id")

    # query pay/info to see reselect + methods
    info_req = urllib.request.Request(
        "https://pay2.vantyr.xyz/api/v1/pay/info",
        data=json.dumps({"trade_id": trade_id}).encode(),
        headers={"Content-Type": "application/json"},
    )
    info = json.loads(urllib.request.urlopen(info_req, timeout=20).read())
    dd = info.get("data", {})
    print("reselect:", dd.get("reselect"))
    print("networks offered:", [m.get("name") for m in (dd.get("network") or [])][:12])
    print("fiat:", dd.get("fiat"), "money:", dd.get("money"), "trade_type:", dd.get("trade_type", "(none)"))
except urllib.error.HTTPError as e:
    print("error:", e.code, e.read().decode()[:300])
except Exception as e:
    print("ERR:", e)
