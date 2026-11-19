"""Measure a synthetic submission and poll to completion; never substitutes fixed timings."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--aws", action="store_true")
parser.add_argument("--timeout", type=int, default=240)
args = parser.parse_args()
base = args.url.rstrip("/")
payload = json.loads((Path(__file__).resolve().parents[1] / "backend" / "samples" / "web_form.json").read_text())
payload["patient_mrn"] = str(100000 + uuid.uuid4().int % 900000)
headers = {"Content-Type": "application/json"}
if not args.aws:
    from http.cookiejar import CookieJar
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    with opener.open(base + "/api/health") as response:
        headers["X-CSRFToken"] = json.load(response)["csrf"]
else:
    opener = urllib.request.build_opener()
path = "/orders?source=web_form" if args.aws else "/api/orders"
started = time.perf_counter()
with opener.open(urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers=headers)) as response:
    order = json.load(response)
accepted = time.perf_counter()
order_id = order.get("order_id", order.get("id"))
status_path = "/orders/" if args.aws else "/api/orders/"
while time.perf_counter() - started < args.timeout:
    with opener.open(base + status_path + order_id) as response:
        current = json.load(response)
    if current["status"] in ("completed", "failed"):
        break
    time.sleep(.5)
else:
    raise SystemExit("Timed out waiting for generation.")
print(json.dumps({"submission_ms": round((accepted-started)*1000, 2),
                  "observed_completion_s": round(time.perf_counter()-started, 2),
                  "provider_generation_ms": current.get("generation_ms"),
                  "status": current["status"]}, indent=2))
if current["status"] != "completed":
    raise SystemExit(1)
