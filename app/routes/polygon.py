from __future__ import annotations

import asyncio
from datetime import datetime, date, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.polygon_client import PolygonClient

router = APIRouter()

UNDERLYING_CACHE_TTL_SECONDS = 300      # 5 minutes
OPTION_CHAIN_CACHE_TTL_SECONDS = 300    # 5 minutes
OPTION_PREV_CLOSE_CACHE_TTL_SECONDS = 600  # 10 minutes

_underlying_cache: dict[str, tuple[datetime, float]] = {}
_option_chain_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
_option_prev_close_cache: dict[str, tuple[datetime, float | None]] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_premium(
    premium_mode: str,
    bid: float | None,
    ask: float | None,
    last: float | None,
) -> float | None:
    if premium_mode == "bid":
        return bid
    if premium_mode == "ask":
        return ask
    if premium_mode == "last":
        return last
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    if last is not None:
        return last
    if bid is not None:
        return bid
    return ask


def _select_expiries(
    available_expiries: list[str],
    expiry_scope: str,
    horizon_mode: str,
    manual_expiry: str | None,
) -> list[str]:
    if not available_expiries:
        return []

    today = date.today().isoformat()
    future_expiries = [e for e in available_expiries if e > today]

    if expiry_scope == "manual":
        if manual_expiry and manual_expiry in available_expiries:
            return [manual_expiry]
        if future_expiries:
            return [future_expiries[0]]
        return []

    pool = future_expiries if future_expiries else available_expiries

    if expiry_scope == "weekly":
        return pool[:1]
    if expiry_scope == "near":
        return pool[:3]
    if expiry_scope == "far":
        return pool[-3:]
    if expiry_scope == "all":
        return pool
    if expiry_scope == "fixed-horizon":
        if horizon_mode == "1m":
            return pool[:4]
        if horizon_mode == "6m":
            return pool[:12]
        if horizon_mode == "1y":
            return pool[:24]

    return pool[:1]


async def _get_cached_underlying_price(client: PolygonClient, symbol: str) -> float:
    key = symbol.upper()
    now = _utc_now()

    cached = _underlying_cache.get(key)
    if cached:
        cached_at, cached_value = cached
        if (now - cached_at).total_seconds() < UNDERLYING_CACHE_TTL_SECONDS:
            return cached_value

    value = await client.get_prev_close(key)
    _underlying_cache[key] = (now, value)
    return value


async def _get_cached_option_chain(
    client: PolygonClient,
    symbol: str,
    contract_type: str | None,
) -> list[dict[str, Any]]:
    key = f"{symbol.upper()}::{contract_type or 'both'}"
    now = _utc_now()

    cached = _option_chain_cache.get(key)
    if cached:
        cached_at, cached_value = cached
        if (now - cached_at).total_seconds() < OPTION_CHAIN_CACHE_TTL_SECONDS:
            return cached_value

    value = await client.get_option_chain_snapshot(
        underlying=symbol,
        contract_type=contract_type,
        limit=250,
        max_pages=1,
    )
    _option_chain_cache[key] = (now, value)
    return value


async def _get_cached_option_prev_close(
    client: PolygonClient,
    option_ticker: str,
) -> float | None:
    """Fetch the previous close price for an option contract (cached)."""
    key = option_ticker.upper()
    now = _utc_now()

    cached = _option_prev_close_cache.get(key)
    if cached:
        cached_at, cached_value = cached
        if (now - cached_at).total_seconds() < OPTION_PREV_CLOSE_CACHE_TTL_SECONDS:
            return cached_value

    try:
        value = await client.get_prev_close(option_ticker)
        result = float(value) if value is not None else None
    except Exception:
        result = None

    _option_prev_close_cache[key] = (now, result)
    return result


def _resolve_best_contract(
    raw_chain: list[dict[str, Any]],
    underlying_price: float,
    expiry_scope: str,
    horizon_mode: str,
    option_side: str,
    premium_mode: str,
    manual_expiry: str | None,
    target_mode: str,
    target_delta: float | None,
    target_percent_otm: float | None,
) -> dict[str, Any]:
    """Pure function — resolves the best contract from a raw chain."""
    standard_contracts: list[dict[str, Any]] = []
    available_expiries_set: set[str] = set()

    for contract in raw_chain:
        details = contract.get("details", {}) or {}
        strike = _to_float(details.get("strike_price"))
        expiry = details.get("expiration_date")
        ctype = details.get("contract_type")

        if strike is None or not expiry or ctype not in {"call", "put"}:
            continue
        if strike <= 5:
            continue

        available_expiries_set.add(expiry)
        standard_contracts.append(contract)

    available_expiries = sorted(available_expiries_set)
    selected_expiries = _select_expiries(
        available_expiries=available_expiries,
        expiry_scope=expiry_scope,
        horizon_mode=horizon_mode,
        manual_expiry=manual_expiry,
    )
    selected_expiry = selected_expiries[0] if selected_expiries else None

    filtered_contracts: list[dict[str, Any]] = []
    for contract in standard_contracts:
        details = contract.get("details", {}) or {}
        expiry = details.get("expiration_date")
        ctype = details.get("contract_type")

        if expiry not in selected_expiries:
            continue
        if option_side == "calls" and ctype != "call":
            continue
        if option_side == "puts" and ctype != "put":
            continue

        filtered_contracts.append(contract)

    best_contract = None
    best_score = None

    for contract in filtered_contracts:
        details = contract.get("details", {}) or {}
        greeks = contract.get("greeks", {}) or {}
        last_quote = contract.get("last_quote", {}) or {}
        last_trade = contract.get("last_trade", {}) or {}

        strike = _to_float(details.get("strike_price"))
        expiry = details.get("expiration_date")
        ctype = details.get("contract_type")

        if strike is None or not expiry or ctype not in {"call", "put"}:
            continue

        delta_value = _to_float(greeks.get("delta"))
        gamma_value = _to_float(greeks.get("gamma"))
        theta_value = _to_float(greeks.get("theta"))
        vega_value = _to_float(greeks.get("vega"))
        rho_value = _to_float(greeks.get("rho"))

        bid = _to_float(last_quote.get("bid"))
        ask = _to_float(last_quote.get("ask"))
        last = _to_float(last_trade.get("price"))

        premium = _pick_premium(
            premium_mode=premium_mode,
            bid=bid,
            ask=ask,
            last=last,
        )

        if ctype == "call":
            percent_otm = ((strike - underlying_price) / underlying_price) * 100.0
            moneyness = "ITM" if strike < underlying_price else ("ATM" if strike == underlying_price else "OTM")
        else:
            percent_otm = ((underlying_price - strike) / underlying_price) * 100.0
            moneyness = "ITM" if strike > underlying_price else ("ATM" if strike == underlying_price else "OTM")

        if target_mode == "percent-otm":
            score = abs(percent_otm - float(target_percent_otm or 5.0))
        else:
            if delta_value is None:
                continue
            score = abs(abs(delta_value) - float(target_delta or 0.30))

        if best_score is None or score < best_score:
            best_score = score
            best_contract = {
                "optionTicker": details.get("ticker"),
                "optionSide": "Call" if ctype == "call" else "Put",
                "expiry": expiry,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "last": last,
                "premium": premium,
                "returnPercent": (premium / strike * 100.0)
                if premium is not None and strike > 0
                else None,
                "delta": delta_value,
                "gamma": gamma_value,
                "theta": theta_value,
                "vega": vega_value,
                "rho": rho_value,
                "moneyness": moneyness,
                "underlyingPrice": underlying_price,
            }

    return {
        "availableExpiries": available_expiries,
        "selectedExpiry": selected_expiry,
        "contractsEvaluated": len(filtered_contracts),
        "resolved": best_contract,
        "underlyingPrice": underlying_price,
    }


async def _apply_premium_fallback(
    client: PolygonClient,
    resolved: dict[str, Any] | None,
) -> None:
    """
    If premium is null, fetch the option's previous close as a fallback.
    Handles Starter plan accounts where bid/ask/last are not in the snapshot.
    Mutates resolved in place.
    """
    if not resolved or resolved.get("premium") is not None:
        return

    option_ticker = resolved.get("optionTicker")
    if not option_ticker:
        return

    prev_price = await _get_cached_option_prev_close(client, option_ticker)
    if prev_price is not None and prev_price > 0:
        resolved["premium"] = round(prev_price, 4)
        resolved["last"] = round(prev_price, 4)
        strike = resolved.get("strike")
        if strike and strike > 0:
            resolved["returnPercent"] = round((prev_price / strike) * 100.0, 4)


@router.get("/polygon/options/{symbol}")
async def get_polygon_option_resolved(
    symbol: str,
    expiry_scope: str = Query("weekly"),
    horizon_mode: str = Query("1m"),
    option_side: str = Query("calls"),
    premium_mode: str = Query("mid"),
    manual_expiry: str | None = Query(None),
    target_mode: str = Query("delta"),
    target_delta: float | None = Query(0.30),
    target_percent_otm: float | None = Query(5.0),
):
    try:
        client = PolygonClient()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    contract_type: str | None = None
    if option_side == "calls":
        contract_type = "call"
    elif option_side == "puts":
        contract_type = "put"

    try:
        underlying_price, raw_chain = await asyncio.gather(
            _get_cached_underlying_price(client, symbol),
            _get_cached_option_chain(client, symbol, contract_type),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Polygon request failed for {symbol.upper()}: {exc}",
        ) from exc

    result = _resolve_best_contract(
        raw_chain=raw_chain,
        underlying_price=underlying_price,
        expiry_scope=expiry_scope,
        horizon_mode=horizon_mode,
        option_side=option_side,
        premium_mode=premium_mode,
        manual_expiry=manual_expiry,
        target_mode=target_mode,
        target_delta=target_delta,
        target_percent_otm=target_percent_otm,
    )

    await _apply_premium_fallback(client, result.get("resolved"))

    return {
        "symbol": symbol.upper(),
        "expiryScope": expiry_scope,
        "horizonMode": horizon_mode,
        "optionSideRequest": option_side,
        "premiumMode": premium_mode,
        **result,
    }


@router.post("/polygon/options/bulk")
async def get_polygon_options_bulk(
    payload: dict[str, Any],
):
    """
    Accepts a list of symbols and shared query params.
    Fetches all symbols concurrently and returns results keyed by symbol.
    """
    symbols: list[str] = payload.get("symbols") or []
    expiry_scope: str = payload.get("expiryScope", "weekly")
    horizon_mode: str = payload.get("horizonMode", "1m")
    option_side: str = payload.get("optionSide", "calls")
    premium_mode: str = payload.get("premiumMode", "mid")
    manual_expiry: str | None = payload.get("manualExpiry")
    target_mode: str = payload.get("targetMode", "delta")
    target_delta: float | None = payload.get("targetDelta", 0.30)
    target_percent_otm: float | None = payload.get("targetPercentOtm", 5.0)

    if not symbols:
        return {"results": {}}

    try:
        client = PolygonClient()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    contract_type: str | None = None
    if option_side == "calls":
        contract_type = "call"
    elif option_side == "puts":
        contract_type = "put"

    async def fetch_one(symbol: str) -> tuple[str, dict[str, Any]]:
        try:
            underlying_price, raw_chain = await asyncio.gather(
                _get_cached_underlying_price(client, symbol),
                _get_cached_option_chain(client, symbol, contract_type),
            )
            result = _resolve_best_contract(
                raw_chain=raw_chain,
                underlying_price=underlying_price,
                expiry_scope=expiry_scope,
                horizon_mode=horizon_mode,
                option_side=option_side,
                premium_mode=premium_mode,
                manual_expiry=manual_expiry,
                target_mode=target_mode,
                target_delta=target_delta,
                target_percent_otm=target_percent_otm,
            )

            await _apply_premium_fallback(client, result.get("resolved"))

            return (symbol.upper(), {"symbol": symbol.upper(), **result, "error": None})
        except Exception as exc:
            return (
                symbol.upper(),
                {
                    "symbol": symbol.upper(),
                    "error": str(exc),
                    "resolved": None,
                    "availableExpiries": [],
                    "selectedExpiry": None,
                    "contractsEvaluated": 0,
                    "underlyingPrice": None,
                },
            )

    results_list = await asyncio.gather(*[fetch_one(s) for s in symbols])
    results = {symbol: data for symbol, data in results_list}

    return {"results": results}
