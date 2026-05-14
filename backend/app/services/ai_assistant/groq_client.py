import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from time import monotonic
from typing import Any


LOGGER = logging.getLogger("bescom.ai_assistant")
MODEL_FALLBACKS = (
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 180
_ENV_LOADED = False


class GroqUnavailable(RuntimeError):
    pass


class GroqAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _cache_key(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_local_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).resolve().parents[4] / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def chat_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    _load_local_env()
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not api_key:
        raise GroqUnavailable("GROQ_API_KEY is not set")

    key = _cache_key(messages)
    cached = _CACHE.get(key)
    if cached and monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}

    last_error = "Groq request failed"
    for model in MODEL_FALLBACKS:
        for attempt in range(2):
            try:
                completion = await asyncio.to_thread(_sdk_completion, api_key, model, messages)
                answer = completion.choices[0].message.content.strip()
                result = {
                    "answer": answer,
                    "model": model,
                    "cached": False,
                    "usage": completion.usage.model_dump() if completion.usage else {},
                }
                _CACHE[key] = (monotonic(), result)
                return result
            except (GroqAPIError, TimeoutError, ValueError) as exc:
                status = getattr(exc, "status", None)
                last_error = f"{model}: {exc}"
                LOGGER.warning("Groq attempt failed: %s", last_error)
                if status and status not in {408, 429, 500, 502, 503, 504}:
                    break
                await asyncio.sleep(0.35 * (attempt + 1))
    raise GroqUnavailable(last_error)


def _sdk_completion(api_key: str, model: str, messages: list[dict[str, str]]):
    try:
        from groq import APIConnectionError, APIStatusError, Groq
    except ImportError as exc:
        raise GroqUnavailable("Groq Python SDK is not installed. Rebuild the backend container.") from exc

    try:
        client = Groq(api_key=api_key, timeout=18.0, max_retries=0)
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.25,
            max_tokens=700,
        )
    except APIStatusError as exc:
        detail = str(getattr(exc, "response", ""))[:700]
        raise GroqAPIError(f"HTTP {exc.status_code}: {detail or exc}", status=exc.status_code) from exc
    except APIConnectionError as exc:
        raise GroqAPIError(f"connection error: {exc}") from exc
