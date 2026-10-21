from functools import lru_cache

from pydantic import Field, model_validator
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

    # Login SSO Microsoft Entra ID (OIDC). Mati bawaannya; login lokal tetap ada.
    # Client secret hanya boleh ada di environment/.env, tidak pernah di kode.
    sso_enabled: bool = False
    sso_client_id: str = ""
    sso_client_secret: str = ""
    # ID tenant Entra ID Tel-U (publik, bukan rahasia). Login dari tenant lain ditolak.
    sso_tenant_id: str = "90affe0f-c2a3-4108-bb98-6ceb4e94ef15"
    sso_redirect_uri: str = "http://localhost:8080/api/auth/sso/callback"
    # Dipisah koma. Dicocokkan persis dengan bagian setelah "@", bukan sekadar akhiran.
    sso_allowed_domains: str = "telkomuniversity.ac.id,student.telkomuniversity.ac.id"

    @property
    def sso_domains(self) -> set[str]:
        return {d.strip().lower() for d in self.sso_allowed_domains.split(",") if d.strip()}

    @model_validator(mode="after")
    def _sso_needs_credentials(self) -> "Settings":
        # Gagal saat start, bukan saat pengguna pertama menekan tombolnya.
        if self.sso_enabled and not (self.sso_client_id and self.sso_client_secret):
            raise ValueError("SSO_ENABLED=true membutuhkan SSO_CLIENT_ID dan SSO_CLIENT_SECRET.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
