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
import re
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


def fact_citation_ok(answer: str, sources: list[dict], must: list[list[str]], expected: list[dict]) -> bool | None:
    """Lebih ketat dari citation_ok: kalimat yang memuat kata kunci wajib harus mengutip sumber yang benar.

    citation_ok lolos asal SALAH SATU sumber yang dikutip cocok, sehingga "60 poin [3]" dengan [3] halaman
    yang salah tetap lolos bila ada sumber lain yang benar. Di sini, untuk tiap grup kata kunci, dicari
    kalimat yang memuatnya, lalu nomor sitasi di kalimat itu harus menunjuk dokumen + halaman yang benar.
    """
    if not must or not expected:
        return None
    by_number = {s["number"]: s for s in sources}
    # Sama dengan app/api/citations.py: titik setelah angka (nomor daftar) bukan batas kalimat, dan
    # potongan yang hanya berisi nomor sitasi ("... 2026. [2]") ikut kalimat sebelumnya.
    sentences: list[str] = []
    for line in answer.split("\n"):
        for s in re.split(r"(?<=[^\d\s][.!?])[ \t]+", line):
            if re.fullmatch(r"\s*(\[\d+\]\s*)+[.!?]?\s*", s) and sentences:
                sentences[-1] += " " + s
            elif s.strip():
                sentences.append(s)
    for grp in must:
        hit_sentences = [s for s in sentences if any(norm(k) in norm(s) for k in grp)]
        if not hit_sentences:
            return False
        ok = False
        for s in hit_sentences:
            for n in re.findall(r"\[(\d+)\]", s):
                src = by_number.get(int(n))
                if src and source_match(src["title"], src["page"], expected):
                    ok = True
        if not ok:
            return False
    return True


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
            row["fact_citation_ok"] = (
                fact_citation_ok(body["answer"], body["sources"], it["must"], it["sources"]) if not body["escalate"] else None
            )
            if it["expect"] == "escalate":
                row["pass"] = body["escalate"]
            elif it["expect"] == "answer":
                row["pass"] = (not body["escalate"]) and bool(row["keywords_ok"]) and bool(row["citation_ok"])
            else:  # answer_or_escalate
                row["pass"] = body["escalate"] or (bool(row["keywords_ok"]) and bool(row["citation_ok"]))
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("id", "rank", "pass", "escalate", "keywords_ok", "citation_ok", "fact_citation_ok", "seconds")}, ensure_ascii=False), flush=True)

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
                # Lolos + kalimat berisi kata kunci mengutip sumber yang benar (metrik ketat, sejak 22 Nov).
                "strict_pass": sum(1 for r in rows if r["pass"] and r.get("fact_citation_ok") is not False),
                "fact_citation_ok": sum(1 for r in rows if r.get("fact_citation_ok") is True),
                "fact_citation_n": sum(1 for r in rows if r.get("fact_citation_ok") is not None),
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
