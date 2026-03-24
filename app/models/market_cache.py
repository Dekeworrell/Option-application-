from __future__ import annotations

from sqlalchemy import String, Float, DateTime, func, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketCache(Base):
    """
    Stores the latest pre-fetched market data for each symbol.
    Updated by the background scheduler every 60 seconds.
    One row per symbol — upserted on each refresh.
    """
    __tablename__ = "market_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)

    # Underlying stock price
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Best option contract data
    option_ticker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    option_side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    expiry: Mapped[str | None] = mapped_column(String(16), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    moneyness: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Available expiries for manual selection
    available_expiries: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Timestamps
    fetched_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
