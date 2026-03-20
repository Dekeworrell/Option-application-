from pathlib import Path
from datetime import date, timedelta
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=env_path)

from app.routes.auth import router as auth_router
from app.routes.lists import router as lists_router
from app.routes.tickers import router as tickers_router
from app.routes.presets import router as presets_router

import app.models  # noqa: F401

from app.services.polygon_client import PolygonClient
from app.utils.dates import nearest_friday
from app.routes.polygon import router as polygon_router

app = FastAPI()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(lists_router)
app.include_router(tickers_router)
app.include_router(presets_router)
app.include_router(polygon_router)

polygon_client = PolygonClient()

_underlying_cache: dict[str, dict[str, Any]] = {}
UNDERLYING_CACHE_TTL_SECONDS = 60


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

async def _get_cached_underlying_price(symbol: str) -> float | None:
    from time import time

    key = symbol.upper().strip()
    now_ts = time()
    cached = _underlying_cache.get(key)

    if cached and (now_ts - cached["timestamp"] < UNDERLYING_CACHE_TTL_SECONDS):
        return cached["price"]

    try:
        prev_close = await polygon_client.get_prev_close(key)
        price = _safe_float(prev_close)
    except Exception:
        price = cached["price"] if cached else None

    if price is not None:
        _underlying_cache[key] = {
            "timestamp": now_ts,
            "price": price,
        }

    return price

def _get_contract_type_label(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.lower().strip()
    if normalized == "call":
        return "Call"
    if normalized == "put":
        return "Put"
    return None


def _get_moneyness(
    underlying_price: float | None,
    strike: float | None,
    option_side: str | None,
) -> str | None:
    if underlying_price is None or strike is None or not option_side:
        return None

    if underlying_price == 0:
        return None

    distance_pct = abs(strike - underlying_price) / underlying_price
    if distance_pct < 0.01:
        return "ATM"

    if option_side.lower() == "call":
        return "ITM" if strike < underlying_price else "OTM"

    if option_side.lower() == "put":
        return "ITM" if strike > underlying_price else "OTM"

    return None


def _get_premium(
    bid: float | None,
    ask: float | None,
    last: float | None,
    premium_mode: str,
) -> float | None:
    if premium_mode == "bid":
        return bid
    if premium_mode == "ask":
        return ask
    if premium_mode == "last":
        return last
    if premium_mode == "mid":
        if bid is not None and ask is not None:
            return round((bid + ask) / 2, 4)
        return last
    return last

def _is_standard_contract(contract: dict) -> bool:
    details = contract.get("details") or {}

    shares_per_contract = details.get("shares_per_contract")
    if shares_per_contract not in (None, 100):
        return False

    if details.get("additional_underlyings"):
        return False

    ticker = details.get("ticker")
    if isinstance(ticker, str):
        prefix = f"O:{(details.get('underlying_ticker') or '').upper()}"
        if prefix != "O:" and ticker.startswith(prefix):
            suffix = ticker[len(prefix):]
            if suffix and suffix[0].isdigit():
                # Standard options should begin with YY after the symbol, not 1YY...
                if len(suffix) >= 7 and suffix[0] == "1":
                    return False

    return True

def _normalize_snapshot_contract(contract: dict, premium_mode: str) -> dict | None:
    details = contract.get("details") or {}
    quote = contract.get("last_quote") or {}
    trade = contract.get("last_trade") or {}
    greeks = contract.get("greeks") or {}
    underlying_asset = contract.get("underlying_asset") or {}

    strike = _safe_float(details.get("strike_price"))
    expiry = details.get("expiration_date")
    option_side = details.get("contract_type")
    option_ticker = details.get("ticker")

    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    last = _safe_float(trade.get("price"))
    premium = _get_premium(bid, ask, last, premium_mode)
    underlying_price = _safe_float(underlying_asset.get("price"))
    return_percent = round((premium / strike) * 100, 4) if premium is not None and strike else None

    normalized = {
        "optionTicker": option_ticker,
        "optionSide": _get_contract_type_label(option_side),
        "expiry": expiry,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": last,
        "premium": premium,
        "returnPercent": return_percent,
        "delta": _safe_float(greeks.get("delta")),
        "gamma": _safe_float(greeks.get("gamma")),
        "theta": _safe_float(greeks.get("theta")),
        "vega": _safe_float(greeks.get("vega")),
        "rho": None,
        "underlyingPrice": underlying_price,
        "moneyness": _get_moneyness(underlying_price, strike, option_side),
    }

    if not normalized["expiry"] or normalized["strike"] is None:
        return None

    return normalized


def _pick_expiry(
    available_expiries: list[str],
    expiry_scope: str,
    horizon_mode: str,
    manual_expiry: str | None,
) -> str | None:
    if not available_expiries:
        return None

    parsed = sorted(date.fromisoformat(x) for x in available_expiries)
    today = date.today()

    if expiry_scope == "manual" and manual_expiry:
        try:
            desired = date.fromisoformat(manual_expiry)
            if desired in parsed:
                return desired.isoformat()
        except ValueError:
            pass

    if expiry_scope == "weekly":
        target_friday = nearest_friday(today)
        friday_matches = [d for d in parsed if d >= today and d.weekday() == 4]
        if friday_matches:
            best = min(friday_matches, key=lambda d: abs((d - target_friday).days))
            return best.isoformat()

    if expiry_scope == "near" or expiry_scope == "manual":
        future = [d for d in parsed if d >= today]
        return (future[0] if future else parsed[0]).isoformat()

    if expiry_scope == "far":
        future = [d for d in parsed if d >= today]
        return (future[-1] if future else parsed[-1]).isoformat()

    if expiry_scope == "fixed-horizon":
        if horizon_mode == "1m":
            target = today + timedelta(days=30)
        elif horizon_mode == "6m":
            target = today + timedelta(days=182)
        else:
            target = today + timedelta(days=365)

        best = min(parsed, key=lambda d: abs((d - target).days))
        return best.isoformat()

    return None

def _pick_best_candidate(
    contracts: list[dict],
    underlying_price: float | None,
) -> dict | None:
    if not contracts:
        return None

    if underlying_price is None or underlying_price <= 0:
        contracts_sorted = sorted(
            contracts,
            key=lambda contract: (
                0 if _safe_float(contract.get("premium")) is not None else 1,
                _safe_float(contract.get("strike")) or 999999.0,
            ),
        )
        return contracts_sorted[0] if contracts_sorted else None

    valid_contracts: list[dict] = []
    for contract in contracts:
        strike = _safe_float(contract.get("strike"))
        option_side = (contract.get("optionSide") or "").lower().strip()

        if strike is None or strike <= 0:
            continue

        if option_side == "call" and strike >= underlying_price:
            valid_contracts.append(contract)
        elif option_side == "put" and strike <= underlying_price:
            valid_contracts.append(contract)

    pool = valid_contracts if valid_contracts else contracts

    def sort_key(contract: dict) -> tuple[float, int, float]:
        strike = _safe_float(contract.get("strike")) or 999999.0
        premium = _safe_float(contract.get("premium"))
        distance_pct = abs(strike - underlying_price) / underlying_price

        return (
            distance_pct,
            0 if premium is not None else 1,
            strike,
        )

    pool_sorted = sorted(pool, key=sort_key)

    within_band = []
    for contract in pool_sorted:
        strike = _safe_float(contract.get("strike"))
        if strike is None:
            continue

        distance_pct = abs(strike - underlying_price) / underlying_price
        if distance_pct <= 0.10:
            within_band.append(contract)

    if within_band:
        return sorted(within_band, key=sort_key)[0]

    return pool_sorted[0] if pool_sorted else None

@app.get("/polygon/status")
async def polygon_status():
    return await polygon_client.markets_status()


@app.get("/polygon/last/{symbol}")
async def polygon_last(symbol: str):
    prev_close = await polygon_client.get_prev_close(symbol)
    return {
        "symbol": symbol.upper(),
        "prev_close": float(prev_close),
    }


@app.get("/polygon/debug")
async def polygon_debug():
    return {
        "polygon_client_class": str(type(polygon_client)),
        "polygon_client_file": str(type(polygon_client).__module__),
        "has_get_option_chain_snapshot": hasattr(polygon_client, "get_option_chain_snapshot"),
        "has_get_option_contract_snapshot": hasattr(polygon_client, "get_option_contract_snapshot"),
    }


def _pick_best_candidate(
    contracts: list[dict],
    underlying_price: float | None,
) -> dict | None:
    if not contracts:
        return None

    if underlying_price is None or underlying_price <= 0:
        contracts_sorted = sorted(
            contracts,
            key=lambda contract: (
                0 if _safe_float(contract.get("premium")) is not None else 1,
                _safe_float(contract.get("strike")) or 999999.0,
            ),
        )
        return contracts_sorted[0] if contracts_sorted else None

    valid_contracts: list[dict] = []
    for contract in contracts:
        strike = _safe_float(contract.get("strike"))
        option_side = (contract.get("optionSide") or "").lower().strip()

        if strike is None or strike <= 0:
            continue

        if option_side == "call" and strike >= underlying_price:
            valid_contracts.append(contract)
        elif option_side == "put" and strike <= underlying_price:
            valid_contracts.append(contract)

    pool = valid_contracts if valid_contracts else contracts

    def sort_key(contract: dict) -> tuple[float, int, float]:
        strike = _safe_float(contract.get("strike")) or 999999.0
        premium_value = _safe_float(contract.get("premium"))
        distance_pct = abs(strike - underlying_price) / underlying_price

        return (
            distance_pct,
            0 if premium_value is not None else 1,
            strike,
        )

    pool_sorted = sorted(pool, key=sort_key)

    within_band = []
    for contract in pool_sorted:
        strike = _safe_float(contract.get("strike"))
        if strike is None:
            continue

        distance_pct = abs(strike - underlying_price) / underlying_price
        if distance_pct <= 0.10:
            within_band.append(contract)

    if within_band:
        return sorted(within_band, key=sort_key)[0]

    return pool_sorted[0] if pool_sorted else None


@app.get("/polygon/options/{symbol}")
async def polygon_options(
    symbol: str,
    expiry_scope: str = Query("weekly"),
    horizon_mode: str = Query("1m"),
    option_side: str = Query("calls"),
    premium_mode: str = Query("mid"),
    manual_expiry: str | None = Query(None),
):
    scope = expiry_scope.strip().lower()
    horizon = horizon_mode.strip().lower()
    side = option_side.strip().lower()
    premium = premium_mode.strip().lower()

    underlying_price = await _get_cached_underlying_price(symbol)

    raw_contracts = await polygon_client.get_option_chain_snapshot(
        underlying=symbol,
        expiration_date=None,
        contract_type=None,
        limit=250,
    )

    normalized_contracts = []
    for contract in raw_contracts:
        if not _is_standard_contract(contract):
            continue

        normalized = _normalize_snapshot_contract(contract, premium)
        if normalized is None:
            continue

        normalized["underlyingPrice"] = underlying_price
        normalized["moneyness"] = _get_moneyness(
            underlying_price,
            _safe_float(normalized.get("strike")),
            normalized.get("optionSide"),
        )
        normalized_contracts.append(normalized)

    available_expiries = sorted(
        {contract["expiry"] for contract in normalized_contracts if contract.get("expiry")}
    )

    selected_expiry = _pick_expiry(
        available_expiries=available_expiries,
        expiry_scope=scope,
        horizon_mode=horizon,
        manual_expiry=manual_expiry,
    )

    filtered_contracts = normalized_contracts

    if scope != "all" and selected_expiry:
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("expiry") == selected_expiry
        ]

    if underlying_price is not None and underlying_price > 0:
        bounded_contracts = []
        for contract in filtered_contracts:
            strike = _safe_float(contract.get("strike"))
            if strike is None:
                continue

            distance_pct = abs(strike - underlying_price) / underlying_price
            if distance_pct <= 0.50:
                bounded_contracts.append(contract)

        if bounded_contracts:
            filtered_contracts = bounded_contracts

    if side == "calls":
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("optionSide") == "Call"
        ]
    elif side == "puts":
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("optionSide") == "Put"
        ]

    resolved = _pick_best_candidate(filtered_contracts, underlying_price)

    if resolved:
        strike_value = _safe_float(resolved.get("strike"))
        resolved["underlyingPrice"] = underlying_price
        resolved["moneyness"] = _get_moneyness(
            underlying_price,
            strike_value,
            resolved.get("optionSide"),
        )

        if not _safe_float(resolved.get("premium")):
            option_ticker = resolved.get("optionTicker")
            if option_ticker:
                try:
                    fallback_premium = await polygon_client.get_option_prev_close(option_ticker)
                except Exception:
                    fallback_premium = None

                if fallback_premium is not None:
                    resolved["premium"] = fallback_premium
                    if strike_value not in (None, 0):
                        resolved["returnPercent"] = round((fallback_premium / strike_value) * 100, 4)

    return {
        "symbol": symbol.upper(),
        "expiryScope": scope,
        "horizonMode": horizon,
        "optionSideRequest": side,
        "premiumMode": premium,
        "availableExpiries": available_expiries,
        "selectedExpiry": resolved.get("expiry") if resolved else selected_expiry,
        "contractsEvaluated": len(filtered_contracts),
        "resolved": resolved,
    }


@app.get("/polygon/options/{symbol}/debug")
async def polygon_options_debug(
    symbol: str,
    expiry_scope: str = Query("weekly"),
    horizon_mode: str = Query("1m"),
    option_side: str = Query("calls"),
    premium_mode: str = Query("mid"),
    manual_expiry: str | None = Query(None),
):
    scope = expiry_scope.strip().lower()
    horizon = horizon_mode.strip().lower()
    side = option_side.strip().lower()
    premium = premium_mode.strip().lower()

    underlying_price = await _get_cached_underlying_price(symbol)

    raw_contracts = await polygon_client.get_option_chain_snapshot(
        underlying=symbol,
        expiration_date=None,
        contract_type=None,
        limit=250,
    )

    normalized_contracts = []
    for contract in raw_contracts:
        if not _is_standard_contract(contract):
            continue

        normalized = _normalize_snapshot_contract(contract, premium)
        if normalized is None:
            continue

        normalized["underlyingPrice"] = underlying_price
        normalized["moneyness"] = _get_moneyness(
            underlying_price,
            _safe_float(normalized.get("strike")),
            normalized.get("optionSide"),
        )
        normalized_contracts.append(normalized)

    available_expiries = sorted(
        {contract["expiry"] for contract in normalized_contracts if contract.get("expiry")}
    )

    selected_expiry = _pick_expiry(
        available_expiries=available_expiries,
        expiry_scope=scope,
        horizon_mode=horizon,
        manual_expiry=manual_expiry,
    )

    filtered_contracts = normalized_contracts

    if scope != "all" and selected_expiry:
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("expiry") == selected_expiry
        ]

    if underlying_price is not None and underlying_price > 0:
        bounded_contracts = []
        for contract in filtered_contracts:
            strike = _safe_float(contract.get("strike"))
            if strike is None:
                continue

            distance_pct = abs(strike - underlying_price) / underlying_price
            if distance_pct <= 0.50:
                bounded_contracts.append(contract)

        if bounded_contracts:
            filtered_contracts = bounded_contracts

    if side == "calls":
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("optionSide") == "Call"
        ]
    elif side == "puts":
        filtered_contracts = [
            contract for contract in filtered_contracts if contract.get("optionSide") == "Put"
        ]

    resolved = _pick_best_candidate(filtered_contracts, underlying_price)

    if resolved:
        resolved["underlyingPrice"] = underlying_price
        resolved["moneyness"] = _get_moneyness(
            underlying_price,
            _safe_float(resolved.get("strike")),
            resolved.get("optionSide"),
        )

    preview = []
    sorted_candidates = sorted(
        filtered_contracts,
        key=lambda contract: _safe_float(contract.get("strike")) or 999999.0,
    )

    for contract in sorted_candidates[:25]:
        strike = _safe_float(contract.get("strike"))
        distance_pct = None
        if strike is not None and underlying_price is not None and underlying_price > 0:
            distance_pct = round(abs(strike - underlying_price) / underlying_price * 100, 4)

        preview.append(
            {
                "optionTicker": contract.get("optionTicker"),
                "optionSide": contract.get("optionSide"),
                "expiry": contract.get("expiry"),
                "strike": strike,
                "premium": _safe_float(contract.get("premium")),
                "returnPercent": contract.get("returnPercent"),
                "delta": contract.get("delta"),
                "moneyness": _get_moneyness(
                    underlying_price,
                    strike,
                    contract.get("optionSide"),
                ),
                "underlyingPrice": underlying_price,
                "distancePct": distance_pct,
            }
        )

    return {
        "symbol": symbol.upper(),
        "expiryScope": scope,
        "horizonMode": horizon,
        "optionSideRequest": side,
        "premiumMode": premium,
        "underlyingPrice": underlying_price,
        "rawContractsCount": len(raw_contracts),
        "normalizedContractsCount": len(normalized_contracts),
        "filteredContractsCount": len(filtered_contracts),
        "availableExpiries": available_expiries,
        "selectedExpiry": selected_expiry,
        "resolved": resolved,
        "preview": preview,
    }