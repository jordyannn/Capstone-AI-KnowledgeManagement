"""Chat dengan agen AI: retrieval -> Ollama -> jawaban + sitasi dokumen/halaman.

Dua endpoint dengan alur yang sama:
- POST /api/chat         : jawaban utuh (dipakai skrip evaluasi dan uji).
- POST /api/chat/stream  : Server-Sent Events. Teks dikirim per potongan selagi model menulis,
                           lalu satu event "done" berisi ChatResponse lengkap (sumber, eskalasi).

Belum ada: penyimpanan riwayat, klasifikasi niat lengkap, livechat, PII masking. Keputusan eskalasi:
tidak ada potongan yang cukup mirip, atau model menyatakan konteks tidak memuat jawabannya.
"""

import json
import re
from collections.abc import Iterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models import User

router = APIRouter(prefix="/chat", tags=["chat"])

NOT_FOUND = "TIDAK_DITEMUKAN"

SYSTEM_PROMPT = f"""Kamu adalah asisten layanan informasi administratif untuk mahasiswa Program Studi S1 Sistem Informasi Telkom University Jakarta.
Aturan:
1. Jawab HANYA berdasarkan KONTEKS yang diberikan. Jangan memakai pengetahuan lain dan jangan mengarang.
2. WAJIB: setiap kalimat yang memuat fakta diakhiri nomor sumber dalam kurung siku, misalnya [1] atau [2][3], sesuai nomor potongan konteks.
3. Pertahankan angka, tanggal, dan syarat persis seperti di konteks, termasuk pengecualiannya.
4. Jika konteks tidak memuat jawaban, atau pertanyaan di luar urusan administratif akademik, jawab tepat satu kata: {NOT_FOUND}
5. Jawab dalam Bahasa Indonesia yang jelas dan ringkas."""

NO_CONTEXT_ANSWER = "Maaf, informasi tersebut belum ditemukan di dokumen yang tersedia. Anda dapat menghubungi staf program studi."
NOT_FOUND_ANSWER = "Maaf, dokumen yang tersedia tidak memuat jawaban untuk pertanyaan ini. Anda dapat menghubungi staf program studi."


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class Source(BaseModel):
    number: int
    title: str
    page: int
    url: str
    score: float
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    escalate: bool
    reason: str | None = None


def _context(hits: list[dict]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        blocks.append(f"[{i}] {h['title']} (halaman {h['page_number']})\n{h['text']}")
    return "\n\n".join(blocks)


def _retrieve(question: str) -> list[dict]:
    settings = get_settings()
    try:
        r = httpx.post(f"{settings.rag_url}/search", json={"query": question, "k": settings.chat_top_k}, timeout=60)
        r.raise_for_status()
        return r.json()["hits"]
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Layanan pencarian belum siap.") from exc


def _no_context(hits: list[dict]) -> ChatResponse | None:
    # Hasil hybrid: potongan dari BM25 saja bisa ber-skor cosine 0, jadi ambang dipakai pada skor
    # tertinggi, bukan per potongan.
    if not hits or max(h["score"] for h in hits) < get_settings().chat_min_score:
        return ChatResponse(answer=NO_CONTEXT_ANSWER, sources=[], escalate=True, reason="tidak ada dokumen yang cukup relevan")
    return None


def _ollama_payload(question: str, hits: list[dict], stream: bool) -> dict:
    settings = get_settings()
    return {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"KONTEKS:\n{_context(hits)}\n\nPERTANYAAN: {question}"},
        ],
        "stream": stream,
        "keep_alive": settings.ollama_keep_alive,
        "options": {"num_ctx": settings.ollama_num_ctx, "temperature": 0.2},
    }


def _finalize(answer: str, hits: list[dict]) -> ChatResponse:
    answer = answer.strip()
    if NOT_FOUND in answer.upper():
        return ChatResponse(answer=NOT_FOUND_ANSWER, sources=[], escalate=True, reason="model menyatakan konteks tidak memuat jawaban")

    # Nomor di luar jumlah potongan (mis. [9] padahal konteks hanya 6) diabaikan.
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)} & set(range(1, len(hits) + 1))
    if not cited:
        # Model kecil kadang lupa menulis nomor sumber. Agar jawaban tetap bisa diverifikasi,
        # tampilkan 3 potongan konteks teratas sebagai sumber.
        cited = set(range(1, min(3, len(hits)) + 1))
    sources = [
        Source(
            number=i,
            title=h["title"],
            page=h["page_number"],
            url=h["source_url"],
            score=round(h["score"], 3),
            snippet=h["text"][:280],
        )
        for i, h in enumerate(hits, start=1)
        if i in cited
    ]
    return ChatResponse(answer=answer, sources=sources, escalate=False)


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, user: User = Depends(get_current_user)) -> ChatResponse:
    question = body.question.strip()
    hits = _retrieve(question)
    if (early := _no_context(hits)) is not None:
        return early
    settings = get_settings()
    try:
        r = httpx.post(f"{settings.ollama_url}/api/chat", json=_ollama_payload(question, hits, stream=False), timeout=settings.ollama_timeout_seconds)
        r.raise_for_status()
        answer = r.json()["message"]["content"]
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model bahasa tidak dapat dihubungi.") from exc
    return _finalize(answer, hits)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Potongan awal ditahan sampai jelas bukan "TIDAK_DITEMUKAN", supaya kata itu tidak sempat tampil.
_HOLD = len(NOT_FOUND) + 2


def _stream_answer(question: str, hits: list[dict]) -> Iterator[str]:
    settings = get_settings()
    answer = ""
    released = False
    try:
        with httpx.stream(
            "POST", f"{settings.ollama_url}/api/chat", json=_ollama_payload(question, hits, stream=True), timeout=settings.ollama_timeout_seconds
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                part = json.loads(line)
                piece = part.get("message", {}).get("content", "")
                answer += piece
                if not released:
                    head = answer.lstrip()
                    if len(head) >= _HOLD and not head.upper().startswith("TIDAK"):
                        released = True
                        yield _sse("token", {"text": answer})
                elif piece:
                    yield _sse("token", {"text": piece})
                if part.get("done"):
                    break
    except (httpx.HTTPError, json.JSONDecodeError):
        yield _sse("error", {"detail": "Model bahasa tidak dapat dihubungi."})
        return
    if not released and not answer.strip().upper().startswith("TIDAK"):
        yield _sse("token", {"text": answer})  # jawaban sangat pendek
    yield _sse("done", _finalize(answer, hits).model_dump())


@router.post("/stream")
def chat_stream(body: ChatRequest, user: User = Depends(get_current_user)) -> StreamingResponse:
    question = body.question.strip()
    hits = _retrieve(question)  # galat retrieval tetap jadi HTTP 503 biasa, sebelum stream dimulai
    early = _no_context(hits)

    def events() -> Iterator[str]:
        if early is not None:
            yield _sse("done", early.model_dump())
            return
        yield from _stream_answer(question, hits)

    # X-Accel-Buffering: Nginx meneruskan tiap event langsung, tidak ditahan di buffer.
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def warm_up_model() -> None:
    """Muat model ke GPU saat backend start, supaya pertanyaan pertama tidak menunggu ±2 menit."""
    settings = get_settings()
    try:
        httpx.post(
            f"{settings.ollama_url}/api/generate",
            json={"model": settings.ollama_model, "keep_alive": settings.ollama_keep_alive},
            timeout=settings.ollama_timeout_seconds,
        )
    except httpx.HTTPError:
        pass  # Ollama belum menyala: tidak fatal, model dimuat saat pertanyaan pertama
