from sqlalchemy import (
    Integer, Float, String, DateTime, ForeignKey, JSON, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # who/where this result belongs to
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id"), index=True, nullable=False)
    ticker_id: Mapped[int] = mapped_column(ForeignKey("tickers.id"), index=True, nullable=False)

    # when this row was produced
    run_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)

    # computed scan outputs (keep v1 simple)
    underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ma30: Mapped[float | None] = mapped_column(Float, nullable=True)

    option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)  # "put" / "call"
    expiry: Mapped[str | None] = mapped_column(String(10), nullable=True)      # "YYYY-MM-DD"
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    premium: Mapped[float | None] = mapped_column(Float, nullable=True)

    # return = premium/strike (NOT annualized)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # error handling / dashboard coloring
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ok")  # "ok" / "error"
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # optional: stash raw API bits for debugging/future features
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    list = relationship("List")
    ticker = relationship("Ticker", overlaps="scan_results")

    __table_args__ = (
        Index("ix_scan_results_list_runat", "list_id", "run_at"),
        Index("ix_scan_results_ticker_runat", "ticker_id", "run_at"),
    )

    @property
    def is_below_ma30(self) -> bool:
        if self.ma30 is None or self.underlying_price is None:
            return False
        return self.underlying_price < self.ma30
    
    @property
    def passes_ma30_filter(self) -> bool:
        if self.ma30 is None or self.underlying_price is None:
            return True
        if self.option_type == "call":
            return self.underlying_price >= self.ma30
        if self.option_type == "put":
            return self.underlying_price <= self.ma30
        return True