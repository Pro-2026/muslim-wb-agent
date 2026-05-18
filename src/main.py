import logging
from contextlib import asynccontextmanager

import sentry_sdk

from aiogram.types import Update
from fastapi import FastAPI, Request, Response

from src.bot.setup import bot, dp, setup_bot
from src.config import settings
from src.database import Base, engine
import src.models  # noqa: F401 — register all models with Base
from src.scheduler import setup_scheduler, scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
    logger.info("Sentry initialized")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await setup_bot()
    setup_scheduler()
    logger.info("Service started")
    yield
    scheduler.shutdown(wait=False)
    await bot.session.close()
    await engine.dispose()
    logger.info("Service stopped")


app = FastAPI(title="WB AI Agent", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post(settings.webhook_path)
async def webhook(request: Request) -> Response:
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return Response()
