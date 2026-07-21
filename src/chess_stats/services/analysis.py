"""Move-quality analysis with a local Stockfish.

Classifies each of the player's moves by centipawn loss against the engine's
choice — an approximation of chess.com Game Review labels, not a clone of them.
"""
import io
import logging
import shutil
import threading

import chess
import chess.engine
import chess.pgn
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Game, MoveStats, Player
from .sync import normalize_username

logger = logging.getLogger(__name__)

CLASSES = ("brilliant", "great", "best", "excellent", "good", "inaccuracy", "mistake", "blunder")

DEPTH = 10          # "balanced" per #12
GREAT_GAP_CP = 150  # best move is "great" when the alternative is this much worse
BRILLIANT_GAP_CP = 200
MATE_SCORE = 100000

_PIECE_VALUE = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

# one engine run at a time (single-CPU container); progress mirrors the sync pattern
_ANALYSIS_RUN_LOCK = threading.Lock()
ANALYSIS_PROGRESS: dict[str, dict] = {}


def _progress(username: str, **kw) -> None:
    ANALYSIS_PROGRESS.setdefault(username, {}).update(kw)


def engine_available() -> bool:
    return shutil.which("stockfish") is not None


def _is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Naive: the moved piece (value >= 3) ends up capturable by a cheaper attacker."""
    piece = board.piece_at(move.from_square)
    if piece is None or _PIECE_VALUE[piece.piece_type] < 3:
        return False
    board.push(move)
    try:
        attackers = board.attackers(board.turn, move.to_square)
        return any(
            _PIECE_VALUE[board.piece_at(sq).piece_type] < _PIECE_VALUE[piece.piece_type]
            for sq in attackers
        )
    finally:
        board.pop()


class Analyzer:
    def __init__(self, depth: int = DEPTH):
        self.depth = depth
        self.engine = chess.engine.SimpleEngine.popen_uci("stockfish")
        self.engine.configure({"Threads": 1})

    def close(self) -> None:
        self.engine.quit()

    def _cp(self, info, color: chess.Color) -> int:
        return info["score"].pov(color).score(mate_score=MATE_SCORE)

    def analyze_game(self, pgn: str, my_color_white: bool) -> dict | None:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return None
        my_color = chess.WHITE if my_color_white else chess.BLACK
        counts = dict.fromkeys(CLASSES, 0)
        moves = 0
        board = game.board()

        for node in game.mainline():
            move = node.move
            if board.turn != my_color:
                board.push(move)
                continue
            infos = self.engine.analyse(
                board, chess.engine.Limit(depth=self.depth), multipv=2
            )
            best_move = infos[0]["pv"][0]
            best_cp = self._cp(infos[0], my_color)
            moves += 1

            if move == best_move:
                gap = (
                    best_cp - self._cp(infos[1], my_color)
                    if len(infos) > 1
                    else GREAT_GAP_CP
                )
                if gap >= BRILLIANT_GAP_CP and _is_sacrifice(board, move):
                    counts["brilliant"] += 1
                elif gap >= GREAT_GAP_CP:
                    counts["great"] += 1
                else:
                    counts["best"] += 1
            else:
                board.push(move)
                after = self.engine.analyse(board, chess.engine.Limit(depth=self.depth))
                board.pop()
                loss = max(0, best_cp - self._cp(after, my_color))
                if loss >= 300:
                    counts["blunder"] += 1
                elif loss >= 100:
                    counts["mistake"] += 1
                elif loss >= 50:
                    counts["inaccuracy"] += 1
                elif loss >= 20:
                    counts["good"] += 1
                else:
                    counts["excellent"] += 1
            board.push(move)

        return {"moves": moves, **counts}


def run_analysis(username: str | None = None) -> dict:
    """Analyze every stored-but-unanalyzed game for a player."""
    username = normalize_username(username)
    with _ANALYSIS_RUN_LOCK:
        _progress(username, state="running", error=None, done=0)
        try:
            with SessionLocal() as db:
                player = db.execute(
                    select(Player).where(Player.username == username)
                ).scalar_one_or_none()
                if player is None:
                    raise ValueError(f"player '{username}' not synced")
                pending = db.execute(
                    select(Game)
                    .outerjoin(MoveStats, MoveStats.game_id == Game.id)
                    .where(
                        Game.player_id == player.id,
                        Game.pgn.is_not(None),
                        MoveStats.id.is_(None),
                    )
                    .order_by(Game.end_time)
                ).scalars().all()
                _progress(username, total=len(pending))
                if not pending:
                    _progress(username, state="done")
                    return {"player": username, "analyzed": 0, "skipped": 0}

                analyzer = Analyzer()
                analyzed = skipped = 0
                try:
                    for i, game in enumerate(pending, 1):
                        result = analyzer.analyze_game(
                            game.pgn, game.color == "white"
                        )
                        if result is None:
                            skipped += 1
                        else:
                            db.add(
                                MoveStats(
                                    game_id=game.id, depth=analyzer.depth, **result
                                )
                            )
                            analyzed += 1
                        if i % 10 == 0 or i == len(pending):
                            db.commit()
                        _progress(username, done=i)
                finally:
                    analyzer.close()
                db.commit()
        except Exception as exc:
            _progress(username, state="error", error=str(exc))
            raise
        _progress(username, state="done")
        return {"player": username, "analyzed": analyzed, "skipped": skipped}
