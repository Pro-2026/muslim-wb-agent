import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.bot.setup import bot
from src.config import settings
from src.database import AsyncSessionLocal
from src.models import Client
from sqlalchemy import select

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


async def _pull_all_clients() -> None:
    from src.wb.sync import sync_client

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Client))
        clients = result.scalars().all()

    if not clients:
        logger.info("No clients configured, skipping pull")
        return

    for client in clients:
        try:
            async with AsyncSessionLocal() as session:
                campaigns, keywords = await sync_client(session, client)
            logger.info("Pull OK client=%d: %d campaigns, %d keywords", client.id, campaigns, keywords)
        except Exception as e:
            logger.exception("Pull failed for client %d: %s", client.id, e)
            try:
                await bot.send_message(
                    settings.admin_user_id,
                    f"Ошибка синхронизации WB: <code>{e}</code>",
                )
            except Exception:
                pass


def setup_scheduler() -> None:
    scheduler.add_job(
        _pull_all_clients,
        trigger=IntervalTrigger(hours=3),
        id="wb_pull",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: WB pull every 3h")
