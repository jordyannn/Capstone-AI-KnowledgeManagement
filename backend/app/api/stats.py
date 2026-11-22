"""Pemantauan sederhana untuk admin/staf (UC-07, SCRUM-80).

GET /api/admin/stats?days=30
Angka dihitung dari percakapan MAHASISWA saja. Percakapan akun admin/staf (mis. skrip evaluasi yang
login sebagai admin) tidak dihitung, supaya angka mencerminkan pemakaian sebenarnya.
"""

import statistics
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.support import require_staff
from app.core.db import get_db
from app.models import Conversation, Message, Role, SupportMessage, SupportRequest, User
from app.models.chat import SENDER_ASSISTANT, SENDER_STUDENT
from app.models.support import SENDER_STAFF, STAFF_ROLES, STATUS_ACTIVE, STATUS_CLOSED, STATUS_WAITING

router = APIRouter(prefix="/admin/stats", tags=["stats"])


class DayCount(BaseModel):
    date: date
    questions: int
    escalated: int


class Stats(BaseModel):
    days: int
    questions: int
    students: int
    answered: int
    escalated: int
    escalated_pct: float
    feedback_up: int
    feedback_down: int
    support_waiting: int
    support_active: int
    support_closed: int
    support_livechat: int
    support_ticket: int
    first_reply_median_minutes: float | None
    by_category: dict[str, int]
    per_day: list[DayCount]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("", response_model=Stats)
def stats(
    days: int = Query(30, ge=1, le=365),
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
) -> Stats:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    student_ids = select(User.id).join(Role).where(Role.code.not_in(STAFF_ROLES))

    msgs = db.execute(
        select(Message.sender, Message.escalated, Message.feedback, Message.created_at, Conversation.user_id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id.in_(student_ids), Message.created_at >= since)
    ).all()
    questions = [m for m in msgs if m.sender == SENDER_STUDENT]
    answers = [m for m in msgs if m.sender == SENDER_ASSISTANT]
    escalated = sum(1 for m in answers if m.escalated)

    per_day: dict[date, list[int]] = {}
    for m in msgs:
        d = _aware(m.created_at).date()
        row = per_day.setdefault(d, [0, 0])
        if m.sender == SENDER_STUDENT:
            row[0] += 1
        elif m.escalated:
            row[1] += 1

    reqs = list(db.scalars(select(SupportRequest).where(SupportRequest.created_at >= since)))
    waits = []
    for r in reqs:
        first_staff = next((sm for sm in r.messages if sm.sender_role == SENDER_STAFF), None)
        if first_staff:
            waits.append((_aware(first_staff.created_at) - _aware(r.created_at)).total_seconds() / 60)
    by_category: dict[str, int] = {}
    for r in reqs:
        by_category[r.category] = by_category.get(r.category, 0) + 1

    return Stats(
        days=days,
        questions=len(questions),
        students=len({m.user_id for m in questions}),
        answered=len(answers) - escalated,
        escalated=escalated,
        escalated_pct=round(100 * escalated / len(answers), 1) if answers else 0.0,
        feedback_up=sum(1 for m in answers if m.feedback == "membantu"),
        feedback_down=sum(1 for m in answers if m.feedback == "tidak"),
        support_waiting=sum(1 for r in reqs if r.status == STATUS_WAITING),
        support_active=sum(1 for r in reqs if r.status == STATUS_ACTIVE),
        support_closed=sum(1 for r in reqs if r.status == STATUS_CLOSED),
        support_livechat=sum(1 for r in reqs if r.kind == "livechat"),
        support_ticket=sum(1 for r in reqs if r.kind == "tiket"),
        first_reply_median_minutes=round(statistics.median(waits), 1) if waits else None,
        by_category=by_category,
        per_day=[DayCount(date=d, questions=v[0], escalated=v[1]) for d, v in sorted(per_day.items())],
    )
