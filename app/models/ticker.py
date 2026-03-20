from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Ticker(Base):
    __tablename__ = "tickers"
    __table_args__ = (
        UniqueConstraint("list_id", "symbol", name="uq_tickers_list_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("lists.id"), index=True, nullable=False)

    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    list = relationship("List", back_populates="tickers")
    scan_results = relationship("ScanResult", cascade="all, delete-orphan")