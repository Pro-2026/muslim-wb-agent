import asyncio
import logging
from datetime import date

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://advert-api.wildberries.ru"
_RATE_LIMIT_SLEEP = 1.0


class WBApiError(Exception):
    pass


class WBClient:
    def __init__(self, token: str) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": token},
            timeout=30,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        await asyncio.sleep(_RATE_LIMIT_SLEEP)
        for attempt in range(4):
            try:
                resp = await self._client.request(method, path, **kwargs)
                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("WB rate limit, retry in %ds", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("WB 5xx (%d), retry in %ds", resp.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                logger.debug("WB %s %s → %d", method, path, resp.status_code)
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == 3:
                    raise WBApiError(f"WB API error: {e}") from e
        raise WBApiError("WB API: max retries exceeded")

    async def get_campaigns(self) -> list[dict]:
        """Список всех рекламных кампаний."""
        data = await self._request("GET", "/adv/v1/promotion/adverts")
        return data if isinstance(data, list) else []

    async def get_campaign_stats(
        self, campaign_id: int, date_from: date, date_to: date
    ) -> list[dict]:
        """Статистика по кампании за период."""
        data = await self._request(
            "POST",
            "/adv/v2/fullstats",
            json=[
                {
                    "id": campaign_id,
                    "dates": [date_from.isoformat(), date_to.isoformat()],
                }
            ],
        )
        return data if isinstance(data, list) else []

    async def get_keywords(self, campaign_id: int) -> list[dict]:
        """Поисковые кластеры с метриками по кампании."""
        data = await self._request(
            "GET",
            "/adv/v1/stat/words",
            params={"id": campaign_id},
        )
        # WB возвращает {'words': {'clusters': [...]}, ...}
        if isinstance(data, dict):
            return data.get("words", {}).get("clusters", [])
        return []

    async def exclude_keyword(self, campaign_id: int, keyword: str) -> None:
        """Добавить фразу в минус-слова кампании."""
        await self._request(
            "POST",
            f"/adv/v1/setkeyword",
            json={"advertId": campaign_id, "excluded": [keyword]},
        )

    async def restore_keyword(self, campaign_id: int, keyword: str) -> None:
        """Убрать фразу из минус-слов кампании."""
        await self._request(
            "DELETE",
            f"/adv/v1/setkeyword",
            json={"advertId": campaign_id, "excluded": [keyword]},
        )
