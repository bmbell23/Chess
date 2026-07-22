from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MoveStats(Base):
    """Per-game move-quality counts from our own Stockfish analysis.

    Classes approximate chess.com Game Review labels via centipawn-loss
    thresholds — they will not exactly match chess.com's numbers.
    """

    __tablename__ = "move_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), unique=True)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    depth: Mapped[int] = mapped_column(Integer)

    moves: Mapped[int] = mapped_column(Integer, default=0)  # player's moves analyzed
    brilliant: Mapped[int] = mapped_column(Integer, default=0)
    great: Mapped[int] = mapped_column(Integer, default=0)
    best: Mapped[int] = mapped_column(Integer, default=0)
    excellent: Mapped[int] = mapped_column(Integer, default=0)
    good: Mapped[int] = mapped_column(Integer, default=0)
    inaccuracy: Mapped[int] = mapped_column(Integer, default=0)
    mistake: Mapped[int] = mapped_column(Integer, default=0)
    blunder: Mapped[int] = mapped_column(Integer, default=0)

    # ---- Insights v2 (#15); NULL on rows from the pre-v2 analyzer → re-analyzed ----
    acpl: Mapped[float | None] = mapped_column(Float)  # avg centipawn loss, player moves
    first_bad_move: Mapped[int | None] = mapped_column(Integer)  # fullmove of 1st mistake/blunder
    max_eval: Mapped[int | None] = mapped_column(Integer)  # best advantage reached (player POV, cp)
    min_eval: Mapped[int | None] = mapped_column(Integer)  # worst deficit reached (player POV, cp)
    # per-phase centipawn-loss sums + move counts + blunders (opening/middle/end)
    open_cpl: Mapped[int | None] = mapped_column(Integer)
    open_moves: Mapped[int | None] = mapped_column(Integer)
    open_blunders: Mapped[int | None] = mapped_column(Integer)
    mid_cpl: Mapped[int | None] = mapped_column(Integer)
    mid_moves: Mapped[int | None] = mapped_column(Integer)
    mid_blunders: Mapped[int | None] = mapped_column(Integer)
    end_cpl: Mapped[int | None] = mapped_column(Integer)
    end_moves: Mapped[int | None] = mapped_column(Integer)
    end_blunders: Mapped[int | None] = mapped_column(Integer)
