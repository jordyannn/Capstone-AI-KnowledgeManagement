# AI Knowledge Management System

Capstone Kelompok 31, Prodi S1 Sistem Informasi, Telkom University Jakarta.

Status saat ini:
- login/logout (**SCRUM-28**) dan login SSO Microsoft (**SCRUM-73**);
- pipeline data: ETL korpus ke Postgres (**SCRUM-36**) serta chunking, embedding, dan indexing ke
  ChromaDB (**SCRUM-38**);
- chat asisten berbasis RAG dengan sitasi dokumen + halaman, jawaban streaming, eskalasi bila
  dokumen tidak memuat jawaban, dan riwayat percakapan per mahasiswa.

Belum ada: livechat/tiket, unggah dokumen lewat UI, halaman admin, PII masking, log audit.

## Arsitektur (yang sudah ada)

```
Browser -> Nginx (:HTTP_PORT)
             |-- /      -> Frontend (Next.js)
             '-- /api/  -> Backend (FastAPI) -> PostgreSQL (pengguna, dokumen, riwayat chat)
                              |-- /search --> RAG service (embedding e5 + BM25) -> ChromaDB
                              '-- /api/chat -> Ollama di host (qwen2.5:7b, GPU)

Ingest Worker --baca dokumen "pending"--> PostgreSQL
              --tulis vektor------------> ChromaDB
```

## Prasyarat

- **Git**
- **Docker Desktop**, dan harus dalam keadaan **berjalan** (ikon paus di system tray,
  status *Engine running*) sebelum menjalankan perintah `docker compose` apa pun.
- **Ollama** di komputer host (bukan di container), dengan model `qwen2.5:7b`. Lihat bagian
  [Ollama (model bahasa)](#ollama-model-bahasa).

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

## Setup untuk anggota tim (laptop sendiri)

Langkah lengkap supaya anggota tim bisa menjalankan aplikasi di laptopnya sendiri, termasuk login
SSO dengan akun Telkom University. Aplikasi, database, dan dokumen berjalan di laptop masing-masing,
jadi akun, riwayat chat, dan tiket **tidak tersambung** dengan laptop anggota lain.

**Minta dulu ke pemegang repo (lewat chat pribadi, jangan di grup besar atau GitHub):**
- `SSO_CLIENT_ID` dan `SSO_CLIENT_SECRET`
- folder `data/` (±21 MB: `data/seed/corpus_clean.jsonl` + PDF di `data/dokumen/`). Folder ini tidak di-commit.

**1. Install:** Git, Docker Desktop (jalankan sampai *Engine running*), dan Ollama.

**2. Siapkan model bahasa** (sekali, ±4,7 GB). Lalu atur setelan GPU dan restart Ollama
(tray → Quit, buka lagi). Penjelasannya ada di bagian [Ollama](#ollama-model-bahasa).

```powershell
ollama pull qwen2.5:7b
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

Tanpa GPU NVIDIA ≥ 6 GB, jawaban bisa lebih dari 1 menit. Alternatif yang lebih ringan:
`ollama pull qwen2.5:3b`, lalu tambahkan `OLLAMA_MODEL=qwen2.5:3b` di `.env`. Model ini ±2x lebih
cepat, tetapi lebih sering salah menolak pertanyaan.

**3. Clone dan isi `.env`:**

```powershell
git clone https://github.com/jordyannn/Capstone-AI-KnowledgeManagement.git
cd Capstone-AI-KnowledgeManagement
copy .env.example .env
```

Di `.env`: isi `POSTGRES_PASSWORD`, `SECRET_KEY`, `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` (bebas,
milik sendiri), lalu aktifkan SSO:

```
SSO_ENABLED=true
SSO_CLIENT_ID=<dari pemegang repo>
SSO_CLIENT_SECRET=<dari pemegang repo>
```

Biarkan `HTTP_PORT=8080` dan `SSO_REDIRECT_URI` seperti bawaan. Redirect URI yang terdaftar di Azure
adalah `http://localhost:8080/api/auth/sso/callback`, jadi port lain membuat SSO gagal.

**4. Salin folder `data/`** ke root repo, sehingga ada `data/seed/corpus_clean.jsonl` dan `data/dokumen/*.pdf`.

**5. Jalankan dan isi basis pengetahuan:**

```powershell
docker compose up -d --build
docker compose exec backend python -m app.etl.load_corpus /data/seed/corpus_clean.jsonl
docker compose exec worker python -m app.etl.load_pdfs /data/dokumen
docker compose logs -f worker      # tunggu sampai semua dokumen ter-index, lalu Ctrl+C
```

Indexing pertama mengunduh model embedding dan butuh beberapa menit. Cek progres:
`docker compose exec postgres psql -U kms -d kms -c "select status, count(*) from documents group by status;"`.
Selesai bila semua `indexed`.

**6. Buka `http://localhost:8080`** (bukan `127.0.0.1`), lalu klik **"Masuk dengan akun Telkom
University"**. Akun `@student.telkomuniversity.ac.id` otomatis dibuat sebagai Mahasiswa. Untuk
membuka halaman admin (Antrean Bantuan), login dengan `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD`.

**Kalau ada masalah:**
- Tombol SSO tidak muncul: `SSO_ENABLED` belum `true`, atau backend belum dibuat ulang (`docker compose up -d`).
- Backend tidak mau start setelah SSO diaktifkan: client ID/secret kosong (`docker compose logs backend`).
- Chat selalu menjawab "dokumen tidak memuat jawaban": langkah 5 belum selesai, atau Ollama belum jalan.
- Secret SSO bocor: pemegang repo membuat secret baru di Azure (Certificates & secrets), menghapus
  yang lama, dan membagikan yang baru.

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

## Ollama (model bahasa)

Chat memakai Ollama yang berjalan langsung di Windows agar bisa memakai GPU. Container backend
menghubunginya lewat `http://host.docker.internal:11434`.

```powershell
ollama pull qwen2.5:7b
```

**Setelan wajib** (sekali per komputer). Tanpa ini, di GPU 6 GB model tidak muat dan jawaban jauh
lebih lambat. Hasil pengukuran: median 20 detik -> 12,5 detik.

```powershell
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

Setelah itu tutup Ollama lewat ikon tray -> **Quit**, lalu buka lagi agar setelan terbaca. Untuk
membatalkan: `setx OLLAMA_FLASH_ATTENTION 0` dan `setx OLLAMA_KV_CACHE_TYPE f16`, lalu restart Ollama.

Setelan aplikasi terkait (`docker-compose.yml` / `.env`):

| Variabel | Default | Keterangan |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:7b` | `qwen2.5:3b` 2x lebih cepat tetapi lebih sering salah menolak pertanyaan |
| `CHAT_TOP_K` | `4` | Jumlah potongan dokumen yang dikirim ke model. Lebih sedikit = lebih cepat |

Backend memuat model ke GPU saat start dan menahannya 30 menit setelah dipakai terakhir. Untuk
melepas VRAM (misalnya mau main game): `ollama stop qwen2.5:7b`.

**Kebutuhan VRAM:** qwen2.5:7b (Q4_K_M) butuh +-5,2 GB. Di GTX 1660 6 GB hanya 25 dari 29 layer yang
masuk GPU karena Windows ikut memakai VRAM, sehingga waktu respons 7-22 detik. Untuk target <= 5 detik
dibutuhkan GPU >= 8 GB. Saat demo, tutup aplikasi yang memakai GPU (browser dengan hardware
acceleration, game, overlay).

## Evaluasi chat

Set uji 34 pertanyaan ada di `backend/eval/eval_set.jsonl`. Hasil tiap run disimpan di
`backend/eval/results/`.

```powershell
docker compose cp backend/eval/. backend:/tmp/eval/
docker compose exec -e EVAL_EMAIL=<email akun uji> -e EVAL_PASSWORD=<sandi> backend python /tmp/eval/run_eval.py --label nama-run
docker compose cp backend:/tmp/eval-results/. backend/eval/results/
```

`--no-chat` hanya mengukur retrieval (cepat, tanpa LLM). `stream_latency.py` mengukur waktu sampai
kata pertama tampil. Gunakan pertanyaan baru untuk mengukur waktu: pertanyaan yang sama dengan run
sebelumnya terkena cache Ollama sehingga angkanya terlalu bagus.

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
| `GET /api/auth/sso/status` | `{"enabled": true/false}`; dipakai halaman login untuk menampilkan tombol SSO |
| `GET /api/auth/sso/login` | Memulai login SSO Microsoft (redirect ke Microsoft). 404 bila SSO mati |
| `GET /api/auth/sso/callback` | Tujuan redirect dari Microsoft; memasang cookie sesi yang sama. 404 bila SSO mati |

- Sesi berakhir setelah `ACCESS_TOKEN_MINUTES` (bawaan 30) tanpa request terautentikasi.
- Logout menghapus cookie di browser. Token yang sudah terlanjur disalin tetap valid sampai
  kedaluwarsa (maksimal `ACCESS_TOKEN_MINUTES`).
- Lima peran (Admin, Kaprodi, Dosen, Staf Administrasi, Mahasiswa) disimpan di tabel `roles`,
  bukan hard-coded. Hak akses per peran menunggu matriks RBAC (SCRUM-25).
- Belum ada: pembuatan pengguna lewat UI (manajemen pengguna), pembatasan percobaan login.

## Login SSO Microsoft

Tombol **"Masuk dengan akun Telkom University"** memakai Microsoft Entra ID (OpenID Connect,
authorization code + PKCE). Login email + kata sandi tetap ada. SSO **mati bawaannya**.

### Mengaktifkan

1. Di Azure Portal, buka App registration aplikasi ini (`KMS SI Jakarta (dev)`). Salin
   **Application (client) ID** dari halaman Overview.
2. Buat client secret: **Certificates & secrets → New client secret**. Salin kolom **Value**
   (bukan *Secret ID*). Nilainya hanya tampil sekali, dan secret punya masa berlaku: catat
   tanggal kedaluwarsanya.
3. Isi `.env` (file ini di-gitignore; **jangan pernah** menaruh secret di kode, README, atau commit):
   ```
   SSO_ENABLED=true
   SSO_CLIENT_ID=<Application (client) ID>
   SSO_CLIENT_SECRET=<Value dari langkah 2>
   ```
4. Terapkan: `docker compose up -d` (backend dibuat ulang karena env berubah).
5. Buka **`http://localhost:8080/login`**, bukan `127.0.0.1`. Redirect URI di Azure dan cookie sesi
   terikat ke `localhost`. Redirect URI yang terdaftar harus persis
   `http://localhost:8080/api/auth/sso/callback`; bila `HTTP_PORT` diubah, ubah juga `SSO_REDIRECT_URI`
   dan daftarkan URI barunya di Azure.

Bila `SSO_ENABLED=true` tetapi client ID atau secret kosong, backend **sengaja menolak start** dengan
pesan jelas (cek `docker compose logs backend`).

### Aturan akun

- Hanya akun dari tenant Entra ID Tel-U (`SSO_TENANT_ID`) dengan domain di `SSO_ALLOWED_DOMAINS`
  yang diterima. Domain dicocokkan persis, bukan sebagai akhiran.
- Email **`@student.telkomuniversity.ac.id`** yang belum terdaftar otomatis dibuat sebagai **Mahasiswa**.
  Itu mencakup mahasiswa Tel-U mana pun, bukan hanya SI Jakarta; saat ini Mahasiswa hanya melihat
  dokumen publik.
- Email lain di domain yang diizinkan (Dosen, Staf, Kaprodi) **tidak dibuat otomatis**. Akunnya harus
  dibuat admin lebih dulu (manajemen pengguna: SCRUM-30, belum ada). Hasilnya
  "Akun belum terdaftar, hubungi admin prodi".
- Akun yang sudah ada dengan email yang sama **ditautkan** pada login SSO pertama dan mempertahankan
  perannya. Tautan ini mengandalkan klaim email dari Microsoft, yang bisa berubah; risikonya rendah
  karena tenant dikelola IT Tel-U dan dibatasi domain, dan akun yang sudah tertaut ke identitas lain
  tidak bisa diambil alih. Identitas selanjutnya dikenali lewat `oid`, bukan email.
- Akun SSO tidak punya kata sandi dan **tidak bisa** login lewat form email + sandi.
- Logout hanya mengakhiri sesi aplikasi, bukan sesi Microsoft di browser. Karena itu login selalu
  meminta pengguna memilih akun.

### Mematikan

`SSO_ENABLED=false` di `.env`, lalu `docker compose up -d`. Tombol hilang dan endpoint SSO menjawab 404.
Pengguna SSO yang sudah ada tetap tersimpan, tetapi tidak bisa masuk sampai SSO diaktifkan lagi
(mereka tidak punya kata sandi).

### Deploy ke server

Microsoft hanya mengizinkan redirect URI `http://` untuk `localhost`. Untuk server dibutuhkan HTTPS dan
domain, `COOKIE_SECURE=true`, `SSO_REDIRECT_URI` yang sesuai, dan URI itu didaftarkan di Azure.

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
