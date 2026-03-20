from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models import ScanResult, Ticker
from app.services.polygon_client import PolygonClient
from app.services.indicator_engine import IndicatorRequest, compute_indicators


def compute_sma(closes: list[float], length: int) -> float | None:
    if len(closes) < length:
        return None
    window = closes[-length:]
    return sum(window) / length


def next_friday(from_date: Optional[date] = None) -> date:
    d = from_date or date.today()
    days_ahead = (4 - d.weekday()) % 7  # Mon=0 ... Fri=4
    return d + timedelta(days=days_ahead)


def select_contract_by_delta(
    contracts: list[dict],
    target_abs_delta: float,
) -> Optional[dict]:
    best: Optional[dict] = None
    best_abs = -1.0

    for c in contracts:
        greeks = c.get("greeks") or {}
        delta = greeks.get("delta")
        if delta is None:
            continue

        abs_d = abs(float(delta))
        if abs_d <= target_abs_delta and abs_d > best_abs:
            best = c
            best_abs = abs_d

    return best


def extract_premium_from_snapshot(option_snapshot: dict) -> Optional[float]:
    result = option_snapshot.get("results") or {}

    last_quote = result.get("last_quote") or {}
    bid = last_quote.get("bid")
    ask = last_quote.get("ask")
    if bid is not None and ask is not None:
        bid_f = float(bid)
        ask_f = float(ask)
        if ask_f > 0:
            return (bid_f + ask_f) / 2.0

    last_trade = result.get("last_trade") or {}
    price = last_trade.get("price")
    if price is not None:
        return float(price)

    return None

async def get_best_premium(
    polygon: PolygonClient,
    symbol: str,
    option_ticker: str,
) -> tuple[Optional[float], str]:
    """
    403-safe pricing:
    1) snapshot (quote/trade midpoint)
    2) last minute close (may 403 or None)
    3) prev close agg
    """
    snap = await polygon.get_option_contract_snapshot(symbol, option_ticker)
    premium = extract_premium_from_snapshot(snap)
    if premium is not None:
        return float(premium), "snapshot_quote_trade"

    # Try minute close (may 403). If blocked/unavailable, fall back.
    try:
        premium = await polygon.get_option_last_minute_close(option_ticker)
        if premium is not None:
            return float(premium), "last_minute_close"
    except Exception:
        pass

    premium = await polygon.get_option_prev_close(option_ticker)
    if premium is not None:
        return float(premium), "agg_prev_close"

    return None, "none"

def _extract_closes_from_daily_bars(daily_bars: list) -> list[float]:
    closes: list[float] = []
    for b in daily_bars:
        try:
            c = getattr(b, "c", None)
            if c is None and isinstance(b, dict):
                c = b.get("c")
            if c is None:
                continue
            closes.append(float(c))
        except Exception:
            continue
    return closes


async def run_polygon_scan_for_list(
    db: Session,
    *,
    list_id: int,
    tickers: Sequence[Ticker],
    option_type: str = "call",
    delta_target: float = 0.30,
    indicators: Optional[list[dict]] = None,
    trend_sma_length: int = 30,
    trend_type: str = "sma",
    use_rsi_filter: bool = False,
    rsi_length: int = 14,
    rsi_min: float = 0.0,
    rsi_max: float = 100.0,
    use_ma30_filter: bool = True,
) -> Tuple[datetime, list[ScanResult]]:
    option_type = option_type.lower().strip()
    if option_type not in {"call", "put"}:
        raise ValueError("option_type must be 'call' or 'put'")

    run_at = datetime.utcnow().replace(microsecond=0)
    expiry = next_friday()

    polygon = PolygonClient()
    results: list[ScanResult] = []

    for t in tickers:
        symbol = (t.symbol or "").upper().strip()

        try:
    
            # 1) underlying price (prev close)
            prev = await polygon.get_prev_close(symbol)

            underlying_price = None

            if isinstance(prev, (int, float)):
                underlying_price = float(prev)

            elif isinstance(prev, dict):
                c = prev.get("close")
                if c is not None:
                    underlying_price = float(c)

            # 1b) Indicators (modular + forced for filters)

            indicator_reqs: list[IndicatorRequest] = []

            # Add explicit indicators from request
            if indicators:
                for it in indicators:
                    try:
                        indicator_reqs.append(
                            IndicatorRequest(
                                type=str(it.get("type", "")).lower().strip(),
                                length=int(it.get("length", 0)),
                            )
                        )
                    except Exception:
                        continue

            # FORCE required indicators for enabled filters
            if use_ma30_filter:
                indicator_reqs.append(
                    IndicatorRequest(type="sma", length=int(trend_sma_length))
                )

            if use_rsi_filter:
                indicator_reqs.append(
                    IndicatorRequest(type="rsi", length=int(rsi_length))
                )

            # De-duplicate (type + length)
            seen = set()
            deduped: list[IndicatorRequest] = []
            for r in indicator_reqs:
                key = (r.type, r.length)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)

            if not deduped:
                deduped = [IndicatorRequest(type="sma", length=30)]

            indicators_out = await compute_indicators(
                polygon,
                symbol,
                indicators=deduped,
            )

            # Extract MA value safely (int OR str key)
            payload_trend_type = (trend_type or "sma").lower().strip()
            trend_bucket = indicators_out.get(payload_trend_type, {}) or {}

            ma30 = trend_bucket.get(trend_sma_length)
            if ma30 is None:
                ma30 = trend_bucket.get(str(trend_sma_length))

            # RSI filter (optional)
            if use_rsi_filter:
                rsi_val = indicators_out.get("rsi", {}).get(str(rsi_length))
                if rsi_val is None or rsi_val < rsi_min or rsi_val > rsi_max:
                    raw = {
                        "symbol": symbol,
                        "use_ma30_filter": use_ma30_filter,
                        "use_rsi_filter": use_rsi_filter,
                        "run_at": run_at.isoformat(),
                        "expiry": expiry.isoformat(),
                        "error": "Blocked by RSI filter",
                        "indicators": indicators_out,
                        "underlying_price": underlying_price,
                        "option_type": option_type,
                        "rsi_length": rsi_length,
                        "rsi_min": rsi_min,
                        "rsi_max": rsi_max,
                        "rsi_value": rsi_val,
                    }
                    results.append(
                        ScanResult(
                            list_id=list_id,
                            ticker_id=t.id,
                            run_at=run_at,
                            underlying_price=underlying_price,
                            ma30=ma30,
                            option_type=option_type,
                            expiry=expiry,
                            strike=None,
                            delta=None,
                            premium=None,
                            return_pct=None,
                            status="error",
                            error="Blocked by RSI filter",
                            raw_json=raw,
                        )
                    )
                    continue

            # 2) option chain snapshot for expiry + type
            contracts = await polygon.get_option_chain_snapshot(
                underlying=symbol,
                expiration_date=expiry.isoformat(),
                contract_type=option_type,
            )

            best = select_contract_by_delta(contracts, delta_target)

            # 3) OPTIONAL MA30 filter
            if use_ma30_filter and ma30 is not None and underlying_price is not None:
                blocked = (
                    (option_type == "call" and underlying_price < ma30)
                    or (option_type == "put" and underlying_price > ma30)
                )
                if blocked:
                    raw = {
                        "symbol": symbol,
                        "use_ma30_filter": use_ma30_filter,
                        "run_at": run_at.isoformat(),
                        "expiry": expiry.isoformat(),
                        "error": "Blocked by MA30 filter",
                        "indicators": indicators_out,
                        "underlying_price": underlying_price,
                        "option_type": option_type,
                    }
                    results.append(
                        ScanResult(
                            list_id=list_id,
                            ticker_id=t.id,
                            run_at=run_at,
                            underlying_price=underlying_price,
                            ma30=ma30,
                            option_type=option_type,
                            expiry=expiry,
                            strike=None,
                            delta=None,
                            premium=None,
                            return_pct=None,
                            status="error",
                            error="Blocked by MA30 filter",
                            raw_json=raw,
                        )
                    )
                    continue

            if not best:
                raw = {
                    "symbol": symbol,
                    "use_ma30_filter": use_ma30_filter,
                    "error": "No contract matched delta filter",
                    "count": len(contracts),
                    "indicators": indicators_out,
                }
                results.append(
                    ScanResult(
                        list_id=list_id,
                        ticker_id=t.id,
                        run_at=run_at,
                        underlying_price=underlying_price,
                        ma30=ma30,
                        option_type=option_type,
                        expiry=expiry,
                        strike=None,
                        delta=None,
                        premium=None,
                        return_pct=None,
                        status="error",
                        error="No contract matched delta filter",
                        raw_json=raw,
                    )
                )
                continue

            details = best.get("details") or {}
            greeks = best.get("greeks") or {}

            option_ticker = details.get("ticker")
            strike = details.get("strike_price")
            delta = greeks.get("delta")

            if not option_ticker or strike is None or delta is None:
                raw = {
                    "symbol": symbol,
                    "use_ma30_filter": use_ma30_filter,
                    "error": "Missing ticker/strike/delta",
                    "best": best,
                    "indicators": indicators_out,
                }
                results.append(
                    ScanResult(
                        list_id=list_id,
                        ticker_id=t.id,
                        run_at=run_at,
                        underlying_price=underlying_price,
                        ma30=ma30,
                        option_type=option_type,
                        expiry=expiry,
                        strike=None,
                        delta=None,
                        premium=None,
                        return_pct=None,
                        status="error",
                        error="Missing ticker/strike/delta",
                        raw_json=raw,
                    )
                )
                continue

            strike_f = float(strike)
            delta_f = float(delta)

            premium, pricing_source = await get_best_premium(polygon, symbol, option_ticker)
            if premium is None or strike_f <= 0:
                raw = {
                    "symbol": symbol,
                    "use_ma30_filter": use_ma30_filter,
                    "error": "No premium available",
                    "option_ticker": option_ticker,
                    "pricing_source": pricing_source,
                    "best": best,
                    "indicators": indicators_out,
                }
                results.append(
                    ScanResult(
                        list_id=list_id,
                        ticker_id=t.id,
                        run_at=run_at,
                        underlying_price=underlying_price,
                        ma30=ma30,
                        option_type=option_type,
                        expiry=expiry,
                        strike=strike_f,
                        delta=delta_f,
                        premium=None,
                        return_pct=None,
                        status="error",
                        error="No premium available",
                        raw_json=raw,
                    )
                )
                continue

            return_pct = float(premium) / strike_f

            raw = {
                "symbol": symbol,
                "use_ma30_filter": use_ma30_filter,
                "run_at": run_at.isoformat(),
                "expiry": expiry.isoformat(),
                "pricing_source": pricing_source,
                "selected": {
                    "option_ticker": option_ticker,
                    "strike": strike_f,
                    "delta": delta_f,
                    "premium": float(premium),
                    "return_pct": return_pct,
                },
                "indicators": indicators_out,
                "best_raw": best,
            }

            results.append(
                ScanResult(
                    list_id=list_id,
                    ticker_id=t.id,
                    run_at=run_at,
                    underlying_price=underlying_price,
                    ma30=ma30,
                    option_type=option_type,
                    expiry=expiry,
                    strike=strike_f,
                    delta=delta_f,
                    premium=float(premium),
                    return_pct=return_pct,
                    status="ok",
                    error=None,
                    raw_json=raw,
                )
            )

        except Exception as e:
            raw = {"symbol": symbol, "error": str(e)}
            results.append(
                ScanResult(
                    list_id=list_id,
                    ticker_id=t.id,
                    run_at=run_at,
                    underlying_price=None,
                    ma30=None,
                    option_type=option_type,
                    expiry=expiry,
                    strike=None,
                    delta=None,
                    premium=None,
                    return_pct=None,
                    status="error",
                    error=str(e),
                    raw_json=raw,
                )
            )

    db.add_all(results)
    db.commit()

    for r in results:
        db.refresh(r)

    return run_at, results