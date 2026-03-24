from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.ticker import Ticker
from app.models.market_cache import MarketCache

logger = logging.getLogger(__name__)


async def _fetch_symbol(symbol: str, client) -> dict:
    """Fetch option chain data for a single symbol and return normalized result."""
    from app.routes.polygon import (
        _get_cached_underlying_price,
        _get_cached_option_chain,
        _resolve_best_contract,
        _apply_premium_fallback,
    )

    try:
        underlying_price, raw_chain = await asyncio.gather(
            _get_cached_underlying_price(client, symbol),
            _get_cached_option_chain(client, symbol, "call"),
        )

        result = _resolve_best_contract(
            raw_chain=raw_chain,
            underlying_price=underlying_price,
            expiry_scope="weekly",
            horizon_mode="1m",
            option_side="calls",
            premium_mode="mid",
            manual_expiry=None,
            target_mode="delta",
            target_delta=0.30,
            target_percent_otm=5.0,
        )

        await _apply_premium_fallback(client, result.get("resolved"))

        resolved = result.get("resolved")

        return {
            "symbol": symbol,
            "underlying_price": underlying_price,
            "option_ticker": resolved.get("optionTicker") if resolved else None,
            "option_side": resolved.get("optionSide") if resolved else None,
            "expiry": resolved.get("expiry") if resolved else None,
            "strike": resolved.get("strike") if resolved else None,
            "premium": resolved.get("premium") if resolved else None,
            "return_percent": resolved.get("returnPercent") if resolved else None,
            "delta": resolved.get("delta") if resolved else None,
            "gamma": resolved.get("gamma") if resolved else None,
            "theta": resolved.get("theta") if resolved else None,
            "vega": resolved.get("vega") if resolved else None,
            "moneyness": resolved.get("moneyness") if resolved else None,
            "available_expiries": result.get("availableExpiries", []),
            "status": "ok" if resolved else "no_contract",
            "error": None,
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "underlying_price": None,
            "option_ticker": None,
            "option_side": None,
            "expiry": None,
            "strike": None,
            "premium": None,
            "return_percent": None,
            "delta": None,
            "gamma": None,
            "theta": None,
            "vega": None,
            "moneyness": None,
            "available_expiries": [],
            "status": "error",
            "error": str(e)[:512],
        }


def _upsert_cache(db: Session, data: dict) -> None:
    """Insert or update a MarketCache row for a symbol."""
    symbol = data["symbol"]
    row = db.query(MarketCache).filter(MarketCache.symbol == symbol).first()

    now = datetime.now(timezone.utc)

    if row is None:
        row = MarketCache(symbol=symbol)
        db.add(row)

    row.underlying_price = data["underlying_price"]
    row.option_ticker = data["option_ticker"]
    row.option_side = data["option_side"]
    row.expiry = data["expiry"]
    row.strike = data["strike"]
    row.premium = data["premium"]
    row.return_percent = data["return_percent"]
    row.delta = data["delta"]
    row.gamma = data["gamma"]
    row.theta = data["theta"]
    row.vega = data["vega"]
    row.moneyness = data["moneyness"]
    row.available_expiries = data["available_expiries"]
    row.status = data["status"]
    row.error = data["error"]
    row.fetched_at = now

    db.commit()


async def refresh_market_cache() -> None:
    """
    Main scheduler task — fetches all unique symbols across all watchlists
    and updates the market_cache table.
    Runs every 60 seconds via APScheduler.
    """
    from app.services.polygon_client import PolygonClient

    db: Session = SessionLocal()

    try:
        # Get all unique symbols across all watchlists
        symbols = [
            row[0] for row in
            db.query(Ticker.symbol).distinct().order_by(Ticker.symbol).all()
        ]

        if not symbols:
            return

        logger.info(f"Market cache refresh: {len(symbols)} symbols")

        try:
            client = PolygonClient()
        except Exception as e:
            logger.error(f"Failed to create Polygon client: {e}")
            return

        # Fetch all symbols concurrently in batches of 10
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]

            results = await asyncio.gather(
                *[_fetch_symbol(s, client) for s in batch],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    continue
                try:
                    _upsert_cache(db, result)
                except Exception as e:
                    logger.error(f"Failed to upsert cache for {result.get('symbol')}: {e}")
                    db.rollback()

            # Small delay between batches to be respectful of API limits
            if i + batch_size < len(symbols):
                await asyncio.sleep(0.5)

        logger.info(f"Market cache refresh complete: {len(symbols)} symbols")

    except Exception as e:
        logger.error(f"Market cache refresh failed: {e}")
    finally:
        db.close()
