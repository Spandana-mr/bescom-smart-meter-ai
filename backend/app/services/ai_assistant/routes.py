import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .context_builder import build_dashboard_context
from .groq_client import GroqUnavailable, chat_completion
from .prompt_builder import build_messages
from .response_formatter import fallback_answer, sanitize_text


LOGGER = logging.getLogger("bescom.ai_assistant")
router = APIRouter(tags=["AI Analyst Assistant"])


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=2, max_length=2000)
    context: dict[str, Any] | None = None


class AssistantChatResponse(BaseModel):
    answer: str
    sources: list[str]
    warnings: list[str]
    model: str | None = None
    cached: bool = False


@router.post("/api/v1/assistant/chat", response_model=AssistantChatResponse)
@router.post("/api/assistant/chat", response_model=AssistantChatResponse)
async def assistant_chat(payload: AssistantChatRequest) -> AssistantChatResponse:
    context = build_dashboard_context(payload.context)
    messages = build_messages(payload.message, context)
    warnings = ["AI-generated operational insight. Requires analyst verification."]
    sources = ["dashboard_kpis", "forecast_summary", "zone_risks", "priority_alerts"]
    if context.get("selectedAlert"):
        sources.append("selected_alert")
    if context.get("selectedMeter"):
        sources.append("selected_meter_summary")

    LOGGER.info(
        "assistant_chat requested at %s message=%s context_keys=%s",
        datetime.now(timezone.utc).isoformat(),
        sanitize_text(payload.message[:180]),
        sorted(context.keys()),
    )
    try:
        completion = await chat_completion(messages)
        answer = sanitize_text(completion["answer"])
        if "Requires analyst verification" not in answer:
            answer = f"{answer}\n\nAI-generated operational insight. Requires analyst verification."
        LOGGER.info("assistant_chat completed model=%s cached=%s", completion.get("model"), completion.get("cached"))
        return AssistantChatResponse(
            answer=answer,
            sources=sources,
            warnings=warnings,
            model=completion.get("model"),
            cached=bool(completion.get("cached")),
        )
    except GroqUnavailable as exc:
        LOGGER.warning("assistant_chat using local fallback: %s", exc)
        return AssistantChatResponse(
            answer=sanitize_text(fallback_answer(payload.message, context)),
            sources=sources,
            warnings=[*warnings, f"Groq unavailable; returned local fallback summary. Backend detail: {sanitize_text(str(exc))}"],
            model="local-fallback",
        )
