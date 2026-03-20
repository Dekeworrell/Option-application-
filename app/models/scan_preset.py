from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, List, Dict

from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.core.database import Base


class ScanPreset(Base):
    __tablename__ = "scan_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)

    option_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "call" | "put"
    delta_target: Mapped[float] = mapped_column(Float, nullable=False)

    # Store list of indicator dicts
    indicators: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    # Trend filter
    use_trend_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trend_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # "sma" | "ema"
    trend_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # RSI filter
    use_rsi_filter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rsi_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rsi_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rsi_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="scan_presets")