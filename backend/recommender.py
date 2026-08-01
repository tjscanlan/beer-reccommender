"""Content-based beer recommender.

Builds a flavor-profile vector for each beer (8 flavor axes + normalized
ABV/IBU) and scores candidates by cosine similarity against a taste profile
derived from the user's liked beers and/or free-text preferences.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np

from .catalog import BEERS, BEERS_BY_ID, FLAVOR_KEYS

ABV_MAX = 15.0
IBU_MAX = 100.0

# Keyword → flavor-axis nudges used when parsing free-text preferences
# without an LLM. Values are added to the profile then re-clipped to [0, 1].
KEYWORD_NUDGES: Dict[str, Dict[str, float]] = {
    "hoppy": {"hoppy": 0.9, "bitter": 0.5},
    "hops": {"hoppy": 0.9, "bitter": 0.5},
    "ipa": {"hoppy": 0.9, "bitter": 0.5, "fruity": 0.3},
    "juicy": {"fruity": 0.8, "hoppy": 0.6, "bitter": -0.3},
    "hazy": {"fruity": 0.7, "hoppy": 0.7, "bitter": -0.3},
    "tropical": {"fruity": 0.8, "hoppy": 0.5},
    "citrus": {"fruity": 0.7, "hoppy": 0.5},
    "dark": {"roasty": 0.8, "malty": 0.6},
    "stout": {"roasty": 0.9, "malty": 0.7},
    "porter": {"roasty": 0.8, "malty": 0.6},
    "coffee": {"roasty": 0.9, "malty": 0.5},
    "chocolate": {"roasty": 0.7, "sweet": 0.5, "malty": 0.6},
    "roasty": {"roasty": 0.9, "malty": 0.5},
    "malty": {"malty": 0.9, "sweet": 0.3},
    "caramel": {"malty": 0.8, "sweet": 0.5},
    "sweet": {"sweet": 0.8, "bitter": -0.4},
    "dessert": {"sweet": 0.9, "roasty": 0.4},
    "sour": {"sour": 0.9, "fruity": 0.4},
    "tart": {"sour": 0.8, "fruity": 0.4},
    "funky": {"sour": 0.6, "fruity": 0.3},
    "fruity": {"fruity": 0.9},
    "fruit": {"fruity": 0.8},
    "cherry": {"fruity": 0.8, "sour": 0.4},
    "banana": {"fruity": 0.7, "sweet": 0.3},
    "wheat": {"fruity": 0.5, "crisp": 0.4, "bitter": -0.3},
    "hefeweizen": {"fruity": 0.7, "crisp": 0.4, "bitter": -0.4},
    "belgian": {"fruity": 0.6, "sweet": 0.3},
    "crisp": {"crisp": 0.9, "bitter": -0.2},
    "light": {"crisp": 0.8, "bitter": -0.4, "sweet": -0.2},
    "refreshing": {"crisp": 0.8},
    "clean": {"crisp": 0.7},
    "lager": {"crisp": 0.8, "hoppy": -0.2},
    "pilsner": {"crisp": 0.9, "hoppy": 0.3},
    "session": {"crisp": 0.6},
    "smooth": {"crisp": 0.3, "bitter": -0.3},
    "bitter": {"bitter": 0.8, "hoppy": 0.6},
    "piney": {"hoppy": 0.8, "bitter": 0.6},
    "strong": {"sweet": 0.2, "malty": 0.3},
    "boozy": {"sweet": 0.3, "malty": 0.4},
}

NEGATION_WORDS = ("not ", "no ", "don't like ", "dont like ", "hate ", "avoid ", "less ", "without ")


def beer_vector(beer: dict) -> np.ndarray:
    flavors = [beer["flavors"][k] for k in FLAVOR_KEYS]
    return np.array(
        flavors + [min(beer["abv"], ABV_MAX) / ABV_MAX, min(beer["ibu"], IBU_MAX) / IBU_MAX],
        dtype=np.float64,
    )


BEER_MATRIX = np.stack([beer_vector(b) for b in BEERS])
BEER_IDS = [b["id"] for b in BEERS]


def profile_from_text(text: str) -> Optional[np.ndarray]:
    """Heuristic keyword parse of free-text taste preferences into a flavor profile."""
    lowered = text.lower()
    profile = {k: 0.0 for k in FLAVOR_KEYS}
    matched = False
    for keyword, nudges in KEYWORD_NUDGES.items():
        if keyword not in lowered:
            continue
        matched = True
        idx = lowered.find(keyword)
        preceding = lowered[max(0, idx - 15):idx]
        negated = any(neg in preceding for neg in NEGATION_WORDS)
        for axis, weight in nudges.items():
            profile[axis] += -weight if negated else weight
    if not matched:
        return None
    flavors = np.clip([profile[k] for k in FLAVOR_KEYS], 0.0, 1.0)
    # Neutral ABV/IBU midpoints; strength keywords shift ABV.
    abv = 0.4
    if any(w in lowered for w in ("strong", "boozy", "high abv", "imperial")):
        abv = 0.7
    if any(w in lowered for w in ("light", "low abv", "session", "easy")):
        abv = 0.25
    ibu = float(np.clip(profile.get("bitter", 0.0), 0.05, 1.0)) * 0.8
    return np.concatenate([flavors, [abv, ibu]])


def build_profile(liked_ids: List[int], taste_text: str = "") -> Tuple[Optional[np.ndarray], List[dict]]:
    """Average the liked beers' vectors, blended with any free-text profile."""
    liked = [BEERS_BY_ID[i] for i in liked_ids if i in BEERS_BY_ID]
    vectors = [beer_vector(b) for b in liked]
    text_vec = profile_from_text(taste_text) if taste_text else None
    if vectors and text_vec is not None:
        profile = 0.65 * np.mean(vectors, axis=0) + 0.35 * text_vec
    elif vectors:
        profile = np.mean(vectors, axis=0)
    elif text_vec is not None:
        profile = text_vec
    else:
        return None, liked
    return profile, liked


def recommend(liked_ids: List[int], taste_text: str = "", limit: int = 5) -> List[dict]:
    profile, liked = build_profile(liked_ids, taste_text)
    if profile is None:
        # No signal at all: return a diverse sampler across styles.
        seen_styles = set()
        sampler = []
        for beer in BEERS:
            if beer["style"] in seen_styles:
                continue
            seen_styles.add(beer["style"])
            sampler.append({**beer, "score": 0.0, "reason": "A crowd-pleasing pick to help us learn your taste."})
            if len(sampler) >= limit:
                break
        return sampler

    norms = np.linalg.norm(BEER_MATRIX, axis=1) * (np.linalg.norm(profile) or 1.0)
    scores = BEER_MATRIX @ profile / np.where(norms == 0, 1.0, norms)

    liked_set = set(liked_ids)
    liked_styles = {b["style"] for b in liked}
    ranked = sorted(zip(BEER_IDS, scores), key=lambda pair: pair[1], reverse=True)

    results = []
    style_counts: Dict[str, int] = {}
    for beer_id, score in ranked:
        if beer_id in liked_set:
            continue
        beer = BEERS_BY_ID[beer_id]
        # Cap two per style so results aren't five near-identical IPAs.
        if style_counts.get(beer["style"], 0) >= 2:
            continue
        style_counts[beer["style"]] = style_counts.get(beer["style"], 0) + 1
        results.append({**beer, "score": round(float(score), 3), "reason": _fallback_reason(beer, profile, liked_styles)})
        if len(results) >= limit:
            break
    return results


def rank_candidates(candidates: List[dict], liked_ids: List[int], taste_text: str = "") -> List[dict]:
    """Score an arbitrary candidate list (e.g. beers read off a menu) against
    the user's profile.

    Unlike recommend(), the candidate set is fixed (it's the menu), so there is
    no per-style cap and liked beers are not excluded — a favorite appearing on
    the menu is the best possible order.
    """
    if not candidates:
        return []
    profile, liked = build_profile(liked_ids, taste_text)
    if profile is None:
        return [
            {**b, "score": 0.0, "reason": "We don't know your taste yet — this is a solid pick from the menu."}
            for b in candidates
        ]
    matrix = np.stack([beer_vector(b) for b in candidates])
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(profile) or 1.0)
    scores = matrix @ profile / np.where(norms == 0, 1.0, norms)
    liked_styles = {b["style"] for b in liked}
    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    return [
        {**b, "score": round(float(s), 3), "reason": _fallback_reason(b, profile, liked_styles)}
        for b, s in ranked
    ]


def _fallback_reason(beer: dict, profile: np.ndarray, liked_styles: set) -> str:
    """Template reason used when no Claude API key is configured."""
    flavor_vals = profile[: len(FLAVOR_KEYS)]
    top_axes = [FLAVOR_KEYS[i] for i in np.argsort(flavor_vals)[::-1][:2] if flavor_vals[i] > 0.3]
    parts = []
    if beer["style"] in liked_styles:
        parts.append(f"another standout {beer['style']}")
    if top_axes:
        matched = [a for a in top_axes if beer["flavors"][a] >= 0.5]
        if matched:
            parts.append("matches your taste for " + " and ".join(matched) + " beers")
    if not parts:
        parts.append("a close match to your overall flavor profile")
    return "Recommended because it's " + ", and ".join(parts) + "."
