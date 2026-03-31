from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.deps import get_current_user

from app.models.user import User
from app.models.list import List as Watchlist
from app.models.ticker import Ticker
from app.models.scan_result import ScanResult
from app.models.market_cache import MarketCache

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


router = APIRouter(prefix="/lists", tags=["Lists"])


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
        id=sr.id, list_id=sr.list_id, ticker_id=sr.ticker_id, symbol=symbol,
        run_at=sr.run_at, underlying_price=sr.underlying_price, ma30=sr.ma30,
        option_type=sr.option_type, expiry=sr.expiry, strike=sr.strike,
        delta=sr.delta, premium=sr.premium, return_pct=sr.return_pct,
        status=sr.status, error=sr.error,
        raw_json=sr.raw_json if isinstance(sr.raw_json, dict) else None,
        is_below_ma30=is_below,
    )


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
# Quotes — served instantly from market_cache table
# -------------------------------------------------

@router.get("/{list_id}/quotes")
def get_list_quotes(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns pre-fetched market data from the cache table.
    Data is refreshed by the background scheduler every 60 seconds.
    Response is instant — no live Polygon calls.
    """
    _get_list_owned(db, list_id=list_id, user_id=current_user.id)

    tickers = (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )

    if not tickers:
        return {"list_id": list_id, "count": 0, "quotes": []}

    symbols = [t.symbol.upper() for t in tickers]

    # Fetch all cache rows for these symbols in one DB query
    cache_rows = (
        db.query(MarketCache)
        .filter(MarketCache.symbol.in_(symbols))
        .all()
    )
    cache_by_symbol = {row.symbol: row for row in cache_rows}

    quotes = []
    for symbol in symbols:
        row = cache_by_symbol.get(symbol)

        if row and row.underlying_price is not None:
            quotes.append({
                "symbol": symbol,
                "last_price": row.underlying_price,
                "change": None,
                "change_percent": None,
                "updated_at": row.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.fetched_at else None,
                "status": "ok",
                "error": None,
                # Option data
                "strike": row.strike,
                "expiry": row.expiry,
                "option_side": row.option_side,
                "premium": row.premium,
                "return_percent": row.return_percent,
                "delta": row.delta,
                "gamma": row.gamma,
                "theta": row.theta,
                "vega": row.vega,
                "moneyness": row.moneyness,
                "available_expiries": row.available_expiries or [],
            })
        else:
            # Not in cache yet — scheduler hasn't fetched it yet
            quotes.append({
                "symbol": symbol,
                "last_price": None,
                "change": None,
                "change_percent": None,
                "updated_at": None,
                "status": "pending",
                "error": "Awaiting first cache refresh",
                "strike": None,
                "expiry": None,
                "option_side": None,
                "premium": None,
                "return_percent": None,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None,
                "moneyness": None,
                "available_expiries": [],
            })

    return {"list_id": list_id, "count": len(quotes), "quotes": quotes}


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
        db, list_id=list_id, tickers=tickers,
        option_type=payload.option_type, delta_target=payload.delta_target,
        indicators=payload.indicators, trend_sma_length=payload.trend_sma_length,
        trend_type=payload.trend_type, use_ma30_filter=payload.use_ma30_filter,
        use_rsi_filter=payload.use_rsi_filter, rsi_length=payload.rsi_length,
        rsi_min=payload.rsi_min, rsi_max=payload.rsi_max,
    )

    error_count = len([r for r in rows if getattr(r, "status", "") != "ok"])
    return ScanRunResponse(
        ok=True, list_id=list_id, run_at=run_at,
        inserted=len(rows), errors=error_count, results=rows,
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

    out = []
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
            run_at=r.run_at, total=int(r.total or 0),
            ok=int(r.ok or 0), errors=int(r.errors or 0),
        )
        for r in rows
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
