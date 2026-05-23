import os
import requests
import tweepy
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Sentivity Artist Mentions API")

LASTFM_KEY = os.getenv("LASTFM_API_KEY", "c5f3e1407d1e1cd2d264ecc878590339")
LASTFM_BASE = "http://ws.audioscrobbler.com/2.0/"

LAST_WEEK_API_URL = os.getenv(
    "LAST_WEEK_API_URL",
    "https://artistcontext.onrender.com/map",
)

X_CONSUMER_KEY = os.getenv("X_CONSUMER_KEY")
X_CONSUMER_SECRET = os.getenv("X_CONSUMER_SECRET")
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

x_client = tweepy.Client(
    consumer_key=X_CONSUMER_KEY,
    consumer_secret=X_CONSUMER_SECRET,
    bearer_token=X_BEARER_TOKEN,
)


# ---------------------------------------------------------------------------
# Last.fm
# ---------------------------------------------------------------------------
def lastfm_get(method: str, **params) -> dict:
    r = requests.get(
        LASTFM_BASE,
        params={"method": method, "api_key": LASTFM_KEY, "format": "json", **params},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def get_artist_stats(artist_name: str) -> dict:
    try:
        info = lastfm_get("artist.getinfo", artist=artist_name)
        stats = info["artist"]["stats"]
        search = lastfm_get("artist.search", artist=artist_name, limit=1)
        return {
            "artist": artist_name,
            "listeners": int(stats["listeners"]),
            "playcount": int(stats["playcount"]),
            "mention_count": int(search["results"]["opensearch:totalResults"]),
        }
    except Exception as e:
        print(f"get_artist_stats FAILED [{artist_name}]: {e}")
        return {"artist": artist_name, "listeners": None, "playcount": None, "mention_count": None}


# ---------------------------------------------------------------------------
# MAP API (last week)
# ---------------------------------------------------------------------------
def get_last_week_mention_count(artist_name: str) -> int:
    url = f"{LAST_WEEK_API_URL}/{artist_name}/artist"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        value = data.get("weekly_average") or data.get("mention_count") or 0
        print(f"last-week ok [{artist_name}]: {value} (keys: {list(data.keys())})")
        return int(value)
    except Exception as e:
        print(f"last-week FAILED [{artist_name}] at {url}: {e}")
        return 0


# ---------------------------------------------------------------------------
# X engagement estimate
# ---------------------------------------------------------------------------
def _clean_text(text: str) -> str:
    return text.replace("\n", " ").strip()


def get_x_estimate(artist_name: str, listeners: int, playcount: int) -> int:
    """
    Returns ONLY the estimated mention count from X (no Last.fm addition).
    Returns 0 on any failure so the endpoint still serves a useful response.
    """
    if not listeners or not playcount:
        print(f"x_estimate skipped [{artist_name}]: missing listeners/playcount")
        return 0

    query = f'"{artist_name}" -is:retweet lang:en'
    max_results = 100

    try:
        response = x_client.search_recent_tweets(
            query=query,
            max_results=max_results,
            tweet_fields=["created_at", "public_metrics", "text"],
            sort_order="relevancy",
        )
    except Exception as e:
        print(f"x_estimate search FAILED [{artist_name}]: {e}")
        return 0

    if not response.data:
        return 0

    df = pd.DataFrame([{
        "likes": t.public_metrics.get("like_count", 0),
        "replies": t.public_metrics.get("reply_count", 0),
    } for t in response.data])

    sample_size = len(df)
    reply_sum = int(df["replies"].sum())
    total_engaged = reply_sum + sample_size

    conversion_rate = total_engaged / listeners if listeners else 0
    estimated = (conversion_rate * playcount) / max_results

    print(f"x_estimate [{artist_name}]: sample={sample_size} engaged={total_engaged} est={estimated:.1f}")
    return round(estimated)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ArtistRequest(BaseModel):
    artist_name: str


class MentionResponse(BaseModel):
    artist: str
    mention_count: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/artist-mentions", response_model=MentionResponse)
def artist_mentions_post(body: ArtistRequest):
    return _build_response(body.artist_name)


@app.get("/artist-mentions/{artist_name}", response_model=MentionResponse)
def artist_mentions_get(artist_name: str):
    return _build_response(artist_name)


def _build_response(artist_name: str) -> MentionResponse:
    stats = get_artist_stats(artist_name)
    if stats["mention_count"] is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch Last.fm stats for '{artist_name}'.",
        )

    current = stats["mention_count"]
    last_week = get_last_week_mention_count(artist_name)
    x_est = get_x_estimate(
        artist_name,
        listeners=stats["listeners"] or 0,
        playcount=stats["playcount"] or 0,
    )

    total = current + last_week + x_est
    print(f"[{artist_name}] current={current} last_week={last_week} x={x_est} total={total}")

    return MentionResponse(
        artist=stats["artist"],
        mention_count=total,
    )
