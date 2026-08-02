"""Claude-powered recommendation explanations.

If ANTHROPIC_API_KEY is configured (or an `ant auth login` profile is active),
one Claude call rewrites the template reasons into personalized blurbs.
Failures fall back silently to the template reasons so the app never breaks
without a key.
"""
import datetime
import json
import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

MODEL = "claude-opus-4-8"

# /api/recommend is publicly reachable once deployed, so cap how many Claude
# calls a single process will make per UTC day — a hard ceiling on API spend
# even if the endpoint is hammered. The app degrades to template reasons.
# (Per-process: on Lambda each concurrent container counts separately, so the
# true ceiling is roughly limit x reserved concurrency.)
AI_DAILY_CALL_LIMIT = int(os.environ.get("AI_DAILY_CALL_LIMIT", "200"))

_calls_today = 0
_calls_day: "datetime.date" = datetime.date.min

_client = None
_client_checked = False


def _under_daily_limit() -> bool:
    global _calls_today, _calls_day
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if today != _calls_day:
        _calls_day = today
        _calls_today = 0
    if _calls_today >= AI_DAILY_CALL_LIMIT:
        if _calls_today == AI_DAILY_CALL_LIMIT:
            _calls_today += 1  # log the cutoff once per day, not per request
            logger.warning(
                "AI_DAILY_CALL_LIMIT (%d) reached; using template reasons until tomorrow",
                AI_DAILY_CALL_LIMIT,
            )
        return False
    _calls_today += 1
    return True


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


def personalize_reasons(liked: List[dict], taste_text: str, recs: List[dict]) -> Dict[int, str]:
    """Return {beer_id: blurb} for each recommendation, or {} on any failure."""
    client = _get_client()
    if client is None or not recs or not _under_daily_limit():
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
