FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --no-create-home app && chmod +x entrypoint.sh
USER app

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
