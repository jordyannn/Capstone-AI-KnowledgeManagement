"""Pencatatan log audit (F-15). Pemanggil yang melakukan commit, supaya catatan dan perubahan yang
dicatat tersimpan dalam transaksi yang sama (tidak ada aksi tanpa catatan, atau sebaliknya)."""

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    action: str,
    actor: User | None = None,
    *,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else actor_email,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
        )
    )
