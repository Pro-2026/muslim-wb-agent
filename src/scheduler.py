import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update

from src.bot.setup import bot
from src.config import settings
from src.database import AsyncSessionLocal
from src.models import Client, Decision, DecisionStatus

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


async def _expire_stale_decisions() -> None:
    """Переводит просроченные pending-решения в статус expired."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Decision)
            .where(
                Decision.status == DecisionStatus.pending,
                Decision.expires_at < now,
            )
            .values(status=DecisionStatus.expired)
            .returning(Decision.id)
        )
        expired_ids = result.scalars().all()
        await session.commit()
    if expired_ids:
        logger.info("Expired %d stale decisions", len(expired_ids))


def setup_scheduler() -> None:
    scheduler.add_job(
        _pull_all_clients,
        trigger=IntervalTrigger(hours=3),
        id="wb_pull",
        replace_existing=True,
    )
    scheduler.add_job(
        _expire_stale_decisions,
        trigger=IntervalTrigger(hours=3),
        id="expire_decisions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started: WB pull + TTL expiry every 3h")
