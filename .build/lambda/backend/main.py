"""FastAPI backend for the Beer Recommender.

Serves the JSON API under /api/* and the PWA frontend from /frontend as the
web root, so the whole app runs from a single `uvicorn backend.main:app`.
"""
import logging
import os
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()  # pick up UNTAPPD_* / ANTHROPIC_API_KEY from .env before other imports

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, untappd
from .catalog import BEERS, get_beer, search_beers
from .recommender import recommend

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

# In production (Lambda) the interactive docs and OpenAPI schema are disabled
# to shrink the public surface; locally they stay available at /docs.
IS_PRODUCTION = os.environ.get("APP_ENV") == "production"

app = FastAPI(
    title="Beer Recommender",
    version="1.0.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# The PWA is served from this same app, so every request is same-origin and no
# CORS middleware is needed — browsers' same-origin policy stays fully intact.

_SECURITY_HEADERS = {
    # No inline scripts/styles or external assets exist in frontend/, so the
    # CSP can be strict; loosen a directive here if that ever changes.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; script-src 'self'; "
        "style-src 'self'; connect-src 'self'; manifest-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
        "object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(_SECURITY_HEADERS)
    if IS_PRODUCTION:
        # Only meaningful over HTTPS (Lambda Function URLs are HTTPS-only);
        # kept out of local dev so localhost is never HSTS-pinned.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


class RecommendRequest(BaseModel):
    liked_beer_ids: List[int] = Field(default_factory=list, max_length=60)
    taste_text: str = Field(default="", max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class RecommendResponse(BaseModel):
    recommendations: List[dict]
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
async def search(q: str = Query(..., min_length=1, max_length=100), limit: int = Query(10, ge=1, le=25)) -> dict:
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


# Mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
