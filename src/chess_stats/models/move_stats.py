from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer
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
