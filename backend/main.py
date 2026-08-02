"""FastAPI backend for the Beer Recommender.

Serves the JSON API under /api/* and the PWA frontend from /public as the
web root, so the whole app runs from a single `uvicorn backend.main:app`.
On Vercel, public/ is served from the CDN and this mount is a fallback.
"""
import base64
import logging
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()  # pick up UNTAPPD_* / ANTHROPIC_API_KEY from .env before other imports

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, menu_scan, untappd
from .catalog import BEERS, get_beer, search_beers
from .recommender import rank_candidates, recommend

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs at INFO; Untappd auth rides in the query string,
# so those lines would contain the client secret.
logging.getLogger("httpx").setLevel(logging.WARNING)

_SECRET_PATTERN = re.compile(r"(client_secret|client_id)=[^&\s'\"]+")


class _RedactSecretsFilter(logging.Filter):
    """Scrub Untappd credentials from any log line that slips through."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "client_secret" in message or "client_id" in message:
            record.msg = _SECRET_PATTERN.sub(r"\1=[REDACTED]", message)
            record.args = None
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(_RedactSecretsFilter())

# No CORS middleware on purpose: frontend and API share one origin, and
# browsers refusing cross-origin calls keeps other sites off /api/recommend.
app = FastAPI(title="Beer Recommender", version="1.0.0")

FRONTEND_DIR = Path(__file__).parent.parent / "public"


class RecommendRequest(BaseModel):
    # Caps bound the size of the prompt sent to Claude (a paid call).
    liked_beer_ids: List[int] = Field(default_factory=list, max_length=20)
    taste_text: str = Field(default="", max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class RecommendResponse(BaseModel):
    recommendations: List[dict]
    personalized: bool


ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # decoded


class ScanMenuRequest(BaseModel):
    image_base64: str
    media_type: str = "image/jpeg"
    liked_beer_ids: List[int] = Field(default_factory=list)
    taste_text: str = ""
    limit: int = Field(default=8, ge=1, le=20)


class ScanMenuResponse(BaseModel):
    menu_beers: List[dict]
    personalized: bool


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "beers_loaded": len(BEERS),
        "untappd_configured": untappd.has_credentials(),
    }


@app.get("/api/beers")
def list_beers() -> List[dict]:
    return BEERS


@app.get("/api/beers/{beer_id}")
def beer_detail(beer_id: int) -> dict:
    beer = get_beer(beer_id)
    if beer is None:
        raise HTTPException(status_code=404, detail="Beer not found")
    return beer


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=25)) -> dict:
    untappd_results = await untappd.search_beer(q, limit)
    if untappd_results is not None:
        return {"source": "untappd", "results": untappd_results}
    return {"source": "local", "results": search_beers(q, limit)}


@app.post("/api/recommend")
def get_recommendations(req: RecommendRequest) -> RecommendResponse:
    recs = recommend(req.liked_beer_ids, req.taste_text, req.limit)
    liked = [b for b in (get_beer(i) for i in req.liked_beer_ids) if b]
    blurbs = ai.personalize_reasons(liked, req.taste_text, recs)
    for rec in recs:
        if rec["id"] in blurbs:
            rec["reason"] = blurbs[rec["id"]]
    return RecommendResponse(recommendations=recs, personalized=bool(blurbs))


@app.post("/api/scan-menu")
def scan_menu(req: ScanMenuRequest) -> ScanMenuResponse:
    if not ai.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Menu scanning isn't configured on this server (set ANTHROPIC_API_KEY in .env).",
        )
    if req.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported image type — send JPEG, PNG, or WebP.")
    if len(req.image_base64) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise HTTPException(status_code=413, detail="Image too large — please retake or downscale.")
    try:
        base64.b64decode(req.image_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image data.")

    extracted = ai.extract_menu_beers(req.image_base64, req.media_type)
    if extracted is None:
        raise HTTPException(status_code=502, detail="Couldn't read the menu — try a clearer photo.")

    candidates = menu_scan.resolve_menu_beers(extracted)
    ranked = rank_candidates(candidates, req.liked_beer_ids, req.taste_text)[: req.limit]
    personalized = bool(req.liked_beer_ids) or bool(req.taste_text.strip())
    return ScanMenuResponse(menu_beers=ranked, personalized=personalized)


# Mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
