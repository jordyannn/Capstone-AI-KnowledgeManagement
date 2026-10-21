import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter(tags=["health"])


def check_chroma() -> bool:
    settings = get_settings()
    try:
        response = httpx.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/heartbeat", timeout=2.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        postgres_ok = True
    except SQLAlchemyError:
        postgres_ok = False
    chroma_ok = check_chroma()

    ok = postgres_ok and chroma_ok
    body = {
        "status": "ok" if ok else "degraded",
        "postgres": "ok" if postgres_ok else "down",
        "chromadb": "ok" if chroma_ok else "down",
    }
    return JSONResponse(body, status_code=200 if ok else 503)
