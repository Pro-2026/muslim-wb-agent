import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal
from src.models import Client

logger = logging.getLogger(__name__)
router = Router()


def _admin_only(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.admin_user_id)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я WB AI-агент Муслима.\n\n"
        "Команды:\n"
        "/ping — проверить связь\n"
        "/pull — подтянуть данные из WB\n"
        "/status — состояние сервиса"
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    if not _admin_only(message):
        return
    await message.answer("pong")


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
            "Когда получишь WB-токен — добавь клиента через базу данных:\n"
            "<code>INSERT INTO clients (name, wb_token, telegram_chat_id) "
            "VALUES ('Муслим', 'TOKEN', CHAT_ID);</code>"
        )


@router.message(Command("pull"))
async def cmd_pull(message: Message) -> None:
    if not _admin_only(message):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()

    if not clients:
        await message.answer(
            "Нет клиентов в базе. Сначала добавь WB-токен командой /status."
        )
        return

    await message.answer("Синхронизирую данные из WB...")

    total_campaigns = 0
    total_keywords = 0
    errors = []

    from src.wb.sync import sync_client

    for client in clients:
        try:
            async with AsyncSessionLocal() as session:
                c, k = await sync_client(session, client)
            total_campaigns += c
            total_keywords += k
        except Exception as e:
            logger.exception("pull error for client %d", client.id)
            errors.append(str(e))

    if errors:
        await message.answer(
            f"Готово с ошибками:\n"
            f"Кампаний: {total_campaigns}, кластеров: {total_keywords}\n"
            f"Ошибки: {'; '.join(errors)}"
        )
    else:
        await message.answer(
            f"Готово.\n"
            f"Кампаний: {total_campaigns}\n"
            f"Кластеров: {total_keywords}"
        )
