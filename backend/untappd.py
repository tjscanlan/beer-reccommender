"""Untappd API client (optional).

Untappd's public API (https://untappd.com/api/docs) requires a client ID and
secret, and registration has been closed to new applicants for some time. If
UNTAPPD_CLIENT_ID / UNTAPPD_CLIENT_SECRET are set in the environment (.env),
beer search proxies to Untappd; otherwise the app searches the bundled catalog.
"""
import logging
import os
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.untappd.com/v4"


def has_credentials() -> bool:
    return bool(os.environ.get("UNTAPPD_CLIENT_ID") and os.environ.get("UNTAPPD_CLIENT_SECRET"))


def _auth_params() -> dict:
    return {
        "client_id": os.environ["UNTAPPD_CLIENT_ID"],
        "client_secret": os.environ["UNTAPPD_CLIENT_SECRET"],
    }


async def search_beer(query: str, limit: int = 10) -> Optional[List[dict]]:
    """Search Untappd for beers. Returns None if unavailable so callers can fall back."""
    if not has_credentials():
        return None
    # Untappd auth is query-string only, so the request URL contains the client
    # secret — never log the URL or exception messages/tracebacks that embed it
    # (httpx's HTTPStatusError message includes the full URL).
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{BASE_URL}/search/beer",
                params={**_auth_params(), "q": query, "limit": limit},
            )
            resp.raise_for_status()
            items = resp.json()["response"]["beers"]["items"]
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Untappd search returned HTTP %s; falling back to local catalog",
            exc.response.status_code,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Untappd search failed (%s); falling back to local catalog",
            type(exc).__name__,
        )
        return None

    results = []
    for item in items:
        beer = item.get("beer", {})
        brewery = item.get("brewery", {})
        results.append({
            "untappd_bid": beer.get("bid"),
            "name": beer.get("beer_name"),
            "brewery": brewery.get("brewery_name"),
            "style": beer.get("beer_style"),
            "abv": beer.get("beer_abv"),
            "ibu": beer.get("beer_ibu"),
            "description": beer.get("beer_description", ""),
            "label": beer.get("beer_label"),
        })
    return results
