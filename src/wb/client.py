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
                    wait = 60 * (attempt + 1)
                    logger.warning("WB rate limit 429, retry in %ds", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("WB 5xx (%d), retry in %ds", resp.status_code, wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                logger.debug("WB %s %s -> %d", method, path, resp.status_code)
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == 3:
                    raise WBApiError(f"WB API error {e.response.status_code}: {e.response.text[:200]}") from e
        raise WBApiError("WB API: max retries exceeded")

    async def get_campaigns(self) -> list[dict]:
        """
        Шаг 1: получить все ID кампаний через /count.
        Шаг 2: получить детали батчами по 50 через POST /adverts.
        """
        count_data = await self._request("GET", "/adv/v1/promotion/count")

        all_ids: list[int] = []
        for group in count_data.get("adverts", []):
            for item in group.get("advert_list", []):
                all_ids.append(item["advertId"])

        if not all_ids:
            return []

        campaigns: list[dict] = []
        for i in range(0, len(all_ids), 50):
            batch = all_ids[i:i + 50]
            data = await self._request("POST", "/adv/v1/promotion/adverts", json=batch)
            if isinstance(data, list):
                campaigns.extend(data)
            await asyncio.sleep(_RATE_LIMIT_SLEEP)

        return campaigns

    async def get_campaign_stats(
        self, campaign_id: int, date_from: date, date_to: date
    ) -> list[dict]:
        """Статистика по кампании за период."""
        data = await self._request(
            "POST",
            "/adv/v2/fullstats",
            json=[{"id": campaign_id, "dates": [date_from.isoformat(), date_to.isoformat()]}],
        )
        return data if isinstance(data, list) else []

    async def get_keywords(self, campaign_id: int) -> list[dict]:
        """Поисковые кластеры по кампании."""
        data = await self._request("GET", "/adv/v1/stat/words", params={"id": campaign_id})
        if isinstance(data, dict):
            return data.get("words", {}).get("clusters", [])
        return []

    async def exclude_keyword(self, campaign_id: int, keyword: str) -> None:
        """Добавить фразу в минус-слова."""
        await self._request(
            "POST", "/adv/v1/setkeyword",
            json={"advertId": campaign_id, "excluded": [keyword]},
        )

    async def restore_keyword(self, campaign_id: int, keyword: str) -> None:
        """Убрать фразу из минус-слов."""
        await self._request(
            "DELETE", "/adv/v1/setkeyword",
            json={"advertId": campaign_id, "excluded": [keyword]},
        )
