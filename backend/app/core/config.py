from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kms:kms@postgres:5432/kms"

    # Wajib diisi lewat environment. Tidak ada nilai bawaan agar secret tidak ikut repo.
    secret_key: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    # Sesi berakhir bila tidak ada aktivitas selama nilai ini (token diperbarui tiap request terautentikasi).
    access_token_minutes: int = 30
    cookie_name: str = "access_token"
    cookie_secure: bool = False

    # ChromaDB (vector DB). Hanya dijangkau dari jaringan Docker, tidak dibuka ke host.
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_collection: str = "kms_chunks"

    # Ingest worker. Model bisa diganti lewat env; ganti model = index ulang semua dokumen.
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_batch_size: int = 32
    worker_poll_seconds: float = 5.0

    # Akun admin awal. Dibuat oleh seed hanya jika kedua nilai terisi dan belum ada user.
    seed_admin_email: str = ""
    seed_admin_password: str = ""
    seed_admin_name: str = "Administrator"


@lru_cache
def get_settings() -> Settings:
    return Settings()
