"""Claude-powered recommendation explanations.

If ANTHROPIC_API_KEY is configured (or an `ant auth login` profile is active),
one Claude call rewrites the template reasons into personalized blurbs.
Failures fall back silently to the template reasons so the app never breaks
without a key.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional

from .catalog import FLAVOR_KEYS

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"
VISION_MODEL = "claude-opus-5"

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic()
    except Exception:
        logger.exception("Could not initialize Anthropic client")
        _client = None
    return _client


MENU_SCHEMA = {
    "type": "object",
    "properties": {
        "beers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "brewery": {"type": ["string", "null"]},
                    "style": {"type": "string"},
                    "abv": {"type": "number"},
                    "ibu": {"type": "number"},
                    "flavors": {
                        "type": "object",
                        "properties": {k: {"type": "number"} for k in FLAVOR_KEYS},
                        "required": list(FLAVOR_KEYS),
                        "additionalProperties": False,
                    },
                },
                "required": ["name", "brewery", "style", "abv", "ibu", "flavors"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["beers"],
    "additionalProperties": False,
}

MENU_PROMPT = (
    "This photo shows a menu from a bar or restaurant. Extract every distinct "
    "beer offered for sale (draft, bottle, or can). Ignore wine, cocktails, "
    "spirits, ciders, food, and section headers.\n\n"
    "For each beer:\n"
    "- name: exactly as printed on the menu\n"
    "- brewery: if printed, else null\n"
    "- style: a conventional beer style name (e.g. 'Hazy IPA', 'Stout', "
    "'Pilsner') — infer from the name or description if not printed\n"
    "- abv: the printed value if shown, otherwise a typical estimate for the style\n"
    "- ibu: the printed value if shown, otherwise a typical estimate for the style\n"
    "- flavors: your estimate of this beer's flavor profile, each axis from "
    "0.0 to 1.0: " + ", ".join(FLAVOR_KEYS) + "\n\n"
    "If the image is not a menu or contains no beers, return an empty beers array."
)


def is_configured() -> bool:
    """True when an Anthropic client is available (API key or auth token set)."""
    return _get_client() is not None


def extract_menu_beers(image_base64: str, media_type: str) -> Optional[List[dict]]:
    """Read a beer-menu photo with Claude vision.

    Returns a list of {name, brewery, style, abv, ibu, flavors} dicts, [] when
    the image contains no beers, or None on any failure.
    """
    client = _get_client()
    if client is None:
        return None
    try:
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=16000,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": MENU_SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {"type": "text", "text": MENU_PROMPT},
                    ],
                }
            ],
        )
        if response.stop_reason == "refusal":
            logger.warning("Menu scan refused by safety classifiers")
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        beers = json.loads(text)["beers"]
        return beers if isinstance(beers, list) else None
    except Exception:
        logger.exception("Claude menu extraction failed")
        return None


def personalize_reasons(liked: List[dict], taste_text: str, recs: List[dict]) -> Dict[int, str]:
    """Return {beer_id: blurb} for each recommendation, or {} on any failure."""
    client = _get_client()
    if client is None or not recs:
        return {}

    liked_desc = "; ".join(f"{b['name']} ({b['style']})" for b in liked) or "none listed"
    recs_desc = "\n".join(
        f"- id={b['id']}: {b['name']} by {b['brewery']} — {b['style']}, "
        f"{b['abv']}% ABV, {b['ibu']} IBU. {b['description']}"
        for b in recs
    )
    prompt = (
        "You are a friendly beer sommelier for a recommendation app.\n"
        f"The user likes these beers: {liked_desc}.\n"
        f"Their stated taste preferences: {taste_text or 'none given'}.\n\n"
        "We are recommending these beers:\n"
        f"{recs_desc}\n\n"
        "For each recommended beer, write one enthusiastic but specific sentence "
        "(max 25 words) explaining why THIS user will like it, referencing their "
        "tastes. Respond with ONLY a JSON object mapping beer id (as a string) to "
        'the sentence, e.g. {"3": "..."}.'
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        parsed = json.loads(match.group(0))
        return {int(k): str(v) for k, v in parsed.items() if str(k).isdigit()}
    except Exception:
        logger.exception("Claude personalization failed; using template reasons")
        return {}
