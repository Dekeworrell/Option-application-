from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.ticker import Ticker
from app.models.market_cache import MarketCache

logger = logging.getLogger(__name__)


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_moneyness(underlying_price, strike, option_side) -> str | None:
    if underlying_price is None or strike is None or not option_side:
        return None
    if underlying_price == 0:
        return None
    distance_pct = abs(strike - underlying_price) / underlying_price
    if distance_pct < 0.01:
        return "ATM"
    side = (option_side or "").lower()
    if side == "call":
        return "ITM" if strike < underlying_price else "OTM"
    if side == "put":
        return "ITM" if strike > underlying_price else "OTM"
    return None


def _pick_best_expiry(expiries: list[str]) -> str | None:
    if not expiries:
        return None
    today = date.today()
    parsed = sorted(date.fromisoformat(x) for x in expiries)
    # Prefer nearest Friday
    fridays = [d for d in parsed if d >= today and d.weekday() == 4]
    if fridays:
        return fridays[0].isoformat()
    future = [d for d in parsed if d >= today]
    return (future[0] if future else parsed[0]).isoformat()


def _pick_best_contract(contracts: list[dict], underlying_price: float | None) -> dict | None:
    if not contracts:
        return None

    calls = [c for c in contracts if (c.get("optionSide") or "").lower() == "call"]
    pool = calls if calls else contracts

    if underlying_price is None or underlying_price <= 0:
        return pool[0] if pool else None

    otm = [c for c in pool if (_safe_float(c.get("strike")) or 0) >= underlying_price]
    within_band = [c for c in otm if abs((_safe_float(c.get("strike")) or 0) - underlying_price) / underlying_price <= 0.20]
    pool = within_band if within_band else (otm if otm else pool)

    def sort_key(c):
        delta = _safe_float(c.get("delta"))
        strike = _safe_float(c.get("strike")) or 999999.0
        delta_distance = abs((delta or 0) - 0.30) if delta is not None else 999
        price_distance = abs(strike - underlying_price) / underlying_price if underlying_price else 999
        return (delta_distance, price_distance)

    return sorted(pool, key=sort_key)[0] if pool else None


async def _fetch_bulk_stock_prices(symbols: list[str], api_key: str) -> dict[str, float | None]:
    """
    Fetch all stock prices in a single API call using the bulk snapshot endpoint.
    Requires Stocks Starter plan or higher.
    """
    prices: dict[str, float | None] = {s: None for s in symbols}

    try:
        tickers_param = ",".join(symbols)
        url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        params = {"tickers": tickers_param, "apiKey": api_key}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)

        if resp.status_code == 200:
            data = resp.json()
            tickers_data = data.get("tickers") or []

            for ticker_obj in tickers_data:
                symbol = ticker_obj.get("ticker")
                if not symbol or symbol not in prices:
                    continue

                day = ticker_obj.get("day") or {}
                prev_day = ticker_obj.get("prevDay") or {}
                last_trade = ticker_obj.get("lastTrade") or {}

                close = day.get("c") or last_trade.get("p")
                if close is None:
                    close = prev_day.get("c")

                if close is not None:
                    prices[symbol] = float(close)

            logger.info(f"Bulk stock prices: {sum(1 for v in prices.values() if v is not None)}/{len(symbols)} fetched")
        else:
            logger.error(f"Bulk stock snapshot returned {resp.status_code}: {resp.text[:200]}")

    except Exception as e:
        logger.error(f"Bulk stock price fetch failed: {e}")

    return prices


async def _fetch_option_chain(symbol: str, client) -> tuple[str, list[dict], list[str]]:
    """Fetch option chain for one symbol."""
    try:
        raw_chain = await client.get_option_chain_snapshot(
            underlying=symbol,
            contract_type=None,
            limit=250,
            max_pages=1,
        )

        contracts = []
        available_expiries = set()

        for contract in raw_chain:
            details = contract.get("details") or {}
            quote = contract.get("last_quote") or {}
            trade = contract.get("last_trade") or {}
            greeks = contract.get("greeks") or {}

            strike = _safe_float(details.get("strike_price"))
            expiry = details.get("expiration_date")
            side = details.get("contract_type")

            if not expiry or strike is None:
                continue

            try:
                if date.fromisoformat(expiry) < date.today():
                    continue
            except ValueError:
                continue

            available_expiries.add(expiry)

            bid = _safe_float(quote.get("bid"))
            ask = _safe_float(quote.get("ask"))
            last = _safe_float(trade.get("price"))
            premium = round((bid + ask) / 2, 4) if bid is not None and ask is not None else last

            contracts.append({
                "optionTicker": details.get("ticker"),
                "optionSide": "Call" if (side or "").lower() == "call" else "Put",
                "expiry": expiry,
                "strike": strike,
                "premium": premium,
                "returnPercent": round((premium / strike) * 100, 4) if premium and strike else None,
                "delta": _safe_float(greeks.get("delta")),
                "gamma": _safe_float(greeks.get("gamma")),
                "theta": _safe_float(greeks.get("theta")),
                "vega": _safe_float(greeks.get("vega")),
            })

        return symbol, contracts, sorted(available_expiries)

    except Exception as e:
        logger.error(f"Option chain fetch failed for {symbol}: {e}")
        return symbol, [], []


async def _fetch_option_premium_fallback(option_ticker: str, client) -> float | None:
    """Get premium from prev close if bid/ask unavailable."""
    try:
        return await client.get_prev_close(option_ticker)
    except Exception:
        return None


def _upsert_cache(db: Session, data: dict) -> None:
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
    Fast cache refresh using bulk stock snapshot + concurrent option chains.
    Total time: ~10-20 seconds for all 52 symbols.
    """
    from app.services.polygon_client import PolygonClient
    from app.core.config import settings

    db: Session = SessionLocal()

    try:
        symbols = [
            row[0] for row in
            db.query(Ticker.symbol).distinct().order_by(Ticker.symbol).all()
        ]

        if not symbols:
            return

        logger.info(f"Cache refresh starting: {len(symbols)} symbols")

        try:
            client = PolygonClient()
            api_key = settings.polygon_api_key
        except Exception as e:
            logger.error(f"Failed to create Polygon client: {e}")
            return

        # Phase 1: Fetch all stock prices in ONE bulk API call (Stocks Starter)
        # and all option chains concurrently
        prices, chain_data = await asyncio.gather(
            _fetch_bulk_stock_prices(symbols, api_key),
            _fetch_all_option_chains(symbols, client),
        )

        logger.info(f"Data fetched - processing {len(symbols)} symbols")

        # Phase 2: Combine and upsert
        success_count = 0
        fallback_tasks = []

        for symbol in symbols:
            underlying_price = prices.get(symbol)
            contracts, expiries = chain_data.get(symbol, ([], []))

            best_expiry = _pick_best_expiry(expiries)
            expiry_contracts = [c for c in contracts if c.get("expiry") == best_expiry] if best_expiry else contracts

            for c in expiry_contracts:
                c["moneyness"] = _get_moneyness(underlying_price, c.get("strike"), c.get("optionSide"))

            resolved = _pick_best_contract(expiry_contracts, underlying_price)

            data = {
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
                "available_expiries": expiries,
                "status": "ok" if resolved else "no_contract",
                "error": None,
            }

            # Queue premium fallback if needed
            if resolved and not resolved.get("premium") and resolved.get("optionTicker"):
                fallback_tasks.append((symbol, resolved.get("optionTicker"), resolved.get("strike"), data))
            else:
                logger.info(f"Cache: {symbol} -> price={underlying_price}, expiry={data['expiry']}, premium={data['premium']}")
                try:
                    _upsert_cache(db, data)
                    if resolved:
                        success_count += 1
                except Exception as e:
                    logger.error(f"Upsert failed for {symbol}: {e}")
                    db.rollback()

        # Phase 3: Fetch premium fallbacks concurrently
        if fallback_tasks:
            logger.info(f"Fetching {len(fallback_tasks)} premium fallbacks...")
            fallback_results = await asyncio.gather(
                *[_fetch_option_premium_fallback(opt_ticker, client) for _, opt_ticker, _, _ in fallback_tasks],
                return_exceptions=True,
            )

            for (symbol, opt_ticker, strike, data), fallback in zip(fallback_tasks, fallback_results):
                if isinstance(fallback, Exception):
                    fallback = None
                if fallback:
                    data["premium"] = fallback
                    if strike:
                        data["return_percent"] = round((fallback / strike) * 100, 4)

                logger.info(f"Cache: {symbol} -> price={data['underlying_price']}, expiry={data['expiry']}, premium={data['premium']}")
                try:
                    _upsert_cache(db, data)
                    if data.get("status") == "ok":
                        success_count += 1
                except Exception as e:
                    logger.error(f"Upsert failed for {symbol}: {e}")
                    db.rollback()

        logger.info(f"Cache refresh complete: {success_count}/{len(symbols)} symbols OK")

    except Exception as e:
        logger.error(f"Cache refresh failed: {e}")
    finally:
        db.close()


async def _fetch_all_option_chains(symbols: list[str], client) -> dict[str, tuple[list[dict], list[str]]]:
    """Fetch all option chains concurrently in batches."""
    results = {}
    batch_size = 10

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[_fetch_option_chain(s, client) for s in batch],
            return_exceptions=True,
        )
        for result in batch_results:
            if isinstance(result, Exception):
                continue
            sym, contracts, expiries = result
            results[sym] = (contracts, expiries)

        if i + batch_size < len(symbols):
            await asyncio.sleep(0.3)

    return results
