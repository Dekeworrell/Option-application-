from __future__ import annotations

from sqlalchemy import String, Float, DateTime, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OptionChainCache(Base):
    """
    Stores every option contract for each symbol.
    Refreshed every 60 seconds by the background scheduler.
    Replaces MarketCache for option data - allows frontend filtering
    by expiry, side, delta, strike, etc.
    """
    __tablename__ = "option_chain_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Symbol this contract belongs to
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # Underlying stock price at time of fetch
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Contract details
    option_ticker: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    option_side: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "Call" or "Put"
    expiry: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pricing
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Greeks
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Derived
    implied_volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Moneyness: "ITM", "ATM", "OTM"
    moneyness: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Percent OTM from underlying
    percent_otm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Return % = premium / strike * 100
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Fetch timestamp
    fetched_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Composite indexes for fast filtering
Index("ix_occ_symbol_side_expiry", OptionChainCache.symbol, OptionChainCache.option_side, OptionChainCache.expiry)
Index("ix_occ_symbol_delta", OptionChainCache.symbol, OptionChainCache.delta)
