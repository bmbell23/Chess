"""Read-only chart data endpoints. All queries are scoped to the configured player."""
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..config import get_settings
from ..database import SessionLocal
from ..models import Game, Player
from ..services.sync import normalize_username

router = APIRouter(prefix="/api/v1/charts", tags=["charts"])

MODES = ("rapid", "blitz", "bullet", "daily")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _player_id(db, username: str | None = None) -> int:
    player = db.execute(
        select(Player).where(Player.username == normalize_username(username))
    ).scalar_one_or_none()
    if player is None:
        raise HTTPException(404, "player not synced yet")
    return player.id


@router.get("/rating-history")
def rating_history(player: str | None = None) -> dict:
    """Per-mode series of (game end time, post-game rating), chronological."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.time_class, Game.end_time, Game.my_rating)
            .where(
                Game.player_id == pid,
                Game.my_rating.is_not(None),
                # unrated games don't move ratings — their reported rating is
                # junk for a progression chart (found via #14's 936→420→956 dip)
                Game.rated.is_(True),
            )
            .order_by(Game.end_time)
        ).all()
    series: dict[str, list] = {m: [] for m in MODES}
    for time_class, end_time, rating in rows:
        if time_class in series:
            series[time_class].append({"t": end_time.isoformat(), "r": rating})
    return series


@router.get("/wld")
def win_loss_draw(player: str | None = None) -> dict:
    """W/L/D by mode, by color, and by month."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.time_class, Game.color, Game.end_time, Game.result).where(
                Game.player_id == pid
            )
        ).all()
    by_mode = {m: {"win": 0, "loss": 0, "draw": 0} for m in MODES}
    by_color = {c: {"win": 0, "loss": 0, "draw": 0} for c in ("white", "black")}
    by_month: dict[str, dict] = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0})
    for time_class, color, end_time, result in rows:
        if time_class in by_mode:
            by_mode[time_class][result] += 1
        by_color[color][result] += 1
        by_month[end_time.strftime("%Y-%m")][result] += 1
    return {
        "by_mode": by_mode,
        "by_color": by_color,
        "by_month": dict(sorted(by_month.items())),
    }


@router.get("/openings")
def openings(limit: int = 10, min_games: int = 3, player: str | None = None) -> list[dict]:
    """Most-played openings with W/L/D and win rate."""
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.eco, Game.opening_name, Game.result).where(
                Game.player_id == pid, Game.eco.is_not(None)
            )
        ).all()
    agg: dict[str, dict] = {}
    for eco, name, result in rows:
        entry = agg.setdefault(
            eco, {"eco": eco, "name": name, "win": 0, "loss": 0, "draw": 0}
        )
        entry[result] += 1
    out = []
    for entry in agg.values():
        games = entry["win"] + entry["loss"] + entry["draw"]
        if games < min_games:
            continue
        entry["games"] = games
        entry["winrate"] = round(100 * entry["win"] / games, 1)
        out.append(entry)
    out.sort(key=lambda e: e["games"], reverse=True)
    return out[:limit]


@router.get("/time-buckets")
def time_buckets(player: str | None = None) -> dict:
    """Win rate by local hour-of-day and day-of-week (games stored UTC)."""
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    utc = ZoneInfo("UTC")
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.end_time, Game.result).where(Game.player_id == pid)
        ).all()
    hours = [{"games": 0, "win": 0} for _ in range(24)]
    days = [{"games": 0, "win": 0} for _ in range(7)]
    for end_time, result in rows:
        local = end_time.replace(tzinfo=utc).astimezone(tz)
        for bucket in (hours[local.hour], days[local.weekday()]):
            bucket["games"] += 1
            bucket["win"] += result == "win"
    def rate(b):
        return round(100 * b["win"] / b["games"], 1) if b["games"] else None
    return {
        "tz": settings.tz,
        "hours": [
            {"hour": h, "games": b["games"], "winrate": rate(b)}
            for h, b in enumerate(hours)
        ],
        "weekdays": [
            {"day": WEEKDAYS[i], "games": b["games"], "winrate": rate(b)}
            for i, b in enumerate(days)
        ],
    }


@router.get("/move-quality")
def move_quality(player: str | None = None) -> dict:
    """Cumulative move-quality counts over time (our Stockfish approximation)."""
    from ..models import MoveStats
    from ..services.analysis import CLASSES

    with SessionLocal() as db:
        pid = _player_id(db, player)
        total_games = db.execute(
            select(Game.id).where(Game.player_id == pid)
        ).all()
        rows = db.execute(
            select(Game.end_time, MoveStats)
            .join(MoveStats, MoveStats.game_id == Game.id)
            .where(Game.player_id == pid)
            .order_by(Game.end_time)
        ).all()
    # rolling rate per 100 moves over a trailing window — the "am I blundering
    # less often" view (#19); cumulative counts retired per Brandon
    WINDOW = 20
    running = dict.fromkeys(CLASSES, 0)
    series: dict[str, list] = {c: [] for c in CLASSES}
    stats_list = [(end_time, stats) for end_time, stats in rows]
    for i, (end_time, stats) in enumerate(stats_list):
        for c in CLASSES:
            running[c] += getattr(stats, c)
        window = stats_list[max(0, i - WINDOW + 1): i + 1]
        window_moves = sum(s.moves for _, s in window) or 1
        t = end_time.isoformat()
        for c in CLASSES:
            rate = 100 * sum(getattr(s, c) for _, s in window) / window_moves
            series[c].append({"t": t, "rate": round(rate, 2)})
    return {
        "classes": series,
        "window_games": WINDOW,
        "analyzed_games": len(rows),
        "total_games": len(total_games),
        "totals": running,
    }


_PGN_HDR = {
    k: __import__("re").compile(r'\[' + k + r' "([^"]+)"\]')
    for k in ("UTCDate", "UTCTime", "EndDate", "EndTime")
}
_LIVE = ("rapid", "blitz", "bullet")


@router.get("/daily-volume")
def daily_volume(player: str | None = None) -> dict:
    """Games and minutes played per local day, plus days-played streaks (#21).
    Minutes come from live-game PGN start/end headers; daily games count toward
    games/streaks but not minutes (they run asynchronously)."""
    from datetime import date, datetime, timedelta

    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    utc = ZoneInfo("UTC")
    with SessionLocal() as db:
        pid = _player_id(db, player)
        rows = db.execute(
            select(Game.end_time, Game.time_class, Game.pgn).where(Game.player_id == pid)
        ).all()

    per_day: dict[str, dict] = {}
    for end_time, time_class, pgn in rows:
        day = end_time.replace(tzinfo=utc).astimezone(tz).date().isoformat()
        entry = per_day.setdefault(day, {"games": 0, "seconds": 0})
        entry["games"] += 1
        if pgn and time_class in _LIVE:
            hdr = {k: rx.search(pgn) for k, rx in _PGN_HDR.items()}
            if all(hdr.values()):
                try:
                    start = datetime.strptime(
                        f"{hdr['UTCDate'].group(1)} {hdr['UTCTime'].group(1)}", "%Y.%m.%d %H:%M:%S"
                    )
                    end = datetime.strptime(
                        f"{hdr['EndDate'].group(1)} {hdr['EndTime'].group(1)}", "%Y.%m.%d %H:%M:%S"
                    )
                    dur = (end - start).total_seconds()
                    if 0 < dur <= 6 * 3600:
                        entry["seconds"] += dur
                except ValueError:
                    pass

    played = sorted(date.fromisoformat(d) for d in per_day)
    longest = run = 0
    prev = None
    for d in played:
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    today = datetime.now(tz).date()
    current = 0
    if played:
        played_set = set(played)
        cursor = today if today in played_set else today - timedelta(days=1)
        while cursor in played_set:
            current += 1
            cursor -= timedelta(days=1)

    return {
        "tz": settings.tz,
        "streak_current": current,
        "streak_longest": longest,
        "days_played": len(played),
        "days": [
            {"date": d, "games": v["games"], "minutes": round(v["seconds"] / 60)}
            for d, v in sorted(per_day.items())
        ],
    }
