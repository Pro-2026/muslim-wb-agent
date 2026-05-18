import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings

logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


async def setup_bot() -> None:
    from src.bot.handlers import router
    dp.include_router(router)

    if settings.railway_public_domain:
        await bot.set_webhook(settings.webhook_url)
        logger.info("Webhook set: %s", settings.webhook_url)
    else:
        # Локально: сбрасываем webhook, чтобы не было конфликта
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared (local mode)")
