import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Sentivity Artist Mentions API")

LASTFM_KEY = os.getenv("LASTFM_API_KEY", "c5f3e1407d1e1cd2d264ecc878590339")
LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"

# URL of your existing MAP API that already returns weekly mention data
# Set this in Render env vars
LAST_WEEK_API_URL = os.getenv(
    "LAST_WEEK_API_URL",
    "https://artistcontext.onrender.com/map"
)


# ---------------------------------------------------------------------------
# Last.fm helper (Rowan's code)
# ---------------------------------------------------------------------------
def lastfm_get(method: str, **params) -> dict:
    r = requests.get(
        LASTFM_BASE,
        params={
            "method": method,
            "api_key": LASTFM_KEY,
            "format": "json",
            **params,
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def get_artist_mentions(artist_name: str) -> dict:
    try:
        search = lastfm_get("artist.search", artist=artist_name, limit=1)
        total_results = int(search["results"]["opensearch:totalResults"])
        return {"artist": artist_name, "mention_count": total_results}
    except Exception as e:
        print(f"FAILED {artist_name}: {e}")
        return {"artist": artist_name, "mention_count": None}


# ---------------------------------------------------------------------------
# Pull last week's count from your existing MAP API
# ---------------------------------------------------------------------------
def get_last_week_mention_count(artist_name: str) -> int:
    """
    Hits the existing MAP API to fetch the prior week's mention total.
    Falls back to 0 if the call fails so the endpoint still returns.
    """
    try:
        r = requests.get(
            f"{LAST_WEEK_API_URL}/{artist_name}/artist",
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        # Adjust key path to match whatever MAP actually returns
        return int(data.get("weekly_average") or data.get("mention_count") or 0)
    except Exception as e:
        print(f"last-week fetch failed for {artist_name}: {e}")
        return 0


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ArtistRequest(BaseModel):
    artist_name: str


class MentionResponse(BaseModel):
    artist: str
    current_mentions: int
    last_week_mentions: int
    total_mentions: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/artist-mentions", response_model=MentionResponse)
def artist_mentions_post(body: ArtistRequest):
    return _build_response(body.artist_name)


# GET variant so Campbell's team can hit it the same way as MAP
@app.get("/artist-mentions/{artist_name}", response_model=MentionResponse)
def artist_mentions_get(artist_name: str):
    return _build_response(artist_name)


def _build_response(artist_name: str) -> MentionResponse:
    result = get_artist_mentions(artist_name)
    if result["mention_count"] is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch mentions for '{artist_name}' from Last.fm.",
        )

    current = result["mention_count"]
    last_week = get_last_week_mention_count(artist_name)

    return MentionResponse(
        artist=result["artist"],
        current_mentions=current,
        last_week_mentions=last_week,
        total_mentions=current + last_week,
    )