from fastapi import APIRouter, FastAPI

from app.api import auth, health, sso

app = FastAPI(title="AI Knowledge Management System", docs_url="/api/docs", openapi_url="/api/openapi.json")

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(sso.router)
app.include_router(api)
