import json
import os
import urllib.request

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


payload = get("/api/log/self?p=1&page_size=3&type=2")
print("success:", payload.get("success"), "message:", payload.get("message"))
data = payload.get("data") or {}
print("total rows:", data.get("total"))
items = data.get("items") or []
for item in items[:2]:
    # Never print key material; token_name is a label only.
    item.pop("token_key", None)
    print(json.dumps(item, ensure_ascii=False, indent=1)[:2500])
    print("---")
