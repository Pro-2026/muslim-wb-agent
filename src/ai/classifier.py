import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import google.generativeai as genai
from pydantic import BaseModel, Field

from src.config import settings

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

CLASSIFY_TOOL = {
    "function_declarations": [
        {
            "name": "classify_keyword",
            "description": "Классифицировать поисковый кластер по релевантности товару",
            "parameters": {
                "type": "object",
                "properties": {
                    "phrase": {"type": "string", "description": "Поисковая фраза"},
                    "decision": {
                        "type": "string",
                        "enum": ["relevant", "irrelevant", "borderline"],
                        "description": "relevant=релевантен, irrelevant=нерелевантен, borderline=спорно",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Уверенность от 0.0 до 1.0",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Краткая причина решения (1-2 предложения)",
                    },
                },
                "required": ["phrase", "decision", "confidence", "reason"],
            },
        }
    ]
}

SYSTEM_PROMPT = """Ты — эксперт по рекламе на Wildberries. Твоя задача — классифицировать поисковые кластеры:
показывает ли данный запрос намерение купить именно этот товар или нет.

Решения:
- relevant: запрос явно относится к товару, покупатель ищет именно это
- irrelevant: запрос про другой товар, другую категорию, или явно нецелевой
- borderline: запрос может относиться к товару, но есть сомнения

Для каждого кластера вызови функцию classify_keyword."""


class Decision(str, Enum):
    relevant = "relevant"
    irrelevant = "irrelevant"
    borderline = "borderline"


class KeywordClassification(BaseModel):
    phrase: str
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


async def classify_keywords(
    keywords: list[str], product_context: str
) -> list[KeywordClassification]:
    """Классифицирует список кластеров через Gemini. Возвращает результат для каждого."""
    if not keywords:
        return []

    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        tools=CLASSIFY_TOOL,  # type: ignore[arg-type]
    )

    kw_list = "\n".join(f"- {kw}" for kw in keywords)
    user_message = (
        f"Контекст товара:\n{product_context}\n\n"
        f"Поисковые кластеры для классификации:\n{kw_list}"
    )

    try:
        response = model.generate_content(
            [{"role": "user", "parts": [SYSTEM_PROMPT + "\n\n" + user_message]}],
            tool_config={"function_calling_config": {"mode": "ANY"}},
        )
    except Exception as e:
        logger.error("Gemini API error: %s", e)
        raise

    results: list[KeywordClassification] = []
    for part in response.candidates[0].content.parts:
        if part.function_call:
            fc = part.function_call
            args = dict(fc.args)
            try:
                results.append(
                    KeywordClassification(
                        phrase=args["phrase"],
                        decision=Decision(args["decision"]),
                        confidence=float(args["confidence"]),
                        reason=args["reason"],
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse classification result: %s — %s", args, e)

    phrase_set = {r.phrase for r in results}
    for kw in keywords:
        if kw not in phrase_set:
            results.append(
                KeywordClassification(
                    phrase=kw,
                    decision=Decision.borderline,
                    confidence=0.0,
                    reason="Не удалось классифицировать автоматически",
                )
            )

    return results


def load_product_context(product_id: str) -> str:
    """Читает контекст товара из docs/products/<product_id>.md."""
    path = Path("docs") / "products" / f"{product_id}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"Товар: {product_id}. Подробное описание не добавлено."
