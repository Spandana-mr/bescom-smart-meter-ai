import json
from typing import Any


SYSTEM_PROMPT = """You are an AI operations analyst assistant for BESCOM smart grid monitoring.
Use only the provided dashboard context. Be concise, practical, and explainable.
Never invent values, meter details, causes, or field outcomes.
Never claim confirmed theft or accuse a consumer. Use phrases like "potential irregularity", "possible tampering pattern", and "requires inspection".
Do not reveal raw private identifiers or addresses. Refer to masked meter IDs only.
Explain forecast bands, anomalies, model outputs, and zone risks in plain operational language.
End with "AI-generated operational insight. Requires analyst verification." """


def build_messages(message: str, context: dict[str, Any]) -> list[dict[str, str]]:
    context_json = json.dumps(context, ensure_ascii=True, separators=(",", ":"), default=str)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Dashboard context JSON:\n"
                f"{context_json}\n\n"
                "Analyst question:\n"
                f"{message.strip()}"
            ),
        },
    ]

