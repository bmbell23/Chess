"""chess.com Published-Data API client.

The API is public and read-only — no authentication of any kind. House rules
from the API docs/etiquette: identify yourself via User-Agent, make requests
strictly serially, and back off on 429s. Past monthly archives are immutable;
the current month supports ETag revalidation (304s are cheap).
"""
import logging
import random
import threading
import time
from dataclasses import dataclass

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.chess.com/pub"
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 120.0


@dataclass
class ApiResponse:
    data: dict | None  # None when the server returned 304 Not Modified
    etag: str | None
    not_modified: bool = False


class ChessComError(Exception):
    pass


class PlayerNotFound(ChessComError):
    pass


class ChessComClient:
    """Serial-only client: a lock guarantees one in-flight request, ever."""

    def __init__(self, contact_email: str | None = None):
        settings = get_settings()
        contact = contact_email or settings.contact_email or "unknown"
        self._lock = threading.Lock()
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "User-Agent": f"Chess-Stats self-hosted tracker (contact: {contact})",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, etag: str | None = None) -> ApiResponse:
        headers = {"If-None-Match": etag} if etag else {}
        with self._lock:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    resp = self._client.get(path, headers=headers)
                except httpx.TransportError as exc:
                    if attempt == MAX_RETRIES:
                        raise ChessComError(f"transport failure on {path}: {exc}") from exc
                    self._sleep(attempt, f"transport error on {path}: {exc}")
                    continue

                if resp.status_code == 200:
                    return ApiResponse(data=resp.json(), etag=resp.headers.get("etag"))
                if resp.status_code == 304:
                    return ApiResponse(data=None, etag=etag, not_modified=True)
                if resp.status_code == 404:
                    raise PlayerNotFound(f"chess.com returned 404 for {path}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt == MAX_RETRIES:
                        raise ChessComError(
                            f"{resp.status_code} on {path} after {MAX_RETRIES} attempts"
                        )
                    retry_after = resp.headers.get("retry-after")
                    if resp.status_code == 429 and retry_after and retry_after.isdigit():
                        wait = float(retry_after)
                        logger.warning(
                            "rate limited on %s — honoring Retry-After %.0fs", path, wait
                        )
                        time.sleep(wait)
                    else:
                        self._sleep(attempt, f"{resp.status_code} on {path}")
                    continue
                raise ChessComError(f"unexpected {resp.status_code} on {path}")
        raise ChessComError(f"unreachable: {path}")

    @staticmethod
    def _sleep(attempt: int, reason: str) -> None:
        wait = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
        wait += random.uniform(0, wait / 4)
        logger.warning("%s — backing off %.1fs (attempt %d)", reason, wait, attempt)
        time.sleep(wait)

    # ---- endpoints ----

    def player(self, username: str) -> dict:
        return self._get(f"/player/{username}").data

    def stats(self, username: str) -> dict:
        return self._get(f"/player/{username}/stats").data

    def archives(self, username: str) -> list[str]:
        """Monthly archive URLs, oldest first."""
        return self._get(f"/player/{username}/games/archives").data["archives"]

    def monthly_games(
        self, username: str, year: int, month: int, etag: str | None = None
    ) -> ApiResponse:
        """One month of games. Pass the stored etag for cheap current-month re-polls."""
        return self._get(f"/player/{username}/games/{year}/{month:02d}", etag=etag)
