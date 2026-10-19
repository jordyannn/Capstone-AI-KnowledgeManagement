# AI Knowledge Management System

Capstone Kelompok 31, Prodi S1 Sistem Informasi, Telkom University Jakarta.

Status saat ini: login/logout (**SCRUM-28**) dan pipeline data pertama: ETL korpus ke Postgres
(**SCRUM-36**) serta chunking, embedding, dan indexing ke ChromaDB (**SCRUM-38**).
Belum ada: chat/RAG, unggah dokumen, Ollama.

## Arsitektur (yang sudah ada)

```
Browser -> Nginx (:HTTP_PORT)
             |-- /      -> Frontend (Next.js)
             '-- /api/  -> Backend (FastAPI) -> PostgreSQL

Ingest Worker --baca dokumen "pending"--> PostgreSQL
              --tulis vektor------------> ChromaDB
```

## Prasyarat

- **Git**
- **Docker Desktop**, dan harus dalam keadaan **berjalan** (ikon paus di system tray,
  status *Engine running*) sebelum menjalankan perintah `docker compose` apa pun.

Python dan Node.js di komputer **tidak diperlukan** untuk menjalankan aplikasi maupun test.

Ruang disk: image worker (PyTorch CPU + sentence-transformers) berukuran beberapa GB, dan model
embedding (~470 MB) diunduh sekali saat dokumen pertama diproses. Build pertama jadi lebih lama.

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

**Worker tidak memproses apa pun / dokumen tetap `pending`**
Lihat `docker compose logs worker`. Penyebab umum: model embedding belum selesai diunduh (tunggu),
tidak ada koneksi internet saat unduhan pertama, atau ChromaDB belum sehat (`docker compose ps`).
Selama masalahnya di infrastruktur, dokumen sengaja dibiarkan `pending`, bukan `failed`.

**Port 8080 sudah dipakai aplikasi lain**
Ubah `HTTP_PORT` di `.env` (misalnya `8081`), lalu `docker compose up -d`.

## Pipeline data

```
corpus_clean.jsonl --ETL--> documents + document_pages (status: pending)
                                   |  worker mengambil "pending"
                                   v
                     chunking -> embedding -> ChromaDB (collection kms_chunks) + tabel chunks
                                   |
                                   v  status: indexed (atau failed + error_message)
```

**1. Siapkan korpus.** Salin `corpus_clean.jsonl` (dari vault tim) ke `data/seed/corpus_clean.jsonl`.
Folder `data/` sengaja tidak di-commit.

**2. Muat ke Postgres (ETL).** Aman dijalankan berulang: dokumen dengan `content_hash` yang sama dilewati.

```powershell
docker compose exec backend python -m app.etl.load_corpus /data/seed/corpus_clean.jsonl
```

Hasilnya laporan: dibaca, baru, dilewati (duplikat), dan baris gagal validasi beserta alasannya.

**3. Biarkan worker meng-index.** Worker berjalan otomatis dan memproses dokumen `pending`.
Pertama kali, ia mengunduh model embedding (beberapa menit). Pantau:

```powershell
docker compose logs -f worker
docker compose exec postgres psql -U kms -d kms -c "select status, count(*) from documents group by status;"
```

**4. Coba pencarian** (belum ada endpoint publik, hanya CLI di container worker):

```powershell
docker compose exec worker python -m app.retrieval.search_cli "bagaimana alur penundaan pembayaran BPP?" --k 5
docker compose exec worker python -m app.retrieval.search_cli "..." --role mahasiswa
```

Tanpa `--role`, hanya dokumen `publik` yang dicari. `GET /api/health` kini juga mengecek ChromaDB.

**Index ulang.** Dokumen yang gagal tidak diulang otomatis. Kembalikan ke `pending` dengan:

```powershell
docker compose exec backend python -m app.ingest.requeue --failed   # hanya yang gagal
docker compose exec backend python -m app.ingest.requeue --all      # semua (wajib bila EMBEDDING_MODEL diganti)
```

Catatan desain:
- Akses dokumen disimpan di `documents.allowed_roles` (kode peran atau `publik`). Semua data seed
  `publik` karena matriks RBAC (SCRUM-25) belum final. Filter akses dipakai ulang oleh SCRUM-44 lewat
  `app/retrieval/access.py`.
- ChromaDB tidak menerima list di metadata, jadi tiap peran disimpan sebagai flag (`role_publik`,
  `role_dosen`, ...) dan difilter langsung di ChromaDB.
- Vektor dihitung dari `"{judul}. {isi chunk}"`, bukan isi chunk saja (`embedding_text` di
  `app/ingest/indexer.py`), supaya chunk yang tidak menyebut topik halamannya tetap ketemu. Teks yang
  disimpan (Postgres dan ChromaDB) tetap isi aslinya. Mengubah fungsi itu juga berarti index ulang.
- Mengganti `EMBEDDING_MODEL` mengubah ruang vektor: semua dokumen harus di-index ulang.

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
backend/    FastAPI: app/{core,api,models,schemas,etl,ingest,retrieval}, alembic/, tests/
worker/     Dockerfile + dependensi ML untuk ingest worker (kodenya di backend/app/ingest)
frontend/   Next.js (App Router, TypeScript, Tailwind)
nginx/      nginx.conf
data/       korpus seed (tidak di-commit)
docker-compose.yml, .env.example
```
