"""Chat dengan agen AI (versi awal): retrieval -> Ollama -> jawaban + sitasi dokumen/halaman.

Belum ada: penyimpanan riwayat, klasifikasi niat lengkap, livechat, PII masking. Keputusan eskalasi
versi awal: tidak ada potongan yang cukup mirip, atau model menyatakan konteks tidak memuat jawabannya.
"""

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
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


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest, user: User = Depends(get_current_user)) -> ChatResponse:
    settings = get_settings()
    question = body.question.strip()
    try:
        r = httpx.post(f"{settings.rag_url}/search", json={"query": question, "k": settings.chat_top_k}, timeout=60)
        r.raise_for_status()
        hits = r.json()["hits"]
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Layanan pencarian belum siap.") from exc

    # Hasil hybrid: potongan dari BM25 saja bisa ber-skor cosine 0, jadi ambang dipakai pada skor
    # tertinggi, bukan per potongan.
    if not hits or max(h["score"] for h in hits) < settings.chat_min_score:
        return ChatResponse(
            answer="Maaf, informasi tersebut belum ditemukan di dokumen yang tersedia. Anda dapat menghubungi staf program studi.",
            sources=[],
            escalate=True,
            reason="tidak ada dokumen yang cukup relevan",
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"KONTEKS:\n{_context(hits)}\n\nPERTANYAAN: {question}"},
    ]
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"num_ctx": settings.ollama_num_ctx, "temperature": 0.2},
            },
            timeout=settings.ollama_timeout_seconds,
        )
        r.raise_for_status()
        answer = r.json()["message"]["content"].strip()
    except (httpx.HTTPError, KeyError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model bahasa tidak dapat dihubungi.") from exc

    if NOT_FOUND in answer.upper():
        return ChatResponse(
            answer="Maaf, dokumen yang tersedia tidak memuat jawaban untuk pertanyaan ini. Anda dapat menghubungi staf program studi.",
            sources=[],
            escalate=True,
            reason="model menyatakan konteks tidak memuat jawaban",
        )

    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
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
