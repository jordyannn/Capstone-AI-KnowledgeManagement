# Konteks build = root repo, karena worker memakai kode backend/app (model, config, ETL, indexer)
# ditambah dependensi ML yang tidak ada di image backend.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/models TOKENIZERS_PARALLELISM=false
WORKDIR /srv

COPY backend/requirements.txt backend-requirements.txt
COPY worker/requirements.txt worker-requirements.txt
# Index CPU PyTorch: wheel torch bawaan PyPI di Linux menarik paket CUDA berukuran beberapa GB.
RUN pip install --no-cache-dir -r backend-requirements.txt -r worker-requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY backend/app ./app
RUN useradd --system --no-create-home app && mkdir /models && chown app /models
USER app

CMD ["python", "-m", "app.ingest.worker"]
