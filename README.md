# AI Knowledge Management System

Capstone Kelompok 31, Prodi S1 Sistem Informasi, Telkom University Jakarta.

Status saat ini: kerangka minimal + **SCRUM-28 (F-01 Login dan logout pengguna)**.
Worker ingest, ChromaDB, dan Ollama belum ada di repo ini.

## Arsitektur (yang sudah ada)

```
Browser -> Nginx (:HTTP_PORT)
             |-- /      -> Frontend (Next.js)
             '-- /api/  -> Backend (FastAPI) -> PostgreSQL
```

## Prasyarat

- **Git**
- **Docker Desktop**, dan harus dalam keadaan **berjalan** (ikon paus di system tray,
  status *Engine running*) sebelum menjalankan perintah `docker compose` apa pun.

Python dan Node.js di komputer **tidak diperlukan** untuk menjalankan aplikasi maupun test.

## Menjalankan (pertama kali)

```powershell
git clone https://github.com/jordyannn/Capstone-AI-KnowledgeManagement.git
cd Capstone-AI-KnowledgeManagement

copy .env.example .env      # Windows PowerShell. Di Git Bash/Linux/macOS: cp .env.example .env
```

Buka `.env` lalu ganti semua nilai `ganti-dengan-...`:

| Variabel | Isi |
|---|---|
| `POSTGRES_PASSWORD` | Sandi database, bebas |
| `SECRET_KEY` | String acak minimal 32 karakter. Jangan dibiarkan seperti contoh |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | Akun admin untuk login pertama |

Lalu jalankan:

```powershell
docker compose up -d --build
```

Build pertama memakan beberapa menit karena mengunduh image. Setelah selesai, buka
**http://localhost:8080** dan masuk dengan `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`.

> Satu-satunya akun saat ini adalah admin dari seed. Peran Kaprodi, Dosen, Staf Administrasi,
> dan Mahasiswa sudah ada di tabel `roles`, tetapi belum ada penggunanya. Pembuatan pengguna
> lewat UI belum dikerjakan.

## Sehari-hari

| Keperluan | Perintah |
|---|---|
| Menjalankan | `docker compose up -d` |
| Setelah `git pull` atau mengubah kode | `docker compose up -d --build` |
| Melihat status | `docker compose ps` |
| Melihat log backend | `docker compose logs -f backend` |
| Berhenti (data tetap) | `docker compose down` |
| Berhenti dan **hapus database** | `docker compose down -v` |

Tanpa `--build`, container memakai image lama, sehingga perubahan kode tidak terlihat.

## Masalah umum

**`failed to connect to the docker API ... dockerDesktopLinuxEngine`**
Docker Desktop belum berjalan. Buka Docker Desktop, tunggu sampai *Engine running*, ulangi.

**Postgres langsung berhenti, muncul warning `The "POSTGRES_USER" variable is not set`**
File `.env` belum dibuat. Ikuti langkah `copy .env.example .env` di atas.

**Login gagal atau backend tidak bisa terhubung ke database setelah mengubah `.env`**
Postgres hanya membaca `POSTGRES_PASSWORD` saat database pertama kali dibuat, dan admin hanya
di-seed bila belum ada. Mengubah `POSTGRES_PASSWORD`, `SEED_ADMIN_EMAIL`, atau `SEED_ADMIN_PASSWORD`
setelah run pertama tidak berpengaruh. Reset dengan `docker compose down -v` lalu
`docker compose up -d`. Perintah ini **menghapus seluruh data database**.

**Port 8080 sudah dipakai aplikasi lain**
Ubah `HTTP_PORT` di `.env` (misalnya `8081`), lalu `docker compose up -d`.

## Autentikasi

| Endpoint | Fungsi |
|---|---|
| `POST /api/auth/login` | Verifikasi email + kata sandi (bcrypt), set cookie `access_token` (JWT, httpOnly, SameSite=Lax) |
| `POST /api/auth/logout` | Menghapus cookie |
| `GET /api/auth/me` | Data pengguna + peran; memperpanjang sesi |

- Sesi berakhir setelah `ACCESS_TOKEN_MINUTES` (bawaan 30) tanpa request terautentikasi.
- Logout menghapus cookie di browser. Token yang sudah terlanjur disalin tetap valid sampai
  kedaluwarsa (maksimal `ACCESS_TOKEN_MINUTES`).
- Lima peran (Admin, Kaprodi, Dosen, Staf Administrasi, Mahasiswa) disimpan di tabel `roles`,
  bukan hard-coded. Hak akses per peran menunggu matriks RBAC (SCRUM-25).
- Belum ada: pembuatan pengguna lewat UI (manajemen pengguna), SSO kampus, pembatasan percobaan login.

## Test

Test backend dijalankan di dalam container dan memakai SQLite in-memory, jadi tidak menyentuh
database Postgres:

```powershell
docker compose up -d --build
docker compose exec backend pytest -q -p no:cacheprovider
```

Jalankan `--build` dulu bila test atau kode berubah, karena kode disalin ke image saat build.

## Struktur

```
backend/    FastAPI: app/{core,api,models,schemas}, alembic/, tests/
frontend/   Next.js (App Router, TypeScript, Tailwind)
nginx/      nginx.conf
docker-compose.yml, .env.example
```
