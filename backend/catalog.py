"""Beer catalog: loads the bundled dataset and exposes lookup/search helpers."""
import json
from pathlib import Path
from typing import Dict, List, Optional

DATA_PATH = Path(__file__).parent / "data" / "beers.json"

FLAVOR_KEYS = ["hoppy", "malty", "bitter", "sweet", "roasty", "fruity", "sour", "crisp"]


def load_beers() -> List[dict]:
    with open(DATA_PATH) as f:
        return json.load(f)


BEERS: List[dict] = load_beers()
BEERS_BY_ID: Dict[int, dict] = {b["id"]: b for b in BEERS}


def get_beer(beer_id: int) -> Optional[dict]:
    return BEERS_BY_ID.get(beer_id)


def search_beers(query: str, limit: int = 10) -> List[dict]:
    q = query.lower().strip()
    if not q:
        return []
    results = []
    for beer in BEERS:
        haystack = " ".join([beer["name"], beer["brewery"], beer["style"]]).lower()
        if q in haystack:
            results.append(beer)
    return results[:limit]
