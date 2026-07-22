from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AwardedAchievement(Base):
    """One row per (player, achievement) actually earned. Catalog itself lives
    in code (achievements.CATALOG); only awards are persisted."""

    __tablename__ = "achievements_awarded"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    achievement_id: Mapped[str] = mapped_column(String(64))
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("player_id", "achievement_id", name="uq_award_player_ach"),
    )
