"""Resolve Claude-extracted menu entries into rankable beer candidates.

Pure logic (no API calls): fuzzy-match extracted names against the bundled
catalog so known beers use their real data, and sanitize AI-estimated
profiles for the rest so everything is safe to feed to beer_vector().
"""
import re
from difflib import SequenceMatcher
from typing import List, Optional

from .catalog import BEERS, FLAVOR_KEYS
from .recommender import ABV_MAX, IBU_MAX

NAME_THRESHOLD = 0.85
NAME_WITH_BREWERY_THRESHOLD = 0.72
BREWERY_THRESHOLD = 0.8

DEFAULT_ABV = 5.0
DEFAULT_IBU = 30.0


_BREWERY_NOISE = {"brewery", "brewing", "brewers", "beer", "co", "company", "ales"}


def _norm(s: str) -> str:
    lowered = str(s).lower().replace("'", "").replace("’", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", lowered)).strip()


def _strip_brewery_noise(s: str) -> str:
    return " ".join(w for w in s.split() if w not in _BREWERY_NOISE)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_catalog_beer(name: str, brewery: Optional[str]) -> Optional[dict]:
    """Best catalog match for an extracted menu entry, or None.

    Accept on strong name similarity alone, or moderate name similarity when
    the brewery also matches. Menu names are compared against both the catalog
    name and "brewery name" (menus often print "Founders Breakfast Stout").
    """
    menu_name = _norm(name)
    menu_brewery = _norm(brewery) if brewery else ""
    if not menu_name:
        return None

    best_beer = None
    best_score = 0.0
    for beer in BEERS:
        cat_name = _norm(beer["name"])
        combined = _strip_brewery_noise(_norm(f"{beer['brewery']} {beer['name']}"))
        name_sim = max(_similarity(menu_name, cat_name), _similarity(menu_name, combined))
        brewery_sim = _similarity(menu_brewery, _norm(beer["brewery"])) if menu_brewery else 0.0
        accepted = name_sim >= NAME_THRESHOLD or (
            name_sim >= NAME_WITH_BREWERY_THRESHOLD and brewery_sim >= BREWERY_THRESHOLD
        )
        if accepted and name_sim > best_score:
            best_score = name_sim
            best_beer = beer
    return best_beer


def _clamp(value, lo: float, hi: float, default: float) -> float:
    try:
        return min(max(float(value), lo), hi)
    except (TypeError, ValueError):
        return default


def resolve_menu_beers(extracted: List[dict]) -> List[dict]:
    """Turn extracted menu entries into candidate dicts safe for beer_vector().

    Matched entries carry the full catalog record; unmatched ones keep the
    AI-estimated profile with values clamped to sane ranges. Duplicate menu
    lines (same beer in two sizes) and double-matches are dropped.
    """
    candidates = []
    seen_names = set()
    seen_ids = set()
    for entry in extracted:
        name = str(entry.get("name") or "").strip()
        if not name or _norm(name) in seen_names:
            continue
        seen_names.add(_norm(name))

        brewery = entry.get("brewery")
        matched = match_catalog_beer(name, brewery)
        if matched is not None:
            if matched["id"] in seen_ids:
                continue
            seen_ids.add(matched["id"])
            candidates.append({**matched, "matched": True, "menu_name": name})
            continue

        raw_flavors = entry.get("flavors") or {}
        flavors = {k: _clamp(raw_flavors.get(k), 0.0, 1.0, 0.0) for k in FLAVOR_KEYS}
        candidates.append({
            "id": None,
            "name": name,
            "brewery": str(brewery).strip() if brewery else "Unknown brewery",
            "style": str(entry.get("style") or "Beer").strip(),
            "abv": _clamp(entry.get("abv"), 0.0, ABV_MAX, DEFAULT_ABV),
            "ibu": _clamp(entry.get("ibu"), 0.0, IBU_MAX, DEFAULT_IBU),
            "flavors": flavors,
            "description": "",
            "matched": False,
            "menu_name": name,
        })
    return candidates
