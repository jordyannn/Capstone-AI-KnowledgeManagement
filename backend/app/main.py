import threading

from fastapi import APIRouter, FastAPI

from app.api import auth, chat, health, sso

app = FastAPI(title="AI Knowledge Management System", docs_url="/api/docs", openapi_url="/api/openapi.json")

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(sso.router)
api.include_router(chat.router)
app.include_router(api)


@app.on_event("startup")
def _warm_up_llm() -> None:
    # Di thread terpisah: memuat model bisa +-2 menit dan tidak boleh menahan health check.
    threading.Thread(target=chat.warm_up_model, daemon=True).start()
