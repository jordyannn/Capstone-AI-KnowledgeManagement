"""Lapisan model bahasa: lokal (Ollama) atau komersial (Groq, Gemini, Mistral, Cloudflare).

Keempat penyedia komersial dipanggil lewat endpoint bergaya OpenAI (`/chat/completions`), jadi cukup
satu klien. Ollama tetap memakai API-nya sendiri (`/api/chat`) karena butuh `keep_alive` dan `num_ctx`.

Aturan pemilihan (mengikuti proyek KP, "LLM Switching"):
1. Model lokal selalu tersedia dan menjadi bawaan.
2. Model komersial hanya tersedia bila COMMERCIAL_LLM_ENABLED=true dan API key-nya terisi.
3. Pertanyaan yang memuat data pribadi (terdeteksi PII masking) atau kata sensitif (SENSITIVE_KEYWORDS)
   SELALU dijawab model lokal, apa pun pilihan pengguna. Lapisan ini hanya bisa memindahkan ke lokal,
   tidak pernah sebaliknya.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings

LOCAL = "lokal"


@dataclass(frozen=True)
class Provider:
    code: str
    label: str
    model: str
    url: str = ""
    api_key: str = ""


class LLMError(Exception):
    """reason: ringkas untuk ditampilkan ke pengguna, mis. "batas kuota"."""

    def __init__(self, message: str, reason: str = "galat") -> None:
        super().__init__(message)
        self.reason = reason


def _error(exc: Exception) -> LLMError:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        reason = "batas kuota" if code == 429 else "server penyedia sedang sibuk" if code == 503 else "kunci API ditolak" if code in (401, 403) else f"HTTP {code}"
        return LLMError(f"HTTP {code}", reason)
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("timeout", "waktu habis")
    return LLMError(type(exc).__name__)


def local() -> "Provider":
    return Provider(LOCAL, "Lokal", get_settings().ollama_model)


def _commercial(s: Settings) -> list[Provider]:
    out = []
    if s.groq_api_key:
        out.append(Provider("groq", "Groq", s.groq_model, "https://api.groq.com/openai/v1/chat/completions", s.groq_api_key))
    if s.gemini_api_key:
        out.append(Provider("gemini", "Gemini", s.gemini_model,
                            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", s.gemini_api_key))
    if s.mistral_api_key:
        out.append(Provider("mistral", "Mistral", s.mistral_model, "https://api.mistral.ai/v1/chat/completions", s.mistral_api_key))
    if s.cloudflare_api_token and s.cloudflare_account_id:
        out.append(Provider("cloudflare", "Cloudflare", s.cloudflare_model,
                            f"https://api.cloudflare.com/client/v4/accounts/{s.cloudflare_account_id}/ai/v1/chat/completions",
                            s.cloudflare_api_token))
    return out


def available() -> list[Provider]:
    s = get_settings()
    return [local()] + (_commercial(s) if s.commercial_llm_enabled else [])


def is_sensitive(question: str, masked: list[str]) -> bool:
    low = question.lower()
    return bool(masked) or any(k in low for k in get_settings().sensitive_keyword_list)


def choose(requested: str | None, question: str, masked: list[str]) -> tuple[Provider, str | None]:
    """Kembalikan (penyedia yang dipakai, alasan bila berbeda dari yang diminta)."""
    providers = {p.code: p for p in available()}
    local = providers[LOCAL]
    if not requested or requested == LOCAL:
        return local, None
    if requested not in providers:
        return local, "model yang dipilih tidak tersedia"
    if is_sensitive(question, masked):
        return local, "pertanyaan memuat data pribadi/sensitif, dijawab model lokal"
    return providers[requested], None


def label(p: Provider) -> str:
    return f"{p.label} ({p.model})"


# ---------- pemanggilan ----------


def _ollama_payload(messages: list[dict], stream: bool) -> dict:
    s = get_settings()
    return {
        "model": s.ollama_model,
        "messages": messages,
        "stream": stream,
        "keep_alive": s.ollama_keep_alive,
        "options": {"num_ctx": s.ollama_num_ctx, "temperature": 0.2},
    }


def _openai_payload(p: Provider, messages: list[dict], stream: bool) -> dict:
    body = {"model": p.model, "messages": messages, "stream": stream, "temperature": 0.2,
            "max_tokens": get_settings().commercial_max_tokens}
    if "gpt-oss" in p.model:
        # Model "reasoning": penalaran dipendekkan supaya token tidak habis sebelum jawaban ditulis
        # (diuji 26 Nov di Groq: 141 → 72 token, isi jawaban sama).
        body["reasoning_effort"] = "low"
    return body


def generate(p: Provider, messages: list[dict]) -> str:
    s = get_settings()
    try:
        if p.code == LOCAL:
            r = httpx.post(f"{s.ollama_url}/api/chat", json=_ollama_payload(messages, False), timeout=s.ollama_timeout_seconds)
            r.raise_for_status()
            return r.json()["message"]["content"]
        r = httpx.post(p.url, json=_openai_payload(p, messages, False), timeout=s.commercial_timeout_seconds,
                       headers={"Authorization": f"Bearer {p.api_key}"})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise _error(exc) from exc


def stream(p: Provider, messages: list[dict]) -> Iterator[str]:
    """Menghasilkan potongan teks jawaban. Melempar LLMError bila penyedia gagal."""
    s = get_settings()
    try:
        if p.code == LOCAL:
            with httpx.stream("POST", f"{s.ollama_url}/api/chat", json=_ollama_payload(messages, True),
                              timeout=s.ollama_timeout_seconds) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    part = json.loads(line)
                    piece = part.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if part.get("done"):
                        break
            return
        with httpx.stream("POST", p.url, json=_openai_payload(p, messages, True), timeout=s.commercial_timeout_seconds,
                          headers={"Authorization": f"Bearer {p.api_key}"}) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                choices = json.loads(data).get("choices") or [{}]
                piece = (choices[0].get("delta") or {}).get("content") or ""
                if piece:
                    yield piece
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise _error(exc) from exc
