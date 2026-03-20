from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class List(Base):
    __tablename__ = "lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # NEW: default preset
    default_preset_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_presets.id"),
        nullable=True,
    )

    user = relationship("User", back_populates="lists")

    tickers = relationship(
        "Ticker",
        back_populates="list",
        cascade="all, delete-orphan",
    )

    default_preset = relationship("ScanPreset")