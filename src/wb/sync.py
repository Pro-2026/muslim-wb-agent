import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Campaign, Client, Keyword, KeywordMetric
from src.wb.client import WBClient

logger = logging.getLogger(__name__)


async def sync_client(session: AsyncSession, client: Client) -> tuple[int, int]:
    """Тянет кампании и кластеры из WB, сохраняет upsert. Возвращает (campaigns, keywords)."""
    wb = WBClient(client.wb_token)
    try:
        raw_campaigns = await wb.get_campaigns()
    finally:
        await wb.close()

    campaign_count = 0
    keyword_count = 0
    date_to = date.today() - timedelta(days=1)
    date_from = date_to - timedelta(days=6)

    for rc in raw_campaigns:
        wb_id = rc.get("advertId") or rc.get("id")
        if not wb_id:
            continue

        result = await session.execute(
            select(Campaign).where(
                Campaign.client_id == client.id, Campaign.wb_id == wb_id
            )
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            campaign = Campaign(
                client_id=client.id,
                wb_id=wb_id,
                name=rc.get("name", ""),
                campaign_type=str(rc.get("type", "")),
                status=str(rc.get("status", "")),
            )
            session.add(campaign)
            await session.flush()
        else:
            campaign.name = rc.get("name", campaign.name)
            campaign.status = str(rc.get("status", campaign.status))
        campaign_count += 1

        wb2 = WBClient(client.wb_token)
        try:
            clusters = await wb2.get_keywords(wb_id)
            stats = await wb2.get_campaign_stats(wb_id, date_from, date_to)
        finally:
            await wb2.close()

        stats_map: dict[str, dict] = {}
        for s in stats:
            for day in s.get("days", []):
                for kw in day.get("apps", []) + day.get("keywords", []):
                    phrase = kw.get("keyword", "")
                    if phrase:
                        entry = stats_map.setdefault(phrase, {})
                        entry["views"] = entry.get("views", 0) + kw.get("views", 0)
                        entry["clicks"] = entry.get("clicks", 0) + kw.get("clicks", 0)
                        entry["orders"] = entry.get("orders", 0) + kw.get("orders", 0)
                        entry["spend"] = entry.get("spend", 0.0) + kw.get("sum", 0.0)

        for cluster in clusters:
            phrase = cluster.get("cluster", "") or cluster.get("keyword", "")
            if not phrase:
                continue

            result = await session.execute(
                select(Keyword).where(
                    Keyword.campaign_id == campaign.id, Keyword.phrase == phrase
                )
            )
            kw_obj = result.scalar_one_or_none()
            if kw_obj is None:
                kw_obj = Keyword(
                    campaign_id=campaign.id,
                    phrase=phrase,
                    cluster=cluster.get("cluster", phrase),
                )
                session.add(kw_obj)
                await session.flush()
            keyword_count += 1

            m = stats_map.get(phrase, {})
            if m:
                clicks = m.get("clicks", 0)
                views = m.get("views", 0)
                spend = m.get("spend", 0.0)
                orders = m.get("orders", 0)
                metric = KeywordMetric(
                    keyword_id=kw_obj.id,
                    date=date_to,
                    views=views,
                    clicks=clicks,
                    orders=orders,
                    spend=spend,
                    ctr=clicks / views if views else 0.0,
                    cpo=spend / orders if orders else 0.0,
                )
                session.add(metric)

    await session.commit()
    logger.info(
        "sync client=%d: %d campaigns, %d keywords", client.id, campaign_count, keyword_count
    )
    return campaign_count, keyword_count
