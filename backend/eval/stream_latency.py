"""Ukur waktu sampai kata pertama tampil (time to first token) dan waktu selesai pada /api/chat/stream.

    docker compose exec -T -e EVAL_EMAIL=... -e EVAL_PASSWORD=... backend python /tmp/eval/stream_latency.py
"""

import json
import os
import pathlib
import statistics
import time

import httpx

API = os.environ.get("EVAL_API", "http://127.0.0.1:8000/api")
HERE = pathlib.Path(__file__).parent

items = [json.loads(l) for l in (HERE / "eval_set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
c = httpx.Client(timeout=600)
c.post(f"{API}/auth/login", json={"email": os.environ["EVAL_EMAIL"], "password": os.environ["EVAL_PASSWORD"]}).raise_for_status()

first, total = [], []
for it in items:
    if it["expect"] != "answer":
        continue
    t = time.time()
    ttft = None
    with c.stream("POST", f"{API}/chat/stream", json={"question": it["question"]}) as r:
        for line in r.iter_lines():
            if line.startswith("event: token") and ttft is None:
                ttft = time.time() - t
    done = time.time() - t
    total.append(done)
    if ttft is not None:
        first.append(ttft)
    print(f'{it["id"]:10} first={ttft and round(ttft, 1)} done={done:.1f}', flush=True)

print("SUMMARY", json.dumps({
    "n": len(total),
    "first_token_median": round(statistics.median(first), 1),
    "first_token_max": round(max(first), 1),
    "done_median": round(statistics.median(total), 1),
}))
