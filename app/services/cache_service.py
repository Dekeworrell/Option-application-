from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.ticker import Ticker
from app.models.option_chain_cache import OptionChainCache

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


def _get_percent_otm(underlying_price, strike, option_side) -> float | None:
    if underlying_price is None or strike is None or underlying_price == 0:
        return None
    side = (option_side or "").lower()
    if side == "call":
        return round((strike - underlying_price) / underlying_price * 100, 4)
    if side == "put":
        return round((underlying_price - strike) / underlying_price * 100, 4)
    return None


async def _fetch_bulk_stock_prices(symbols: list[str], api_key: str) -> dict[str, float | None]:
    prices: dict[str, float | None] = {s: None for s in symbols}
    try:
        url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        params = {"tickers": ",".join(symbols), "apiKey": api_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 200:
            for ticker_obj in resp.json().get("tickers") or []:
                symbol = ticker_obj.get("ticker")
                if not symbol or symbol not in prices:
                    continue
                day = ticker_obj.get("day") or {}
                prev_day = ticker_obj.get("prevDay") or {}
                last_trade = ticker_obj.get("lastTrade") or {}
                close = day.get("c") or last_trade.get("p") or prev_day.get("c")
                if close is not None:
                    prices[symbol] = float(close)
            logger.info(f"Bulk stock prices: {sum(1 for v in prices.values() if v is not None)}/{len(symbols)} fetched")
        else:
            logger.error(f"Bulk snapshot returned {resp.status_code}")
    except Exception as e:
        logger.error(f"Bulk stock price fetch failed: {e}")
    return prices


async def _fetch_option_chain_for_symbol(symbol: str, client) -> list[dict]:
    try:
        return await client.get_option_chain_snapshot(
            underlying=symbol,
            contract_type=None,
            limit=250,
            max_pages=1,
        )
    except Exception as e:
        logger.error(f"Option chain fetch failed for {symbol}: {e}")
        return []


def _normalize_contract(contract: dict, underlying_price: float | None) -> dict | None:
    details = contract.get("details") or {}
    quote = contract.get("last_quote") or {}
    trade = contract.get("last_trade") or {}
    greeks = contract.get("greeks") or {}

    strike = _safe_float(details.get("strike_price"))
    expiry = details.get("expiration_date")
    side = details.get("contract_type")
    option_ticker = details.get("ticker")

    if not expiry or strike is None or not option_ticker:
        return None

    try:
        if date.fromisoformat(expiry) < date.today():
            return None
    except ValueError:
        return None

    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    last = _safe_float(trade.get("price"))
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
    delta = _safe_float(greeks.get("delta"))
    gamma = _safe_float(greeks.get("gamma"))
    theta = _safe_float(greeks.get("theta"))
    vega = _safe_float(greeks.get("vega"))
    iv = _safe_float(contract.get("implied_volatility"))
    oi = contract.get("open_interest")

    option_side_label = "Call" if (side or "").lower() == "call" else "Put"
    moneyness = _get_moneyness(underlying_price, strike, side)
    percent_otm = _get_percent_otm(underlying_price, strike, side)
    premium = mid or last
    return_percent = round((premium / strike) * 100, 4) if premium and strike else None

    return {
        "option_ticker": option_ticker,
        "option_side": option_side_label,
        "expiry": expiry,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": last,
        "mid": mid,
        "prev_close": None,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "implied_volatility": iv,
        "open_interest": int(oi) if oi else None,
        "volume": None,
        "moneyness": moneyness,
        "percent_otm": percent_otm,
        "return_percent": return_percent,
    }


def _replace_symbol_contracts(db: Session, symbol: str, underlying_price: float | None, contracts: list[dict], now: datetime) -> int:
    db.query(OptionChainCache).filter(OptionChainCache.symbol == symbol).delete()
    count = 0
    for c in contracts:
        row = OptionChainCache(
            symbol=symbol,
            underlying_price=underlying_price,
            option_ticker=c["option_ticker"],
            option_side=c["option_side"],
            expiry=c["expiry"],
            strike=c["strike"],
            bid=c["bid"],
            ask=c["ask"],
            last=c["last"],
            mid=c["mid"],
            prev_close=c.get("prev_close"),
            delta=c["delta"],
            gamma=c["gamma"],
            theta=c["theta"],
            vega=c["vega"],
            implied_volatility=c["implied_volatility"],
            open_interest=c["open_interest"],
            volume=c["volume"],
            moneyness=c["moneyness"],
            percent_otm=c["percent_otm"],
            return_percent=c["return_percent"],
            fetched_at=now,
        )
        db.add(row)
        count += 1
    db.commit()
    return count


async def refresh_market_cache() -> None:
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

        prices, raw_chains = await asyncio.gather(
            _fetch_bulk_stock_prices(symbols, api_key),
            _fetch_all_chains(symbols, client),
        )

        now = datetime.now(timezone.utc)
        total_contracts = 0
        success_count = 0

        for symbol in symbols:
            underlying_price = prices.get(symbol)
            raw_chain = raw_chains.get(symbol, [])

            contracts = []
            for raw_contract in raw_chain:
                normalized = _normalize_contract(raw_contract, underlying_price)
                if normalized:
                    contracts.append(normalized)

            try:
                count = _replace_symbol_contracts(db, symbol, underlying_price, contracts, now)
                total_contracts += count
                if contracts:
                    success_count += 1
                logger.info(f"Cache: {symbol} -> price={underlying_price}, contracts={count}")
            except Exception as e:
                logger.error(f"Failed to store contracts for {symbol}: {e}")
                db.rollback()

        logger.info(f"Cache refresh complete: {success_count}/{len(symbols)} symbols, {total_contracts} contracts")

    except Exception as e:
        logger.error(f"Cache refresh failed: {e}")
    finally:
        db.close()


async def _fetch_all_chains(symbols: list[str], client) -> dict[str, list[dict]]:
    results = {}
    batch_size = 10
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_results = await asyncio.gather(
            *[_fetch_option_chain_for_symbol(s, client) for s in batch],
            return_exceptions=True,
        )
        for symbol, result in zip(batch, batch_results):
            results[symbol] = [] if isinstance(result, Exception) else result
        if i + batch_size < len(symbols):
            await asyncio.sleep(0.3)
    return results


async def _fetch_prev_close(option_ticker: str, client) -> float | None:
    try:
        return await client.get_prev_close(option_ticker)
    except Exception:
        return None
