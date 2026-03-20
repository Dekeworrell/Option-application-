from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


class PolygonClient:
    """
    Minimal Polygon client used by scan_service and dashboard option lookups.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY is not set (env var missing).")

        self.base_url = (
            base_url or os.getenv("POLYGON_BASE_URL") or "https://api.polygon.io"
        ).rstrip("/")

    async def _get_json(self, url: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            resp = await client.get(url, params={**(params or {}), "apiKey": self.api_key})

        if resp.status_code == 403:
            return {}

        resp.raise_for_status()
        return resp.json()

    async def markets_status(self) -> dict:
        return await self._get_json("/v1/marketstatus/now")

    async def get_prev_close(self, symbol: str) -> float:
        data = await self._get_json(f"/v2/aggs/ticker/{symbol.upper()}/prev")

        results = data.get("results") or []
        if not results:
            raise ValueError(f"No prev close data returned for {symbol}")

        prev_close = results[0].get("c")
        if prev_close is None:
            raise ValueError(f"Prev close missing 'c' field for {symbol}")

        return float(prev_close)

    async def get_daily_bars(self, symbol: str, days_back: int = 90) -> dict:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days_back)

        path = f"/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start.isoformat()}/{today.isoformat()}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
        }
        return await self._get_json(path, params=params)

    async def get_option_chain_snapshot(
        self,
        underlying: str,
        expiration_date: str | None = None,
        contract_type: str | None = None,
        limit: int = 250,
        max_pages: int = 8,
    ) -> list[dict]:
        """
        GET /v3/snapshot/options/{underlying}
        Fetches multiple pages so contract selection is not based on a tiny slice
        of the option chain.
        """
        params: dict[str, str | int] = {
            "limit": limit,
        }

        if expiration_date:
            params["expiration_date"] = expiration_date

        if contract_type:
            normalized = contract_type.lower().strip()
            if normalized not in {"call", "put"}:
                raise ValueError("contract_type must be 'call', 'put', or None")
            params["contract_type"] = normalized

        all_results: list[dict] = []
        next_path = f"/v3/snapshot/options/{underlying.upper()}"
        next_params: dict[str, str | int] | None = params
        page_count = 0

        while next_path and page_count < max_pages:
            data = await self._get_json(next_path, params=next_params)
            page_results = data.get("results") or []

            if page_results:
                all_results.extend(page_results)

            next_url = data.get("next_url")
            if not next_url:
                break

            if next_url.startswith(self.base_url):
                next_path = next_url.replace(self.base_url, "", 1)
            else:
                next_path = next_url

            next_params = None
            page_count += 1

        return all_results