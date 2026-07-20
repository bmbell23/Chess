from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class RatingSnapshot(Base):
    __tablename__ = "rating_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    taken_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    mode: Mapped[str] = mapped_column(String(16))  # rapid/blitz/bullet/daily
    rating: Mapped[int | None] = mapped_column(Integer)
    best_rating: Mapped[int | None] = mapped_column(Integer)
    wins: Mapped[int | None] = mapped_column(Integer)
    losses: Mapped[int | None] = mapped_column(Integer)
    draws: Mapped[int | None] = mapped_column(Integer)

    player: Mapped["Player"] = relationship(back_populates="snapshots")  # noqa: F821

    __table_args__ = (Index("ix_snapshots_player_mode_taken", "player_id", "mode", "taken_at"),)
