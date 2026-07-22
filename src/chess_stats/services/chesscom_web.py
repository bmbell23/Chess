"""Unofficial chess.com callback endpoints (puzzles + lessons).

These are NOT part of the documented Published-Data API — they power the website
and can change or vanish without notice. Everything here is best-effort: any
failure returns a graceful "unavailable" result so the rest of the app is
unaffected. No authentication is used or needed for these fields.
"""
import logging

import httpx

logger = logging.getLogger(__name__)

BASE = "https://www.chess.com/callback"
# a browser-ish UA — the callback host rejects obvious bots
UA = "Mozilla/5.0 (compatible; ChessStats/1.0; self-hosted)"


def _get(path: str) -> dict | None:
    try:
        resp = httpx.get(f"{BASE}/{path}", headers={"User-Agent": UA}, timeout=15.0)
        if resp.status_code == 200:
            return resp.json()
        logger.info("chess.com callback %s -> %s", path, resp.status_code)
    except Exception as exc:  # unofficial endpoint — never let it break a request
        logger.info("chess.com callback %s failed: %s", path, exc)
    return None


def training_stats(username: str) -> dict:
    """Puzzle (tactics), Puzzle Rush, and lesson progress. Unofficial/best-effort."""
    result: dict = {"available": False, "puzzles": None, "lessons": None, "puzzle_rush": None}

    stats = _get(f"member/stats/{username}")
    if stats:
        for block in stats.get("stats", []):
            if block.get("key") == "tactics":
                t = block.get("stats", {})
                attempts = t.get("attempt_count")
                passed = t.get("passed_count")
                seconds = t.get("total_seconds")
                result["puzzles"] = {
                    "rating": t.get("rating"),
                    "highest_rating": t.get("highest_rating"),
                    "attempts": attempts,
                    "passed": passed,
                    "failed": t.get("failed_count"),
                    "pass_rate": round(100 * passed / attempts, 1)
                    if attempts and passed is not None
                    else None,
                    "seconds_spent": seconds,
                    "avg_seconds": round(seconds / attempts, 1)
                    if attempts and seconds
                    else None,
                }
                result["available"] = True
        lesson = stats.get("lessonLevel")
        if lesson:
            result["lessons"] = {
                "level": lesson.get("name"),
                "progress": lesson.get("progress"),
            }
            result["available"] = True

    popup = _get(f"user/popup/{username}")
    if popup and popup.get("topPuzzleRushScore") is not None:
        result["puzzle_rush"] = {
            "best": popup.get("topPuzzleRushScore"),
            "mode": popup.get("topPuzzleRushScoreType"),
        }
        result["available"] = True

    return result
