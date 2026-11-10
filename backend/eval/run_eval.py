"""Evaluasi agen chat dengan set uji (eval_set.jsonl).

Mengukur per pertanyaan:
- retrieval: peringkat potongan pertama yang berasal dari sumber yang benar (top-1/top-3/top-6, MRR);
- jawaban: kata kunci wajib muncul (`must`: daftar grup, tiap grup cukup salah satu);
- sitasi: minimal satu sumber yang dikembalikan cocok dengan sumber yang benar;
- eskalasi: sesuai harapan (answer / escalate / answer_or_escalate);
- waktu respons end-to-end.

Dijalankan di dalam container backend (bisa menjangkau layanan rag dan API backend):
    docker compose cp backend/eval backend:/tmp/eval
    docker compose exec -T -e EVAL_EMAIL=... -e EVAL_PASSWORD=... backend python /tmp/eval/run_eval.py [--label nama] [--only id1,id2]
Hasil disimpan sebagai JSON di /tmp/eval-results/ (salin balik ke backend/eval/results/ dengan `docker compose cp`).
"""

import argparse
import json
import os
import pathlib
import statistics
import time
import unicodedata

import httpx

HERE = pathlib.Path(__file__).parent
API = os.environ.get("EVAL_API", "http://127.0.0.1:8000/api")
RAG = os.environ.get("EVAL_RAG", "http://rag:8001")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).lower()
    return " ".join(s.replace("–", "-").split())


def source_match(title: str, page: int, expected: list[dict]) -> bool:
    for e in expected:
        if norm(e["title"]) in norm(title) and (not e["pages"] or page in e["pages"]):
            return True
    return False


def retrieval_rank(question: str, expected: list[dict], k: int = 6) -> int | None:
    r = httpx.post(f"{RAG}/search", json={"query": question, "k": k}, timeout=120)
    r.raise_for_status()
    for i, h in enumerate(r.json()["hits"], start=1):
        if source_match(h["title"], h["page_number"], expected):
            return i
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-chat", action="store_true", help="hanya ukur retrieval")
    args = ap.parse_args()

    items = [json.loads(l) for l in (HERE / "eval_set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only:
        keep = set(args.only.split(","))
        items = [i for i in items if i["id"] in keep]

    client = httpx.Client(timeout=600)
    if not args.no_chat:
        r = client.post(f"{API}/auth/login", json={"email": os.environ["EVAL_EMAIL"], "password": os.environ["EVAL_PASSWORD"]})
        r.raise_for_status()

    rows = []
    for it in items:
        row = {"id": it["id"], "topic": it["topic"], "expect": it["expect"]}
        if it["sources"]:
            row["rank"] = retrieval_rank(it["question"], it["sources"])
        if not args.no_chat:
            t = time.time()
            r = client.post(f"{API}/chat", json={"question": it["question"]})
            row["seconds"] = round(time.time() - t, 1)
            r.raise_for_status()
            body = r.json()
            ans = norm(body["answer"])
            row["escalate"] = body["escalate"]
            row["answer"] = body["answer"][:400]
            row["cited"] = [f'{s["title"][:40]} hal. {s["page"]}' for s in body["sources"]]
            row["keywords_ok"] = all(any(norm(k) in ans for k in grp) for grp in it["must"]) if it["must"] else None
            row["citation_ok"] = (
                any(source_match(s["title"], s["page"], it["sources"]) for s in body["sources"]) if it["sources"] else None
            )
            if it["expect"] == "escalate":
                row["pass"] = body["escalate"]
            elif it["expect"] == "answer":
                row["pass"] = (not body["escalate"]) and bool(row["keywords_ok"]) and bool(row["citation_ok"])
            else:  # answer_or_escalate
                row["pass"] = body["escalate"] or (bool(row["keywords_ok"]) and bool(row["citation_ok"]))
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("id", "rank", "pass", "escalate", "keywords_ok", "citation_ok", "seconds")}, ensure_ascii=False), flush=True)

    ranked = [r for r in rows if "rank" in r]
    summary = {
        "label": args.label,
        "n": len(rows),
        "retrieval_n": len(ranked),
        "top1": sum(1 for r in ranked if r["rank"] == 1),
        "top3": sum(1 for r in ranked if r["rank"] and r["rank"] <= 3),
        "top6": sum(1 for r in ranked if r["rank"]),
        "mrr": round(sum(1 / r["rank"] for r in ranked if r["rank"]) / max(len(ranked), 1), 3),
    }
    if not args.no_chat:
        secs = [r["seconds"] for r in rows]
        summary.update(
            {
                "pass": sum(1 for r in rows if r["pass"]),
                "answer_pass": sum(1 for r in rows if r["expect"] == "answer" and r["pass"]),
                "answer_n": sum(1 for r in rows if r["expect"] == "answer"),
                "false_escalate": sum(1 for r in rows if r["expect"] == "answer" and r["escalate"]),
                "missed_escalate": sum(1 for r in rows if r["expect"] == "escalate" and not r["escalate"]),
                "seconds_median": statistics.median(secs),
                "seconds_max": max(secs),
            }
        )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    out = pathlib.Path(os.environ.get("EVAL_OUT", "/tmp/eval-results"))
    out.mkdir(exist_ok=True)
    (out / f"{time.strftime('%Y%m%d-%H%M')}-{args.label}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
