"""Eskalasi ke staf (F-10): livechat bila ada staf online, tiket bila tidak.

Mahasiswa (prefix /api/support):
- GET  /status                     : apakah ada staf online (menentukan livechat atau tiket);
- POST /requests                   : buat permintaan bantuan. Jenisnya dipilih server dari status staf;
- GET  /requests                   : daftar permintaan milik sendiri;
- GET  /requests/{id}              : detail + pesan (dipolling halaman livechat);
- POST /requests/{id}/messages     : kirim pesan lanjutan.

Staf, yaitu peran admin/staf (prefix /api/admin/support):
- GET  /requests?status=           : antrean;
- GET  /requests/{id}              : detail + pesan + transkrip chat AI yang dilampirkan;
- POST /requests/{id}/messages     : balas (status menjadi "aktif", ditugaskan ke staf tersebut);
- POST /requests/{id}/close        : tutup ("selesai");
- GET/PUT /presence                : status online staf.

Pembaruan memakai polling, bukan WebSocket (MVP). Setiap request staf berlaku sebagai heartbeat:
staf dianggap online hanya bila toggle aktif DAN request terakhirnya kurang dari PRESENCE_TTL lalu,
supaya staf yang menutup tab tanpa mematikan toggle tidak membuat mahasiswa menunggu di livechat kosong.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import Conversation, StaffPresence, SupportMessage, SupportRequest, User
from app.models.support import (
    CATEGORIES,
    KIND_LIVECHAT,
    KIND_TICKET,
    SENDER_STAFF,
    SENDER_STUDENT,
    STAFF_ROLES,
    STATUS_ACTIVE,
    STATUS_CLOSED,
    STATUS_WAITING,
    STATUSES,
)

PRESENCE_TTL = timedelta(seconds=60)

router = APIRouter(prefix="/support", tags=["support"])
admin_router = APIRouter(prefix="/admin/support", tags=["support-admin"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # SQLite (dipakai test) mengembalikan datetime tanpa zona; nilainya tetap UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_staff(user: User) -> bool:
    return user.role.code in STAFF_ROLES


def staff_online(db: Session) -> bool:
    cutoff = _now() - PRESENCE_TTL
    return any(_aware(p.last_seen_at) >= cutoff for p in db.scalars(select(StaffPresence).where(StaffPresence.online)))


def require_staff(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if not is_staff(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hanya admin/staf yang dapat mengakses antrean.")
    presence = db.get(StaffPresence, user.id)
    if presence is not None:  # heartbeat
        presence.last_seen_at = _now()
        db.commit()
    return user


# ---------- skema ----------


class CreateRequest(BaseModel):
    category: str
    message: str = Field(min_length=2, max_length=4000)
    conversation_id: uuid.UUID | None = None

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"Kategori harus salah satu dari: {', '.join(CATEGORIES)}")
        return v

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("Pesan tidak boleh kosong.")
        return v.strip()


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Pesan tidak boleh kosong.")
        return v.strip()


class PresenceIn(BaseModel):
    online: bool


class SupportMessageOut(BaseModel):
    id: uuid.UUID
    sender_role: str
    sender_name: str
    content: str
    created_at: datetime


class RequestSummary(BaseModel):
    id: uuid.UUID
    kind: str
    category: str
    subject: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_message: str | None
    last_sender_role: str | None


class StudentInfo(BaseModel):
    id: int
    full_name: str
    email: str


class AdminRequestSummary(RequestSummary):
    student: StudentInfo
    assigned_staff_name: str | None


class TranscriptMessage(BaseModel):
    sender: str
    content: str
    escalated: bool
    created_at: datetime


class RequestDetail(RequestSummary):
    conversation_id: uuid.UUID | None
    closed_at: datetime | None
    assigned_staff_name: str | None
    staff_online: bool
    messages: list[SupportMessageOut]


class AdminRequestDetail(RequestDetail):
    student: StudentInfo
    ai_transcript: list[TranscriptMessage]


class StatusOut(BaseModel):
    staff_online: bool


class PresenceOut(BaseModel):
    online: bool
    staff_online: bool


# ---------- penyusun respons ----------


def _name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    return u.full_name if u else None


def _summary_fields(req: SupportRequest) -> dict:
    last = req.messages[-1] if req.messages else None
    return dict(
        id=req.id,
        kind=req.kind,
        category=req.category,
        subject=req.subject,
        status=req.status,
        created_at=req.created_at,
        updated_at=req.updated_at,
        last_message=last.content[:200] if last else None,
        last_sender_role=last.sender_role if last else None,
    )


def _messages(db: Session, req: SupportRequest) -> list[SupportMessageOut]:
    out = []
    for m in req.messages:
        name = _name(db, m.sender_id) or ("Mahasiswa" if m.sender_role == SENDER_STUDENT else "Staf")
        out.append(SupportMessageOut(id=m.id, sender_role=m.sender_role, sender_name=name, content=m.content, created_at=m.created_at))
    return out


def _detail_fields(db: Session, req: SupportRequest) -> dict:
    return dict(
        **_summary_fields(req),
        conversation_id=req.conversation_id,
        closed_at=req.closed_at,
        assigned_staff_name=_name(db, req.assigned_staff_id),
        staff_online=staff_online(db),
        messages=_messages(db, req),
    )


def _student(db: Session, req: SupportRequest) -> StudentInfo:
    u = db.get(User, req.student_id)
    return StudentInfo(id=u.id, full_name=u.full_name, email=u.email)


def _add_message(db: Session, req: SupportRequest, sender: User, role: str, content: str) -> None:
    if req.status == STATUS_CLOSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Percakapan ini sudah ditutup.")
    db.add(SupportMessage(request=req, sender_id=sender.id, sender_role=role, content=content))
    req.updated_at = _now()


# ---------- mahasiswa ----------


def _own_request(db: Session, user: User, request_id: uuid.UUID) -> SupportRequest:
    req = db.get(SupportRequest, request_id)
    # 404 juga untuk milik orang lain: tidak membocorkan bahwa id itu ada (NFR isolasi data).
    if req is None or req.student_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permintaan bantuan tidak ditemukan.")
    return req


@router.get("/status", response_model=StatusOut)
def support_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StatusOut:
    return StatusOut(staff_online=staff_online(db))


@router.post("/requests", response_model=RequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(body: CreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RequestDetail:
    if body.conversation_id is not None:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Percakapan tidak ditemukan.")
    kind = KIND_LIVECHAT if staff_online(db) else KIND_TICKET
    req = SupportRequest(
        student_id=user.id,
        conversation_id=body.conversation_id,
        kind=kind,
        category=body.category,
        subject=body.message.splitlines()[0][:200],
        status=STATUS_WAITING,
    )
    db.add(req)
    db.add(SupportMessage(request=req, sender_id=user.id, sender_role=SENDER_STUDENT, content=body.message))
    db.commit()
    db.refresh(req)
    return RequestDetail(**_detail_fields(db, req))


@router.get("/requests", response_model=list[RequestSummary])
def list_my_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[RequestSummary]:
    rows = db.scalars(
        select(SupportRequest).where(SupportRequest.student_id == user.id).order_by(SupportRequest.updated_at.desc()).limit(50)
    )
    return [RequestSummary(**_summary_fields(r)) for r in rows]


@router.get("/requests/{request_id}", response_model=RequestDetail)
def get_my_request(request_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RequestDetail:
    return RequestDetail(**_detail_fields(db, _own_request(db, user, request_id)))


@router.post("/requests/{request_id}/messages", response_model=RequestDetail)
def student_message(
    request_id: uuid.UUID, body: NewMessage, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RequestDetail:
    req = _own_request(db, user, request_id)
    _add_message(db, req, user, SENDER_STUDENT, body.content)
    db.commit()
    db.refresh(req)
    return RequestDetail(**_detail_fields(db, req))


# ---------- staf ----------


def _any_request(db: Session, request_id: uuid.UUID) -> SupportRequest:
    req = db.get(SupportRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permintaan bantuan tidak ditemukan.")
    return req


def _admin_detail(db: Session, req: SupportRequest) -> AdminRequestDetail:
    transcript: list[TranscriptMessage] = []
    if req.conversation_id is not None:
        conv = db.get(Conversation, req.conversation_id)
        if conv is not None:
            transcript = [
                TranscriptMessage(sender=m.sender, content=m.content, escalated=m.escalated, created_at=m.created_at)
                for m in conv.messages
            ]
    return AdminRequestDetail(**_detail_fields(db, req), student=_student(db, req), ai_transcript=transcript)


@admin_router.get("/requests", response_model=list[AdminRequestSummary])
def queue(
    status_filter: Literal["menunggu", "aktif", "selesai", "terbuka", "semua"] = Query("terbuka", alias="status"),
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> list[AdminRequestSummary]:
    q = select(SupportRequest)
    if status_filter == "terbuka":
        q = q.where(SupportRequest.status.in_((STATUS_WAITING, STATUS_ACTIVE)))
    elif status_filter in STATUSES:
        q = q.where(SupportRequest.status == status_filter)
    # Yang paling lama menunggu di atas, supaya antrean dilayani berurutan.
    order = SupportRequest.updated_at.desc() if status_filter in ("selesai", "semua") else SupportRequest.created_at.asc()
    rows = db.scalars(q.order_by(order).limit(200))
    return [
        AdminRequestSummary(**_summary_fields(r), student=_student(db, r), assigned_staff_name=_name(db, r.assigned_staff_id))
        for r in rows
    ]


@admin_router.get("/requests/{request_id}", response_model=AdminRequestDetail)
def admin_get_request(request_id: uuid.UUID, staff: User = Depends(require_staff), db: Session = Depends(get_db)) -> AdminRequestDetail:
    return _admin_detail(db, _any_request(db, request_id))


@admin_router.post("/requests/{request_id}/messages", response_model=AdminRequestDetail)
def staff_reply(
    request_id: uuid.UUID, body: NewMessage, staff: User = Depends(require_staff), db: Session = Depends(get_db)
) -> AdminRequestDetail:
    req = _any_request(db, request_id)
    _add_message(db, req, staff, SENDER_STAFF, body.content)
    req.status = STATUS_ACTIVE
    if req.assigned_staff_id is None:
        req.assigned_staff_id = staff.id
    db.commit()
    db.refresh(req)
    return _admin_detail(db, req)


@admin_router.post("/requests/{request_id}/close", response_model=AdminRequestDetail)
def close_request(request_id: uuid.UUID, staff: User = Depends(require_staff), db: Session = Depends(get_db)) -> AdminRequestDetail:
    req = _any_request(db, request_id)
    if req.status != STATUS_CLOSED:
        req.status = STATUS_CLOSED
        req.closed_at = _now()
        req.updated_at = req.closed_at
        if req.assigned_staff_id is None:
            req.assigned_staff_id = staff.id  # tercatat siapa yang menutup (bahan log audit F-15)
        db.commit()
        db.refresh(req)
    return _admin_detail(db, req)


@admin_router.get("/presence", response_model=PresenceOut)
def get_presence(staff: User = Depends(require_staff), db: Session = Depends(get_db)) -> PresenceOut:
    p = db.get(StaffPresence, staff.id)
    return PresenceOut(online=bool(p and p.online), staff_online=staff_online(db))


@admin_router.put("/presence", response_model=PresenceOut)
def set_presence(body: PresenceIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)) -> PresenceOut:
    p = db.get(StaffPresence, staff.id)
    if p is None:
        p = StaffPresence(user_id=staff.id)
        db.add(p)
    p.online = body.online
    p.last_seen_at = _now()
    db.commit()
    return PresenceOut(online=p.online, staff_online=staff_online(db))
