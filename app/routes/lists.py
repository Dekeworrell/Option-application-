from __future__ import annotations

import asyncio
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.deps import get_current_user

from app.models.user import User
from app.models.list import List as Watchlist
from app.models.ticker import Ticker
from app.models.scan_result import ScanResult
from app.models.scan_preset import ScanPreset
from polygon import RESTClient
from app.core.config import settings

from app.schemas.lists import ListCreate, ListOut, ListUpdate
from app.schemas.tickers import TickerCreate, TickerOut
from app.schemas.scan import (
    ScanRunRequest,
    ScanRunResponse,
    ScanResultLatestOut,
    ScanResultHistoryOut,
    ScanHistoryRunSummaryOut,
)

from app.services.scan_service import run_polygon_scan_for_list
from app.services.preset_service import get_preset

from time import time
from copy import deepcopy


router = APIRouter(prefix="/lists", tags=["Lists"])
QUOTE_CACHE_TTL_SECONDS = 300
_quote_cache: dict[int, dict] = {}


def _get_list_owned(db: Session, *, list_id: int, user_id: int) -> Watchlist:
    lst = (
        db.query(Watchlist)
        .filter(Watchlist.id == list_id, Watchlist.user_id == user_id)
        .first()
    )
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    return lst


def _to_scan_result_out(sr: ScanResult, symbol: str) -> ScanResultHistoryOut:
    is_below = (
        sr.underlying_price is not None
        and sr.ma30 is not None
        and sr.underlying_price < sr.ma30
    )
    return ScanResultHistoryOut(
        id=sr.id,
        list_id=sr.list_id,
        ticker_id=sr.ticker_id,
        symbol=symbol,
        run_at=sr.run_at,
        underlying_price=sr.underlying_price,
        ma30=sr.ma30,
        option_type=sr.option_type,
        expiry=sr.expiry,
        strike=sr.strike,
        delta=sr.delta,
        premium=sr.premium,
        return_pct=sr.return_pct,
        status=sr.status,
        error=sr.error,
        raw_json=sr.raw_json if isinstance(sr.raw_json, dict) else None,
        is_below_ma30=is_below,
    )


async def _fetch_quotes_bulk(client: RESTClient, symbols: list[str]) -> dict[str, dict]:
    """
    Fetch quotes for all symbols in a single Polygon bulk snapshot call.
    Returns a dict keyed by symbol.
    """
    today = date.today()
    date_from = (today - timedelta(days=7)).isoformat()
    date_to = today.isoformat()

    results: dict[str, dict] = {}

    # Initialize all symbols with error state
    for symbol in symbols:
        results[symbol] = {
            "symbol": symbol,
            "last_price": None,
            "change": None,
            "change_percent": None,
            "updated_at": None,
            "status": "error",
            "error": "No data",
        }

    try:
        # Single bulk call for all tickers
        snapshots = await run_in_threadpool(
            client.get_snapshot_all_tickers,
            "stocks",
            tickers=symbols,
        )

        try:
            snapshot_list = list(snapshots) if snapshots is not None else []
        except Exception:
            snapshot_list = []

        for snapshot in snapshot_list:
            symbol = getattr(snapshot, "ticker", None)
            if not symbol or symbol not in results:
                continue

            day = getattr(snapshot, "day", None)
            prev_day = getattr(snapshot, "prev_day", None)

            close = None
            prev_close = None

            if day:
                close = getattr(day, "close", None) or getattr(day, "c", None)
            if prev_day:
                prev_close = getattr(prev_day, "close", None) or getattr(prev_day, "c", None)

            if close is None:
                last_trade = getattr(snapshot, "last_trade", None)
                if last_trade:
                    close = getattr(last_trade, "price", None) or getattr(last_trade, "p", None)

            last_price = float(close) if close is not None else None
            change = None
            change_percent = None

            if close is not None and prev_close not in (None, 0):
                change = float(close) - float(prev_close)
                change_percent = (float(close) - float(prev_close)) / float(prev_close) * 100

            updated_at = None
            if getattr(snapshot, "updated", None):
                updated_at = str(snapshot.updated)

            results[symbol] = {
                "symbol": symbol,
                "last_price": last_price,
                "change": change,
                "change_percent": change_percent,
                "updated_at": updated_at,
                "status": "ok" if last_price is not None else "error",
                "error": None if last_price is not None else "No price data",
            }

    except Exception as bulk_error:
        bulk_text = str(bulk_error)

        # Fallback: fetch daily bars for all symbols concurrently
        async def _fallback_single(symbol: str) -> tuple[str, dict]:
            try:
                aggs = await run_in_threadpool(
                    client.get_aggs,
                    symbol, 1, "day", date_from, date_to,
                    adjusted=True, sort="desc", limit=5,
                )
                bars = list(aggs or [])

                if bars:
                    latest_bar = bars[0]
                    prev_bar = bars[1] if len(bars) >= 2 else None

                    latest_close = getattr(latest_bar, "close", None) or getattr(latest_bar, "c", None)
                    last_price = float(latest_close) if latest_close is not None else None

                    prev_close = None
                    if prev_bar is not None:
                        prev_close = getattr(prev_bar, "close", None) or getattr(prev_bar, "c", None)

                    change = None
                    change_percent = None
                    if last_price is not None and prev_close not in (None, 0):
                        change = float(last_price) - float(prev_close)
                        change_percent = (float(last_price) - float(prev_close)) / float(prev_close) * 100

                    bar_ts = getattr(latest_bar, "timestamp", None) or getattr(latest_bar, "t", None)
                    updated_at = None
                    if bar_ts is not None:
                        try:
                            updated_at = datetime.fromtimestamp(bar_ts / 1000).isoformat()
                        except Exception:
                            updated_at = str(bar_ts)

                    return symbol, {
                        "symbol": symbol,
                        "last_price": last_price,
                        "change": change,
                        "change_percent": change_percent,
                        "updated_at": updated_at,
                        "status": "delayed",
                        "error": "Fallback daily data",
                    }
                else:
                    return symbol, {
                        "symbol": symbol,
                        "last_price": None,
                        "change": None,
                        "change_percent": None,
                        "updated_at": None,
                        "status": "error",
                        "error": "No data available",
                    }
            except Exception as e:
                return symbol, {
                    "symbol": symbol,
                    "last_price": None,
                    "change": None,
                    "change_percent": None,
                    "updated_at": None,
                    "status": "error",
                    "error": str(e),
                }

        # Run fallback concurrently in batches of 10
        fallback_results = []
        for i in range(0, len(symbols), 10):
            batch = symbols[i:i + 10]
            batch_results = await asyncio.gather(*[_fallback_single(s) for s in batch])
            fallback_results.extend(batch_results)
            if i + 10 < len(symbols):
                        await asyncio.sleep(2)

        for symbol, data in fallback_results:
            results[symbol] = data

    return results


# -------------------------------------------------
# Lists
# -------------------------------------------------

@router.post("", response_model=ListOut, summary="Create a list")
def create_list(
    payload: ListCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = payload.name.strip()
    lst = Watchlist(user_id=current_user.id, name=name, default_preset_id=None)
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return lst


@router.get("", response_model=list[ListOut], summary="Get my lists")
def get_lists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id)
        .order_by(Watchlist.id.asc())
        .all()
    )


@router.patch("/{list_id}", response_model=ListOut)
def update_list(
    list_id: int,
    payload: ListUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    watchlist = (
        db.query(Watchlist)
        .filter(Watchlist.id == list_id, Watchlist.user_id == current_user.id)
        .first()
    )
    if not watchlist:
        raise HTTPException(status_code=404, detail="List not found")

    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Watchlist name is required")

    duplicate = (
        db.query(Watchlist)
        .filter(
            Watchlist.user_id == current_user.id,
            Watchlist.name == new_name,
            Watchlist.id != list_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Watchlist name already exists")

    watchlist.name = new_name
    db.commit()
    db.refresh(watchlist)
    return watchlist


@router.delete("/{list_id}")
def delete_list(
    list_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    list_obj = (
        db.query(Watchlist)
        .filter(Watchlist.id == list_id, Watchlist.user_id == user.id)
        .first()
    )
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")
    db.delete(list_obj)
    db.commit()
    return {"message": "List deleted"}


@router.put("/{list_id}/default-preset/{preset_id}", response_model=ListOut)
def set_default_preset(
    list_id: int,
    preset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lst = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    preset = get_preset(db=db, user_id=current_user.id, preset_id=preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    lst.default_preset_id = preset.id
    db.commit()
    db.refresh(lst)
    return lst


@router.delete("/{list_id}/default-preset", response_model=ListOut)
def clear_default_preset(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lst = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    lst.default_preset_id = None
    db.commit()
    db.refresh(lst)
    return lst


@router.get("/{list_id}/default-preset")
def get_default_preset(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lst = (
        db.query(Watchlist)
        .filter(Watchlist.id == list_id, Watchlist.user_id == current_user.id)
        .first()
    )
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    if not lst.default_preset_id:
        return None
    return get_preset(db, current_user.id, lst.default_preset_id)


# -------------------------------------------------
# Tickers
# -------------------------------------------------

@router.post("/{list_id}/tickers", response_model=TickerOut, summary="Add ticker to list")
def add_ticker(
    list_id: int,
    payload: TickerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    symbol = payload.symbol.upper().strip()
    count = db.query(func.count(Ticker.id)).filter(Ticker.list_id == list_id).scalar() or 0
    if count >= 75:
        raise HTTPException(status_code=400, detail="Ticker limit reached (75)")
    exists = (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id, Ticker.symbol == symbol)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Ticker already exists in this list")
    t = Ticker(list_id=list_id, symbol=symbol)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.get("/{list_id}/tickers", response_model=list[TickerOut], summary="Get tickers in list")
def get_tickers(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    return (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )


# -------------------------------------------------
# Quotes — single bulk snapshot call
# -------------------------------------------------

@router.get("/{list_id}/quotes")
async def get_list_quotes(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_list_owned(db, list_id=list_id, user_id=current_user.id)

    now_ts = time()
    cached = _quote_cache.get(list_id)

    if cached and (now_ts - cached["timestamp"] < QUOTE_CACHE_TTL_SECONDS):
        return deepcopy(cached["data"])

    tickers = (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )

    if not tickers:
        return {"list_id": list_id, "count": 0, "quotes": []}

    client = RESTClient(settings.polygon_api_key)
    symbols = [t.symbol.upper() for t in tickers]

    quotes_by_symbol = await _fetch_quotes_bulk(client, symbols)

    # Return in same order as tickers
    results = [quotes_by_symbol[symbol] for symbol in symbols if symbol in quotes_by_symbol]

    response_data = {
        "list_id": list_id,
        "count": len(results),
        "quotes": results,
    }

    has_any_good_data = any(
        row["status"] in ("ok", "delayed") and row["last_price"] is not None
        for row in results
    )

    if has_any_good_data:
        _quote_cache[list_id] = {"timestamp": now_ts, "data": deepcopy(response_data)}
        return response_data

    if cached:
        stale_data = deepcopy(cached["data"])
        for row in stale_data.get("quotes", []):
            row["error"] = "Using cached data"
        return stale_data

    return response_data


# -------------------------------------------------
# Scan
# -------------------------------------------------

@router.post("/{list_id}/scan/run", response_model=ScanRunResponse, summary="Run scan for list")
async def run_scan(
    list_id: int,
    payload: ScanRunRequest,
    preset_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lst = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    effective_preset_id = preset_id if preset_id is not None else lst.default_preset_id

    if effective_preset_id is not None:
        preset = get_preset(db=db, user_id=current_user.id, preset_id=effective_preset_id)
        if not preset:
            raise HTTPException(status_code=404, detail="Preset not found")
        payload.option_type = preset.option_type
        payload.delta_target = preset.delta_target
        payload.use_rsi_filter = bool(preset.use_rsi_filter)
        payload.rsi_max = preset.rsi_max
        payload.use_ma30_filter = False

    tickers = (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )
    if not tickers:
        raise HTTPException(status_code=400, detail="List has no tickers to scan")

    run_at, rows = await run_polygon_scan_for_list(
        db,
        list_id=list_id,
        tickers=tickers,
        option_type=payload.option_type,
        delta_target=payload.delta_target,
        indicators=payload.indicators,
        trend_sma_length=payload.trend_sma_length,
        trend_type=payload.trend_type,
        use_ma30_filter=payload.use_ma30_filter,
        use_rsi_filter=payload.use_rsi_filter,
        rsi_length=payload.rsi_length,
        rsi_min=payload.rsi_min,
        rsi_max=payload.rsi_max,
    )

    error_count = len([row for row in rows if getattr(row, "status", "") != "ok"])
    return ScanRunResponse(
        ok=True,
        list_id=list_id,
        run_at=run_at,
        inserted=len(rows),
        errors=error_count,
        results=rows,
    )


@router.get("/{list_id}/scan/results/latest", response_model=list[ScanResultLatestOut])
def get_latest_scan_results(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)

    latest_run_at = (
        db.query(func.max(ScanResult.run_at))
        .filter(ScanResult.list_id == list_id)
        .scalar()
    )
    if latest_run_at is None:
        return []

    rows = (
        db.query(ScanResult, Ticker)
        .join(Ticker, Ticker.id == ScanResult.ticker_id)
        .filter(ScanResult.list_id == list_id, ScanResult.run_at == latest_run_at)
        .order_by(
            case((ScanResult.status == "error", 1), else_=0).asc(),
            ScanResult.return_pct.desc().nullslast(),
            Ticker.symbol.asc(),
        )
        .all()
    )

    out: list[ScanResultLatestOut] = []
    for sr, t in rows:
        is_below = (
            sr.underlying_price is not None
            and sr.ma30 is not None
            and sr.underlying_price < sr.ma30
        )
        out.append(ScanResultLatestOut(
            id=sr.id, list_id=sr.list_id, ticker_id=sr.ticker_id, symbol=t.symbol,
            run_at=sr.run_at, underlying_price=sr.underlying_price, ma30=sr.ma30,
            option_type=sr.option_type, expiry=sr.expiry, strike=sr.strike,
            delta=sr.delta, premium=sr.premium, return_pct=sr.return_pct,
            status=sr.status, error=sr.error,
            raw_json=sr.raw_json if isinstance(sr.raw_json, dict) else None,
            is_below_ma30=is_below,
        ))
    return out


@router.get("/{list_id}/scan/history/runs", response_model=list[ScanHistoryRunSummaryOut])
def get_scan_history_runs(
    list_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    limit = max(1, min(limit, 100))

    rows = (
        db.query(
            ScanResult.run_at.label("run_at"),
            func.count(ScanResult.id).label("total"),
            func.sum(case((ScanResult.status == "error", 0), else_=1)).label("ok"),
            func.sum(case((ScanResult.status == "error", 1), else_=0)).label("errors"),
        )
        .filter(ScanResult.list_id == list_id)
        .group_by(ScanResult.run_at)
        .order_by(ScanResult.run_at.desc())
        .limit(limit)
        .all()
    )

    return [
        ScanHistoryRunSummaryOut(
            run_at=row.run_at,
            total=int(row.total or 0),
            ok=int(row.ok or 0),
            errors=int(row.errors or 0),
        )
        for row in rows
    ]


@router.get("/{list_id}/scan/history/{run_at}", response_model=list[ScanResultHistoryOut])
def get_scan_history_for_run(
    list_id: int,
    run_at: datetime,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)

    rows = (
        db.query(ScanResult, Ticker)
        .join(Ticker, Ticker.id == ScanResult.ticker_id)
        .filter(ScanResult.list_id == list_id, ScanResult.run_at == run_at)
        .order_by(
            case((ScanResult.status == "error", 1), else_=0).asc(),
            ScanResult.return_pct.desc().nullslast(),
            Ticker.symbol.asc(),
        )
        .all()
    )

    return [_to_scan_result_out(sr, t.symbol) for sr, t in rows]
