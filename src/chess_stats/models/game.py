from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    # dedupe key per player — NOT globally unique: when two tracked players
    # played each other, the same game uuid exists once under each player
    uuid: Mapped[str] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(256))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))

    end_time: Mapped[datetime] = mapped_column(DateTime)
    time_class: Mapped[str] = mapped_column(String(16))  # rapid/blitz/bullet/daily
    time_control: Mapped[str | None] = mapped_column(String(32))
    rated: Mapped[bool] = mapped_column(Boolean, default=True)

    color: Mapped[str] = mapped_column(String(5))  # white/black
    opponent: Mapped[str | None] = mapped_column(String(64))
    opponent_rating: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(8))  # win/loss/draw
    termination: Mapped[str | None] = mapped_column(String(32))  # checkmated, timeout, resigned…
    my_rating: Mapped[int | None] = mapped_column(Integer)  # post-game

    eco: Mapped[str | None] = mapped_column(String(8), index=True)
    opening_name: Mapped[str | None] = mapped_column(String(128))
    pgn: Mapped[str | None] = mapped_column(Text)
    accuracy_mine: Mapped[float | None] = mapped_column(Float)
    accuracy_opponent: Mapped[float | None] = mapped_column(Float)

    player: Mapped["Player"] = relationship(back_populates="games")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("player_id", "uuid", name="uq_games_player_uuid"),
        Index("ix_games_player_end_time", "player_id", "end_time"),
        Index("ix_games_player_time_class", "player_id", "time_class"),
    )
