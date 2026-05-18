from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import settings

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Я WB AI-агент Муслима.\n\n"
        "Управляю рекламными кампаниями на Wildberries.\n"
        "/ping — проверить связь"
    )


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    if message.from_user and message.from_user.id != settings.admin_user_id:
        return
    await message.answer("pong")
