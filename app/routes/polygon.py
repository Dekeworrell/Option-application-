from __future__ import annotations

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

    value = await client.get_option_chain_snapshot(
        underlying=symbol,
        contract_type=contract_type,
        limit=250,
        max_pages=8,
    )
    _option_chain_cache[key] = (now, value)
    return value


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
            if strike < underlying_price:
                moneyness = "ITM"
            elif strike == underlying_price:
                moneyness = "ATM"
            else:
                moneyness = "OTM"
        else:
            percent_otm = ((underlying_price - strike) / underlying_price) * 100.0
            if strike > underlying_price:
                moneyness = "ITM"
            elif strike == underlying_price:
                moneyness = "ATM"
            else:
                moneyness = "OTM"

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
        "symbol": symbol.upper(),
        "expiryScope": expiry_scope,
        "horizonMode": horizon_mode,
        "optionSideRequest": option_side,
        "premiumMode": premium_mode,
        "availableExpiries": available_expiries,
        "selectedExpiry": selected_expiry,
        "contractsEvaluated": len(filtered_contracts),
        "resolved": best_contract,
        "underlyingPrice": underlying_price,
    }