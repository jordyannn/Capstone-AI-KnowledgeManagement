"""Chat dengan agen AI: retrieval -> Ollama -> jawaban + sitasi dokumen/halaman.

Dua endpoint dengan alur yang sama:
- POST /api/chat         : jawaban utuh (dipakai skrip evaluasi dan uji).
- POST /api/chat/stream  : Server-Sent Events. Teks dikirim per potongan selagi model menulis,
                           lalu satu event "done" berisi ChatResponse lengkap (sumber, eskalasi).

Setiap tanya-jawab disimpan sebagai riwayat (F-11): kirim `conversation_id` untuk melanjutkan
percakapan, atau kosongkan untuk memulai percakapan baru. Riwayat dibaca lewat
GET /api/chat/conversations dan GET /api/chat/conversations/{id}.

Belum ada: klasifikasi niat lengkap, livechat, PII masking. Keputusan eskalasi: tidak ada potongan
yang cukup mirip, atau model menyatakan konteks tidak memuat jawabannya.
"""

import json
import logging
import re
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.api.citations import fix_citations
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.pii import mask as mask_pii
from app.core.db import get_db
from app.models import Conversation, Message, User
from app.models.chat import SENDER_ASSISTANT, SENDER_STUDENT

router = APIRouter(prefix="/chat", tags=["chat"])
log = logging.getLogger("chat")

NOT_FOUND = "TIDAK_DITEMUKAN"

SYSTEM_PROMPT = f"""Kamu adalah asisten layanan informasi administratif untuk mahasiswa Program Studi S1 Sistem Informasi Telkom University Jakarta.
Aturan:
1. Jawab HANYA berdasarkan KONTEKS yang diberikan. Jangan memakai pengetahuan lain dan jangan mengarang.
2. WAJIB: setiap kalimat yang memuat fakta diakhiri nomor sumber dalam kurung siku, misalnya [1] atau [2][3], sesuai nomor potongan konteks.
3. Pertahankan angka, tanggal, dan syarat persis seperti di konteks, termasuk pengecualiannya.
4. Jika konteks tidak memuat jawaban, atau pertanyaan di luar urusan administratif akademik, jawab tepat satu kata: {NOT_FOUND}
5. Jika aturan di konteks berbeda per jenjang (diploma, sarjana, magister, doktor, ekstensi, PJJ), jawab untuk mahasiswa sarjana (S1) reguler kecuali pertanyaan menyebut jenjang lain, dan sebutkan jenjangnya. Jangan menggabungkan aturan dari jenjang yang berbeda.
6. Jawab dalam Bahasa Indonesia yang jelas dan ringkas, dengan kalimat lengkap."""

NO_CONTEXT_ANSWER = "Maaf, informasi tersebut belum ditemukan di dokumen yang tersedia. Anda dapat menghubungi staf program studi."
NOT_FOUND_ANSWER = "Maaf, dokumen yang tersedia tidak memuat jawaban untuk pertanyaan ini. Anda dapat menghubungi staf program studi."


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: uuid.UUID | None = None  # kosong = percakapan baru
    # Kode model yang dipilih pengguna (lihat GET /api/chat/models). Kosong = model lokal.
    model: str | None = Field(default=None, max_length=32)


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
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    # Jenis data pribadi yang disamarkan dari pertanyaan (F-14), mis. ["NOMOR_IDENTITAS"]. Ditampilkan
    # sebagai pemberitahuan di UI.
    masked: list[str] = []
    # Model yang benar-benar menjawab, mis. "Lokal (qwen2.5:7b)" atau "Groq (llama-3.3-70b-versatile)".
    # llm_note terisi bila berbeda dari pilihan pengguna (mis. pertanyaan sensitif dipaksa ke lokal).
    llm_used: str | None = None
    llm_note: str | None = None


class ModelOption(BaseModel):
    code: str
    label: str
    model: str
    local: bool


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


class StoredMessage(BaseModel):
    id: uuid.UUID
    sender: str
    content: str
    sources: list[Source]
    escalated: bool
    reason: str | None
    feedback: str | None
    llm_used: str | None = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _own_conversation(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    # 404 juga untuk percakapan milik orang lain: tidak membocorkan bahwa id itu ada (NFR isolasi data).
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Percakapan tidak ditemukan.")
    return conv


def _open_conversation(db: Session, user: User, body: ChatRequest, question: str) -> Conversation:
    """Ambil percakapan lama atau buat yang baru, lalu simpan pertanyaan mahasiswa."""
    if body.conversation_id is not None:
        conv = _own_conversation(db, user, body.conversation_id)
    else:
        conv = Conversation(user_id=user.id, title=question[:80])
        db.add(conv)
    conv.updated_at = _now()
    db.add(Message(conversation=conv, sender=SENDER_STUDENT, content=question, sources=[]))
    db.commit()
    return conv


def _save_answer(db: Session, conv: Conversation, resp: ChatResponse) -> ChatResponse:
    msg = Message(
        conversation=conv,
        sender=SENDER_ASSISTANT,
        content=resp.answer,
        sources=[s.model_dump() for s in resp.sources],
        escalated=resp.escalate,
        reason=resp.reason,
        llm_used=resp.llm_used,
    )
    db.add(msg)
    conv.updated_at = _now()
    db.commit()
    return resp.model_copy(update={"conversation_id": conv.id, "message_id": msg.id})


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


def _messages(question: str, hits: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"KONTEKS:\n{_context(hits)}\n\nPERTANYAAN: {question}"},
    ]


def _provider_fields(provider: llm.Provider, note: str | None) -> dict:
    return {"llm_used": llm.label(provider), "llm_note": note}


def _normalize(answer: str) -> str:
    """Seragamkan keluaran antar model. gpt-oss (Groq) menulis sitasi sebagai 【4】 atau 【4†sumber】 dan
    memakai **tebal** Markdown, sedangkan UI menampilkan teks polos dan pemeriksa sitasi mencari [4]."""
    answer = re.sub(r"\s*【(\d+)(?:†[^】]*)?】", r" [\1]", answer)
    return answer.replace("**", "")


def _finalize(answer: str, hits: list[dict]) -> ChatResponse:
    answer = _normalize(answer).strip()
    if NOT_FOUND in answer.upper():
        return ChatResponse(answer=NOT_FOUND_ANSWER, sources=[], escalate=True, reason="model menyatakan konteks tidak memuat jawaban")

    # Sitasi diperiksa per kalimat: angka di kalimat harus ada di potongan yang dikutip, kalau tidak
    # dipindah ke potongan yang memuatnya. Nomor di luar jumlah potongan dibuang, dan potongan dari
    # dokumen + halaman yang sama digabung (lihat app/api/citations.py).
    answer, cited_list = fix_citations(answer, hits)
    cited = set(cited_list)
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
def chat(body: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ChatResponse:
    # Data pribadi (NIM, telepon, surel, ...) disamarkan sebelum disimpan, dicari, dan dikirim ke model (F-14).
    question, masked = mask_pii(body.question.strip())
    # Pertanyaan yang memuat data pribadi/sensitif selalu ke model lokal (lihat app/llm.py).
    provider, note = llm.choose(body.model, body.question, masked)
    conv = _open_conversation(db, user, body, question)
    hits = _retrieve(question)
    if (early := _no_context(hits)) is not None:
        return _save_answer(db, conv, early.model_copy(update={"masked": masked}))
    try:
        answer = llm.generate(provider, _messages(question, hits))
    except llm.LLMError as exc:
        if provider.code == llm.LOCAL:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model bahasa tidak dapat dihubungi.") from exc
        # Model cloud gagal atau kena batas kuota (free tier Groq: 8.000 token/menit, ±2–3 pertanyaan):
        # jawaban tetap diberikan oleh model lokal, supaya layanan tetap tersedia.
        log.warning("model %s gagal (%s), dialihkan ke lokal", provider.code, exc)
        provider, note = llm.local(), f"{provider.label} sedang tidak tersedia ({exc.reason}), dijawab model lokal"
        try:
            answer = llm.generate(provider, _messages(question, hits))
        except llm.LLMError as exc2:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model bahasa tidak dapat dihubungi.") from exc2
    resp = _finalize(answer, hits).model_copy(update={"masked": masked, **_provider_fields(provider, note)})
    return _save_answer(db, conv, resp)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# Potongan awal ditahan sampai jelas bukan "TIDAK_DITEMUKAN", supaya kata itu tidak sempat tampil.
_HOLD = len(NOT_FOUND) + 2


def _stream_answer(question: str, hits: list[dict], provider: llm.Provider, note: str | None = None) -> Iterator[str | ChatResponse]:
    """Menghasilkan event SSE "token"/"error" (str), lalu ChatResponse final sebagai item terakhir.

    Bila model cloud gagal sebelum mengirim teks apa pun (mis. batas kuota), dialihkan ke model lokal.
    """
    if provider.code != llm.LOCAL:
        pieces = llm.stream(provider, _messages(question, hits))
        try:
            first = next(pieces, "")
        except llm.LLMError as exc:
            log.warning("model %s gagal (%s), dialihkan ke lokal", provider.code, exc)
            note = f"{provider.label} sedang tidak tersedia ({exc.reason}), dijawab model lokal"
            provider = llm.local()
        else:
            yield from _relay(question, hits, provider, note, _chain(first, pieces))
            return
    yield from _relay(question, hits, provider, note, llm.stream(provider, _messages(question, hits)))


def _chain(first: str, rest: Iterator[str]) -> Iterator[str]:
    if first:
        yield first
    yield from rest


def _relay(question: str, hits: list[dict], provider: llm.Provider, note: str | None, pieces: Iterator[str]) -> Iterator[str | ChatResponse]:
    answer = ""
    released = False
    try:
        for piece in pieces:
            answer += piece
            if not released:
                head = answer.lstrip()
                if len(head) >= _HOLD and not head.upper().startswith("TIDAK"):
                    released = True
                    yield _sse("token", {"text": answer})
            else:
                yield _sse("token", {"text": piece})
    except llm.LLMError:
        yield _sse("error", {"detail": "Model bahasa tidak dapat dihubungi."})
        return
    if not released and not answer.strip().upper().startswith("TIDAK"):
        yield _sse("token", {"text": answer})  # jawaban sangat pendek
    yield _finalize(answer, hits).model_copy(update=_provider_fields(provider, note))


@router.post("/stream")
def chat_stream(body: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    question, masked = mask_pii(body.question.strip())  # F-14, lihat endpoint non-streaming
    provider, note = llm.choose(body.model, body.question, masked)
    conv = _open_conversation(db, user, body, question)
    hits = _retrieve(question)  # galat retrieval tetap jadi HTTP 503 biasa, sebelum stream dimulai
    early = _no_context(hits)

    # Session `db` tetap dipakai di generator setelah dependency selesai: Session SQLAlchemy yang
    # sudah di-close dibuka ulang otomatis saat dipakai lagi.
    def events() -> Iterator[str]:
        if early is not None:
            yield _sse("done", _save_answer(db, conv, early.model_copy(update={"masked": masked})).model_dump(mode="json"))
            return
        for item in _stream_answer(question, hits, provider, note):
            if isinstance(item, ChatResponse):
                final = item.model_copy(update={"masked": masked})
                yield _sse("done", _save_answer(db, conv, final).model_dump(mode="json"))
            else:
                yield item

    # X-Accel-Buffering: Nginx meneruskan tiap event langsung, tidak ditahan di buffer.
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/models", response_model=list[ModelOption])
def list_models(user: User = Depends(get_current_user)) -> list[ModelOption]:
    """Model yang bisa dipilih. Lokal selalu pertama; komersial hanya bila diaktifkan dan punya API key."""
    return [ModelOption(code=p.code, label=p.label, model=p.model, local=p.code == llm.LOCAL) for p in llm.available()]


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Conversation]:
    rows = db.scalars(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).limit(50)
    )
    return list(rows)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Conversation:
    return _own_conversation(db, user, conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    db.delete(_own_conversation(db, user, conversation_id))
    db.commit()


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
