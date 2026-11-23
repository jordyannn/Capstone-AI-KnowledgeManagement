"""Tampilan log audit untuk admin/staf (F-15). Hanya baca; tidak ada endpoint ubah atau hapus.

GET /api/admin/audit?action=&limit=&before=
- action: saring per kode aksi (mis. "bantuan_tutup"); kosong = semua
- before: id entri; untuk memuat halaman berikutnya (entri yang lebih lama)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.support import require_staff
from app.core.db import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/admin/audit", tags=["audit"])


class AuditEntry(BaseModel):
    id: int
    created_at: datetime
    actor_email: str | None
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict


@router.get("", response_model=list[AuditEntry])
def list_audit(
    action: str | None = Query(None, max_length=32),
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, ge=1),
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> list[AuditEntry]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    if before:
        q = q.where(AuditLog.id < before)
    rows = list(db.scalars(q))
    names = {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_({r.actor_id for r in rows if r.actor_id})))}
    return [
        AuditEntry(
            id=r.id,
            created_at=r.created_at,
            actor_email=r.actor_email,
            actor_name=names.get(r.actor_id),
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            detail=r.detail or {},
        )
        for r in rows
    ]
