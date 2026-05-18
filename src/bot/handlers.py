import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal
from src.models import (
    Campaign,
    Client,
    Decision,
    DecisionStatus,
    DecisionType,
    DecisionWho,
    Feedback,
    Keyword,
    KeywordMetric,
)

logger = logging.getLogger(__name__)
router = Router()

DECISION_TTL_HOURS = 24


def _admin_only(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.admin_user_id)


# ─── /start ──────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я WB AI-агент.\n\n"
        "/ping — связь\n"
        "/pull — синхронизация с WB\n"
        "/classify — классифицировать кластеры через AI\n"
        "/review — проверить предложения AI\n"
        "/apply — применить подтверждённые удаления\n"
        "/bids — рекомендации по ставкам\n"
        "/status — состояние сервиса\n"
        "/stop — аварийная остановка"
    )


# ─── /ping ────────────────────────────────────────────────────────────────────

@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    if not _admin_only(message):
        return
    await message.answer("pong")


# ─── /stop ────────────────────────────────────────────────────────────────────

@router.message(Command("stop"))
async def cmd_stop(message: Message) -> None:
    if not _admin_only(message):
        return
    from src.scheduler import scheduler
    if scheduler.running:
        scheduler.pause()
        await message.answer("Планировщик остановлен. Автоматических действий не будет.\n/start снова запустит.")
    else:
        scheduler.resume()
        await message.answer("Планировщик возобновлён.")


# ─── /status ──────────────────────────────────────────────────────────────────

@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _admin_only(message):
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()
    if clients:
        names = ", ".join(c.name for c in clients)
        await message.answer(f"Клиенты: {names}\nСервис работает.")
    else:
        await message.answer(
            "Клиенты не добавлены.\n\n"
            "Когда получишь WB-токен:\n"
            "<code>INSERT INTO clients (name, wb_token, telegram_chat_id) "
            "VALUES ('Имя', 'WB_TOKEN', CHAT_ID);</code>"
        )


# ─── /pull ────────────────────────────────────────────────────────────────────

@router.message(Command("pull"))
async def cmd_pull(message: Message) -> None:
    if not _admin_only(message):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()

    if not clients:
        await message.answer("Нет клиентов в базе. Добавь WB-токен.")
        return

    await message.answer("Синхронизирую данные из WB...")

    from src.wb.sync import sync_client

    total_c, total_k, errors = 0, 0, []
    for client in clients:
        try:
            async with AsyncSessionLocal() as session:
                c, k = await sync_client(session, client)
            total_c += c
            total_k += k
        except Exception as e:
            logger.exception("pull error client=%d", client.id)
            errors.append(str(e))

    if errors:
        await message.answer(f"Готово с ошибками:\nКампаний: {total_c}, кластеров: {total_k}\n{'; '.join(errors)}")
    else:
        await message.answer(f"Готово.\nКампаний: {total_c}\nКластеров: {total_k}")


# ─── /classify ────────────────────────────────────────────────────────────────

@router.message(Command("classify"))
async def cmd_classify(message: Message) -> None:
    if not _admin_only(message):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client).limit(1))
        client = result.scalar_one_or_none()
        if not client:
            await message.answer("Нет клиентов в базе.")
            return

        result = await session.execute(
            select(Campaign).where(Campaign.client_id == client.id).limit(1)
        )
        campaign = result.scalar_one_or_none()
        if not campaign:
            await message.answer("Нет кампаний. Сначала /pull.")
            return

        result = await session.execute(
            select(Keyword)
            .outerjoin(Decision, Decision.keyword_id == Keyword.id)
            .where(
                Keyword.campaign_id == campaign.id,
                Decision.id.is_(None),
            )
            .limit(50)
        )
        keywords = result.scalars().all()

    if not keywords:
        await message.answer("Нет новых кластеров для классификации.")
        return

    await message.answer(f"Классифицирую {len(keywords)} кластеров через AI...")

    from src.ai.classifier import classify_keywords, load_product_context

    product_context = load_product_context(str(campaign.wb_id))
    phrases = [kw.phrase for kw in keywords]

    try:
        results = await classify_keywords(phrases, product_context)
    except Exception as e:
        await message.answer(f"Ошибка Gemini API: {e}")
        return

    phrase_to_kw = {kw.phrase: kw for kw in keywords}
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DECISION_TTL_HOURS)

    counts = {"relevant": 0, "irrelevant": 0, "borderline": 0}
    async with AsyncSessionLocal() as session:
        for r in results:
            kw = phrase_to_kw.get(r.phrase)
            if not kw:
                continue
            counts[r.decision] = counts.get(r.decision, 0) + 1
            session.add(Decision(
                keyword_id=kw.id,
                decision=r.decision,
                confidence=r.confidence,
                reason=r.reason,
                who=DecisionWho.ai,
                status=DecisionStatus.pending,
                expires_at=expires_at,
            ))
        await session.commit()

    await message.answer(
        f"Готово. Проверил {len(results)} кластеров:\n"
        f"Релевантных: {counts['relevant']}\n"
        f"Нерелевантных: {counts['irrelevant']}\n"
        f"Спорных: {counts['borderline']}\n\n"
        f"Используй /review чтобы просмотреть и подтвердить."
    )


# ─── /review ──────────────────────────────────────────────────────────────────

@router.message(Command("review"))
async def cmd_review(message: Message) -> None:
    if not _admin_only(message):
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Decision, Keyword)
            .join(Keyword, Keyword.id == Decision.keyword_id)
            .where(
                Decision.who == DecisionWho.ai,
                Decision.status == DecisionStatus.pending,
                Decision.decision.in_([DecisionType.irrelevant, DecisionType.borderline]),
                Decision.expires_at > now,
            )
            .limit(10)
        )
        rows = result.all()

    if not rows:
        await message.answer("Нет предложений для проверки.")
        return

    await message.answer(f"Показываю {len(rows)} предложений AI:")

    for decision, keyword in rows:
        icon = "🔴" if decision.decision == DecisionType.irrelevant else "🟡"
        confidence_pct = int(decision.confidence * 100)

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Удалить", callback_data=f"dec:remove:{decision.id}"),
            InlineKeyboardButton(text="Оставить", callback_data=f"dec:keep:{decision.id}"),
            InlineKeyboardButton(text="Спорно", callback_data=f"dec:borderline:{decision.id}"),
        ]])

        await message.answer(
            f"{icon} <b>{keyword.phrase}</b>\n"
            f"AI: {decision.decision} ({confidence_pct}%)\n"
            f"Причина: {decision.reason}",
            reply_markup=kb,
        )


# ─── Callback: кнопки решений ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("dec:"))
async def on_decision_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != settings.admin_user_id:
        await callback.answer("Нет доступа")
        return

    _, action, dec_id_str = callback.data.split(":")
    dec_id = int(dec_id_str)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Decision, Keyword).join(Keyword).where(Decision.id == dec_id)
        )
        row = result.one_or_none()
        if not row:
            await callback.answer("Решение не найдено")
            return
        decision, keyword = row

        ai_decision = decision.decision

        if action == "remove":
            decision.decision = DecisionType.remove
            decision.who = DecisionWho.human
            decision.status = DecisionStatus.pending
            label = "Помечено к удалению"
        elif action == "keep":
            decision.status = DecisionStatus.applied
            decision.who = DecisionWho.human
            label = "Оставлено"
        else:
            decision.decision = DecisionType.borderline
            decision.who = DecisionWho.human
            label = "Отмечено как спорное"

        session.add(Feedback(
            keyword_id=keyword.id,
            client_id=(await session.execute(
                select(Campaign.client_id).where(Campaign.id == keyword.campaign_id)
            )).scalar_one(),
            ai_decision=ai_decision,
            human_decision=action,
        ))
        await session.commit()

    await callback.answer(label)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ {label}"
        )


# ─── /apply ───────────────────────────────────────────────────────────────────

@router.message(Command("apply"))
async def cmd_apply(message: Message) -> None:
    if not _admin_only(message):
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Decision, Keyword)
            .join(Keyword)
            .where(
                Decision.who == DecisionWho.human,
                Decision.decision == DecisionType.remove,
                Decision.status == DecisionStatus.pending,
                Decision.expires_at > now,
            )
        )
        rows = result.all()

    if not rows:
        await message.answer("Нет подтверждённых удалений для применения.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"Да, удалить {len(rows)} кластеров", callback_data="apply:confirm"),
        InlineKeyboardButton(text="Отмена", callback_data="apply:cancel"),
    ]])
    phrases = "\n".join(f"- {kw.phrase}" for _, kw in rows[:10])
    tail = f"\n... и ещё {len(rows) - 10}" if len(rows) > 10 else ""
    await message.answer(
        f"Применить {len(rows)} удалений?\n\n{phrases}{tail}",
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("apply:"))
async def on_apply_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != settings.admin_user_id:
        await callback.answer("Нет доступа")
        return

    action = callback.data.split(":")[1]
    if action == "cancel":
        await callback.answer("Отменено")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Decision, Keyword, Campaign)
            .join(Keyword, Keyword.id == Decision.keyword_id)
            .join(Campaign, Campaign.id == Keyword.campaign_id)
            .where(
                Decision.who == DecisionWho.human,
                Decision.decision == DecisionType.remove,
                Decision.status == DecisionStatus.pending,
                Decision.expires_at > now,
            )
        )
        rows = result.all()

    if not rows:
        await callback.answer("Нет записей")
        return

    from src.wb.client import WBClient
    from src.models import Client as ClientModel

    async with AsyncSessionLocal() as session:
        clients_result = await session.execute(select(ClientModel))
        clients_map = {c.id: c for c in clients_result.scalars().all()}

    applied, failed = 0, 0
    for decision, keyword, campaign in rows:
        client = clients_map.get(campaign.client_id)
        if not client:
            continue
        wb = WBClient(client.wb_token)
        try:
            await wb.exclude_keyword(campaign.wb_id, keyword.phrase)
            async with AsyncSessionLocal() as session:
                dec = await session.get(Decision, decision.id)
                if dec:
                    dec.status = DecisionStatus.applied
                    await session.commit()
            applied += 1
        except Exception as e:
            logger.error("exclude_keyword failed: %s", e)
            async with AsyncSessionLocal() as session:
                dec = await session.get(Decision, decision.id)
                if dec:
                    dec.status = DecisionStatus.failed
                    await session.commit()
            failed += 1
        finally:
            await wb.close()

    await callback.answer("Готово")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(
            f"Применено: удалено {applied} кластеров, ошибок {failed}."
        )


# ─── /bids ────────────────────────────────────────────────────────────────────

@router.message(Command("bids"))
async def cmd_bids(message: Message) -> None:
    if not _admin_only(message):
        return

    from src.rules.bidding import calculate_bid_action, BidAction

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Keyword, KeywordMetric)
            .join(KeywordMetric, KeywordMetric.keyword_id == Keyword.id)
            .order_by(KeywordMetric.date.desc())
            .limit(100)
        )
        rows = result.all()

    if not rows:
        await message.answer("Нет метрик. Сначала /pull.")
        return

    # Агрегируем последние метрики по каждому кластеру
    seen: set[int] = set()
    recommendations = []
    for keyword, metric in rows:
        if keyword.id in seen:
            continue
        seen.add(keyword.id)
        rec = calculate_bid_action(
            current_bid=100,  # заглушка — реальные ставки из WB API (Фаза 3+)
            views=metric.views,
            clicks=metric.clicks,
            orders=metric.orders,
            spend=metric.spend,
        )
        if rec.action != BidAction.keep:
            recommendations.append((keyword, metric, rec))

    if not recommendations:
        await message.answer("Все ставки в норме — изменений не требуется.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"Применить все ({len(recommendations)})", callback_data="bids:all"),
        InlineKeyboardButton(text="Отклонить всё", callback_data="bids:reject"),
    ]])

    lines = []
    for keyword, metric, rec in recommendations[:15]:
        arrow = "▲" if rec.action == BidAction.increase else "▼"
        lines.append(
            f"{arrow} <b>{keyword.phrase}</b>\n"
            f"   {rec.current_bid}р → {rec.new_bid}р | {rec.reason}"
        )

    tail = f"\n\n...и ещё {len(recommendations) - 15}" if len(recommendations) > 15 else ""
    await message.answer(
        "Рекомендации по ставкам:\n\n" + "\n\n".join(lines) + tail,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("bids:"))
async def on_bids_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != settings.admin_user_id:
        await callback.answer("Нет доступа")
        return

    action = callback.data.split(":")[1]
    if action == "reject":
        await callback.answer("Отклонено")
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.edit_text(callback.message.text + "\n\n❌ Отклонено")
        return

    # action == "all" — применяем (заглушка до получения реальных ставок из WB)
    await callback.answer("Ставки применены (тест-режим)")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(callback.message.text + "\n\n✅ Ставки применены")
