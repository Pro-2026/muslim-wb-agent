import logging
from datetime import date, datetime, timedelta, timezone

import google.generativeai as genai
from sqlalchemy import func, select

from src.config import settings
from src.database import AsyncSessionLocal
from src.models import Campaign, Client, Keyword, KeywordMetric

logger = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

REPORT_PROMPT = """Ты — аналитик по рекламе на Wildberries. Вот данные за вчера (JSON).

Сделай краткий отчёт для Telegram (до 1200 символов):
1. Общая оценка дня (1-2 предложения)
2. Что работает хорошо
3. Слабые места и конкретные рекомендации
4. На что обратить внимание сегодня

Стиль — деловой, без воды, для эксперта. Используй цифры.

Данные:
{data}"""


async def collect_yesterday_stats() -> dict:
    """Агрегирует метрики за вчера по всем клиентам."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                func.sum(KeywordMetric.views).label("total_views"),
                func.sum(KeywordMetric.clicks).label("total_clicks"),
                func.sum(KeywordMetric.orders).label("total_orders"),
                func.sum(KeywordMetric.spend).label("total_spend"),
            ).where(func.date(KeywordMetric.date) == yesterday)
        )
        totals = result.one()

        # Топ-5 по заказам
        top5_result = await session.execute(
            select(Keyword.phrase, KeywordMetric.orders, KeywordMetric.spend, KeywordMetric.ctr)
            .join(Keyword, Keyword.id == KeywordMetric.keyword_id)
            .where(func.date(KeywordMetric.date) == yesterday)
            .order_by(KeywordMetric.orders.desc())
            .limit(5)
        )
        top5 = [
            {"phrase": r.phrase, "orders": r.orders, "spend": round(r.spend, 0), "ctr": round(r.ctr, 4)}
            for r in top5_result.all()
        ]

        # Худшие 5 (высокий расход, 0 заказов)
        worst5_result = await session.execute(
            select(Keyword.phrase, KeywordMetric.orders, KeywordMetric.spend, KeywordMetric.clicks)
            .join(Keyword, Keyword.id == KeywordMetric.keyword_id)
            .where(func.date(KeywordMetric.date) == yesterday, KeywordMetric.orders == 0, KeywordMetric.spend > 0)
            .order_by(KeywordMetric.spend.desc())
            .limit(5)
        )
        worst5 = [
            {"phrase": r.phrase, "spend": round(r.spend, 0), "clicks": r.clicks}
            for r in worst5_result.all()
        ]

    spend = float(totals.total_spend or 0)
    orders = int(totals.total_orders or 0)
    clicks = int(totals.total_clicks or 0)
    views = int(totals.total_views or 0)

    return {
        "date": yesterday.isoformat(),
        "total_views": views,
        "total_clicks": clicks,
        "total_orders": orders,
        "total_spend_rub": round(spend, 0),
        "drr_pct": round(spend / (orders * 1000) * 100, 1) if orders else None,
        "ctr_pct": round(clicks / views * 100, 2) if views else 0,
        "avg_cpo_rub": round(spend / orders, 0) if orders else None,
        "top5_keywords": top5,
        "worst5_keywords_no_orders": worst5,
    }


async def generate_daily_report() -> str:
    """Собирает данные и генерирует отчёт через Gemini."""
    stats = await collect_yesterday_stats()

    if stats["total_views"] == 0:
        return (
            f"Отчёт за {stats['date']}\n\n"
            "Данных за вчера нет — синхронизация с WB ещё не выполнялась "
            "или кампании не активны."
        )

    import json
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = REPORT_PROMPT.format(data=json.dumps(stats, ensure_ascii=False, indent=2))

    try:
        response = model.generate_content(prompt)
        report_text = response.text.strip()
    except Exception as e:
        logger.error("Gemini report generation failed: %s", e)
        # Fallback — простой отчёт без LLM
        report_text = (
            f"Показы: {stats['total_views']:,}\n"
            f"Клики: {stats['total_clicks']:,} (CTR {stats['ctr_pct']}%)\n"
            f"Заказы: {stats['total_orders']}\n"
            f"Расход: {stats['total_spend_rub']:,} р\n"
            f"CPO: {stats['avg_cpo_rub']} р\n"
            f"ДРР: {stats['drr_pct']}%"
        )

    return f"Отчёт за {stats['date']}\n\n{report_text}"
