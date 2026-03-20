from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.polygon_client import PolygonClient

router = APIRouter()

UNDERLYING_CACHE_TTL_SECONDS = 60
OPTION_CHAIN_CACHE_TTL_SECONDS = 60

_underlying_cache: dict[str, tuple[datetime, float]] = {}
_option_chain_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}


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

    if expiry_scope == "manual":
        if manual_expiry and manual_expiry in available_expiries:
            return [manual_expiry]
        if available_expiries:
            return [available_expiries[0]]
        return []

    if expiry_scope == "weekly":
        return available_expiries[:1]

    if expiry_scope == "near":
        return available_expiries[:3]

    if expiry_scope == "far":
        return available_expiries[-3:]

    if expiry_scope == "all":
        return available_expiries

    if expiry_scope == "fixed-horizon":
        if horizon_mode == "1m":
            return available_expiries[:4]
        if horizon_mode == "6m":
            return available_expiries[:12]
        if horizon_mode == "1y":
            return available_expiries[:24]

    return available_expiries[:1]


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

    # Reduced from max_pages=8 to max_pages=3 — fetching 750 contracts
    # is more than enough to find the best match and is 3x faster.
    value = await client.get_option_chain_snapshot(
        underlying=symbol,
        contract_type=contract_type,
        limit=250,
        max_pages=3,
    )
    _option_chain_cache[key] = (now, value)
    return value


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
    """
    Pure function — resolves the best contract from a raw chain.
    Shared by both the single and bulk endpoints.
    """
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
        underlying_price = await _get_cached_underlying_price(client, symbol)
        raw_chain = await _get_cached_option_chain(client, symbol, contract_type)
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

    Request body:
    {
        "symbols": ["AAPL", "MSFT", "NVDA"],
        "expiryScope": "weekly",
        "horizonMode": "1m",
        "optionSide": "calls",
        "premiumMode": "mid",
        "manualExpiry": null,
        "targetMode": "delta",
        "targetDelta": 0.30,
        "targetPercentOtm": 5.0
    }
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

    # Fetch all symbols truly concurrently
    results_list = await asyncio.gather(*[fetch_one(s) for s in symbols])
    results = {symbol: data for symbol, data in results_list}

    return {"results": results}