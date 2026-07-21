"""Sync engine: backfill immutable monthly archives, refresh the current month,
and snapshot current stats. All chess.com access goes through the serial client."""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import Game, Player, RatingSnapshot, SyncLog
from .chesscom_client import ChessComClient

logger = logging.getLogger(__name__)

# chess.com per-side result codes → win/loss/draw
_DRAW_CODES = {
    "agreed", "repetition", "stalemate", "insufficient",
    "50move", "timevsinsufficient",
}
_ECO_RE = re.compile(r'\[ECO "([^"]+)"\]')
_ECO_URL_RE = re.compile(r'\[ECOUrl "([^"]+)"\]')

_MODES = ("chess_rapid", "chess_blitz", "chess_bullet", "chess_daily")

# one sync at a time process-wide (chess.com wants serial; also guards the UI flow)
_SYNC_RUN_LOCK = __import__("threading").Lock()
# per-username progress for the UI: {state, months_done, months_total, games, error}
SYNC_PROGRESS: dict[str, dict] = {}


def _progress(username: str, **kw) -> None:
    SYNC_PROGRESS.setdefault(username, {}).update(kw)


def normalize_username(username: str | None) -> str:
    username = (username or get_settings().chesscom_username).strip().lower()
    if not username:
        raise ValueError("no username given and CHESSCOM_USERNAME not configured")
    return username


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_game(raw: dict, player: Player) -> Game | None:
    """Map one archive game onto our Game row; None for non-standard variants."""
    if raw.get("rules", "chess") != "chess":
        return None

    white, black = raw.get("white", {}), raw.get("black", {})
    uname = player.username.lower()
    if white.get("username", "").lower() == uname:
        mine, theirs, color = white, black, "white"
    elif black.get("username", "").lower() == uname:
        mine, theirs, color = black, white, "black"
    else:
        return None

    code = mine.get("result", "")
    if code == "win":
        result = "win"
    elif code in _DRAW_CODES:
        result = "draw"
    else:
        result = "loss"

    pgn = raw.get("pgn")
    eco = opening = None
    if pgn:
        if m := _ECO_RE.search(pgn):
            eco = m.group(1)[:8]
        if m := _ECO_URL_RE.search(pgn):
            opening = m.group(1).rsplit("/", 1)[-1].replace("-", " ")[:128]

    accuracies = raw.get("accuracies") or {}
    return Game(
        uuid=raw["uuid"],
        url=raw.get("url"),
        player_id=player.id,
        end_time=datetime.fromtimestamp(raw["end_time"], tz=timezone.utc),
        time_class=raw.get("time_class", "unknown"),
        time_control=raw.get("time_control"),
        rated=bool(raw.get("rated", True)),
        color=color,
        opponent=theirs.get("username"),
        opponent_rating=theirs.get("rating"),
        result=result,
        termination=code[:32] if result != "win" else theirs.get("result", "")[:32],
        my_rating=mine.get("rating"),
        eco=eco,
        opening_name=opening,
        pgn=pgn,
        accuracy_mine=accuracies.get(color),
        accuracy_opponent=accuracies.get("black" if color == "white" else "white"),
    )


class SyncService:
    def __init__(self, client: ChessComClient | None = None):
        self.client = client or ChessComClient()

    def ensure_player(self, db: Session, username: str) -> Player:
        player = db.execute(
            select(Player).where(Player.username == username)
        ).scalar_one_or_none()
        if player is None:
            profile = self.client.player(username)
            player = Player(
                username=profile["username"],
                display_name=profile.get("name"),
            )
            db.add(player)
            db.commit()
        return player

    def snapshot_stats(self, db: Session, player: Player) -> int:
        stats = self.client.stats(player.username)
        count = 0
        for mode in _MODES:
            block = stats.get(mode)
            if not isinstance(block, dict):
                continue
            record = block.get("record", {})
            db.add(
                RatingSnapshot(
                    player_id=player.id,
                    mode=mode.removeprefix("chess_"),
                    rating=block.get("last", {}).get("rating"),
                    best_rating=block.get("best", {}).get("rating"),
                    wins=record.get("win"),
                    losses=record.get("loss"),
                    draws=record.get("draw"),
                )
            )
            count += 1
        db.commit()
        return count

    def sync_games(self, db: Session, player: Player) -> dict:
        """Walk archives oldest→newest. Immutable past months fetch exactly once;
        the current month re-fetches ETag-aware and dedupes by uuid."""
        now = _utc_now()
        added = skipped_variants = months_skipped = not_modified = 0

        archive_urls = self.client.archives(player.username)
        _progress(player.username, months_total=len(archive_urls), months_done=0)
        for url in archive_urls:
            year, month = int(url.rsplit("/", 2)[-2]), int(url.rsplit("/", 1)[-1])
            log = db.execute(
                select(SyncLog).where(
                    SyncLog.player_id == player.id,
                    SyncLog.year == year,
                    SyncLog.month == month,
                )
            ).scalar_one_or_none()

            if log and log.complete:
                months_skipped += 1
                prog = SYNC_PROGRESS.get(player.username, {})
                _progress(player.username, months_done=prog.get("months_done", 0) + 1)
                continue

            resp = self.client.monthly_games(
                player.username, year, month, etag=log.etag if log else None
            )
            if resp.not_modified:
                not_modified += 1
                continue

            existing = {
                u
                for (u,) in db.execute(
                    select(Game.uuid).where(Game.player_id == player.id)
                )
            }
            month_count = 0
            for raw in resp.data.get("games", []):
                if raw["uuid"] in existing:
                    continue
                game = _parse_game(raw, player)
                if game is None:
                    skipped_variants += 1
                    continue
                db.add(game)
                month_count += 1
            added += month_count

            is_past = (year, month) < (now.year, now.month)
            if log is None:
                log = SyncLog(player_id=player.id, year=year, month=month)
                db.add(log)
            log.fetched_at = _utc_now()
            log.game_count = (log.game_count or 0) + month_count
            log.etag = resp.etag
            log.complete = 1 if is_past else 0
            db.commit()
            prog = SYNC_PROGRESS.get(player.username, {})
            _progress(
                player.username,
                months_done=prog.get("months_done", 0) + 1,
                games=prog.get("games", 0) + month_count,
            )
            logger.info(
                "synced %s %04d/%02d: +%d games%s",
                player.username, year, month, month_count,
                " (complete)" if is_past else "",
            )

        return {
            "games_added": added,
            "months_marked_complete_skipped": months_skipped,
            "current_month_304": not_modified,
            "variants_skipped": skipped_variants,
        }

    def run_full_sync(self, username: str | None = None) -> dict:
        username = normalize_username(username)
        with _SYNC_RUN_LOCK:
            _progress(username, state="running", error=None, games=0)
            try:
                with SessionLocal() as db:
                    player = self.ensure_player(db, username)
                    snapshots = self.snapshot_stats(db, player)
                    result = self.sync_games(db, player)
                    total = db.execute(
                        select(func.count(Game.id)).where(Game.player_id == player.id)
                    ).scalar_one()
            except Exception as exc:
                _progress(username, state="error", error=str(exc))
                raise
            _progress(username, state="done")
        return {
            "player": username,
            "snapshot_modes": snapshots,
            **result,
            "total_games_in_db": total,
            "finished_at": _utc_now().isoformat(),
        }


def sync_status(username: str | None = None) -> dict:
    username = normalize_username(username)
    with SessionLocal() as db:
        player = db.execute(
            select(Player).where(Player.username == username)
        ).scalar_one_or_none()
        if player is None:
            return {"player": username, "synced": False}
        last_fetch = db.execute(
            select(func.max(SyncLog.fetched_at)).where(SyncLog.player_id == player.id)
        ).scalar_one()
        months_complete = db.execute(
            select(func.count(SyncLog.id)).where(
                SyncLog.player_id == player.id, SyncLog.complete == 1
            )
        ).scalar_one()
        total_games = db.execute(
            select(func.count(Game.id)).where(Game.player_id == player.id)
        ).scalar_one()
        latest = {}
        for mode in ("rapid", "blitz", "bullet", "daily"):
            snap = db.execute(
                select(RatingSnapshot)
                .where(RatingSnapshot.player_id == player.id, RatingSnapshot.mode == mode)
                .order_by(RatingSnapshot.taken_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if snap:
                latest[mode] = {
                    "rating": snap.rating,
                    "best": snap.best_rating,
                    "record": f"{snap.wins}-{snap.losses}-{snap.draws}",
                }
        return {
            "player": player.username,
            "synced": True,
            "last_sync": last_fetch.isoformat() if last_fetch else None,
            "months_complete": months_complete,
            "total_games": total_games,
            "latest_ratings": latest,
        }
