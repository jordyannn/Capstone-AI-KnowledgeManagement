"""Aturan akses dokumen saat retrieval. Dipakai ulang oleh SCRUM-44 (filter akses di RAG).

Satu dokumen punya daftar allowed_roles (kode peran dari tabel roles, atau "publik").
Aturannya sengaja minimal sampai matriks RBAC (SCRUM-25) final:
  - "publik" selalu boleh, termasuk untuk pengguna tanpa peran.
  - selain itu, peran pengguna harus tercantum persis di allowed_roles.
Belum ada pengecualian untuk Admin/Kaprodi; itu keputusan SCRUM-25, bukan di sini.
"""

from app.models.document import ROLE_PUBLIC

# ChromaDB tidak menerima list di metadata dan tidak bisa mencari substring di metadata,
# jadi tiap peran disimpan sebagai flag boolean: {"role_publik": True, "role_dosen": True}.
_FLAG_PREFIX = "role_"


def normalize_role(role: str | None) -> str | None:
    role = (role or "").strip().lower()
    return role or None


def role_flags(allowed_roles: list[str]) -> dict[str, bool]:
    """Metadata Chroma untuk sebuah dokumen: satu flag per peran yang boleh membacanya."""
    return {f"{_FLAG_PREFIX}{normalize_role(r)}": True for r in allowed_roles if normalize_role(r)}


def can_access(role: str | None, allowed_roles: list[str]) -> bool:
    allowed = {normalize_role(r) for r in allowed_roles}
    role = normalize_role(role)
    return ROLE_PUBLIC in allowed or (role is not None and role in allowed)


def build_role_where(role: str | None) -> dict:
    """Filter `where` ChromaDB: dokumen publik, ditambah dokumen yang mencantumkan peran ini."""
    role = normalize_role(role)
    public = {f"{_FLAG_PREFIX}{ROLE_PUBLIC}": True}
    if role is None or role == ROLE_PUBLIC:
        return public
    return {"$or": [public, {f"{_FLAG_PREFIX}{role}": True}]}
