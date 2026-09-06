"""
Minimal API-key auth for write endpoints (POST /ingest).

This is deliberately small — a single shared key via a header, not a user/
session/OAuth system — because the point is to not leave the write path
wide open to anyone who can reach the port, not to build a full auth
service for a project this size. Read endpoints (GET /runs, /profile,
/preview, /issues, /datasets) stay open, matching a typical internal
reporting-dashboard posture: anyone can view, only a known caller can write.
"""
from fastapi import Header, HTTPException

from config import API_KEY


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: raise 401 unless X-API-Key matches config.API_KEY.
    If API_KEY is unset (e.g. a from-scratch local clone with no .env yet),
    auth is a no-op — fail open for local dev, but config.py logs a clear
    warning so this is never silently the case in a deployed environment.
    """
    if not API_KEY:
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
