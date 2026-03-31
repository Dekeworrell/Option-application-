from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.deps import get_current_user

from app.models.user import User
from app.models.list import List as Watchlist
from app.models.ticker import Ticker
from app.models.scan_result import ScanResult
from app.models.option_chain_cache import OptionChainCache

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


def _pick_best_expiry(expiries: list[str], scope: str) -> str | None:
    if not expiries:
        return None
    today = date.today()
    parsed = sorted(date.fromisoformat(x) for x in expiries if x)

    if scope == "weekly":
        fridays = [d for d in parsed if d >= today and d.weekday() == 4]
        if fridays:
            return fridays[0].isoformat()
        future = [d for d in parsed if d >= today]
        return future[0].isoformat() if future else None

    if scope == "monthly":
        # Third Friday of next month
        future = [d for d in parsed if d >= today]
        # Find expiries that are 3rd+ week out (21+ days)
        monthly = [d for d in future if (d - today).days >= 14]
        return monthly[0].isoformat() if monthly else (future[-1].isoformat() if future else None)

    if scope == "near":
        future = [d for d in parsed if d >= today]
        return future[0].isoformat() if future else None

    if scope == "far":
        future = [d for d in parsed if d >= today]
        return future[-1].isoformat() if future else None

    return None


def _resolve_best_contract(
    contracts: list[OptionChainCache],
    target_mode: str,
    target_delta: float,
    target_percent_otm: float,
    premium_mode: str,
) -> OptionChainCache | None:
    if not contracts:
        return None

    def get_premium(c: OptionChainCache) -> float | None:
        if premium_mode == "bid":
            return c.bid
        if premium_mode == "ask":
            return c.ask
        if premium_mode == "last":
            return c.last or c.prev_close
        if premium_mode == "mid":
            return c.mid or c.last or c.prev_close
        return c.mid or c.last or c.prev_close

    if target_mode == "delta":
        def sort_key(c: OptionChainCache):
            delta = c.delta or 0
            has_premium = 1 if get_premium(c) is not None else 2
            return (abs(delta - target_delta), has_premium)
    else:  # percent-otm
        def sort_key(c: OptionChainCache):
            pct = c.percent_otm or 0
            has_premium = 1 if get_premium(c) is not None else 2
            return (abs(pct - target_percent_otm), has_premium)

    return sorted(contracts, key=sort_key)[0]


# -------------------------------------------------
# Lists
# -------------------------------------------------

@router.post("", response_model=ListOut)
def create_list(payload: ListCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    lst = Watchlist(user_id=current_user.id, name=payload.name.strip(), default_preset_id=None)
    db.add(lst); db.commit(); db.refresh(lst)
    return lst


@router.get("", response_model=list[ListOut])
def get_lists(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Watchlist).filter(Watchlist.user_id == current_user.id).order_by(Watchlist.id.asc()).all()


@router.patch("/{list_id}", response_model=ListOut)
def update_list(list_id: int, payload: ListUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    watchlist = db.query(Watchlist).filter(Watchlist.id == list_id, Watchlist.user_id == current_user.id).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="List not found")
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Watchlist name is required")
    duplicate = db.query(Watchlist).filter(Watchlist.user_id == current_user.id, Watchlist.name == new_name, Watchlist.id != list_id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="Watchlist name already exists")
    watchlist.name = new_name
    db.commit(); db.refresh(watchlist)
    return watchlist


@router.delete("/{list_id}")
def delete_list(list_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    list_obj = db.query(Watchlist).filter(Watchlist.id == list_id, Watchlist.user_id == user.id).first()
    if not list_obj:
        raise HTTPException(status_code=404, detail="List not found")
    db.delete(list_obj); db.commit()
    return {"message": "List deleted"}


@router.put("/{list_id}/default-preset/{preset_id}", response_model=ListOut)
def set_default_preset(list_id: int, preset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    lst = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    preset = get_preset(db=db, user_id=current_user.id, preset_id=preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    lst.default_preset_id = preset.id; db.commit(); db.refresh(lst)
    return lst


@router.delete("/{list_id}/default-preset", response_model=ListOut)
def clear_default_preset(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    lst = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    lst.default_preset_id = None; db.commit(); db.refresh(lst)
    return lst


@router.get("/{list_id}/default-preset")
def get_default_preset(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    lst = db.query(Watchlist).filter(Watchlist.id == list_id, Watchlist.user_id == current_user.id).first()
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")
    if not lst.default_preset_id:
        return None
    return get_preset(db, current_user.id, lst.default_preset_id)


# -------------------------------------------------
# Tickers
# -------------------------------------------------

@router.post("/{list_id}/tickers", response_model=TickerOut)
def add_ticker(list_id: int, payload: TickerCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    symbol = payload.symbol.upper().strip()
    count = db.query(func.count(Ticker.id)).filter(Ticker.list_id == list_id).scalar() or 0
    if count >= 75:
        raise HTTPException(status_code=400, detail="Ticker limit reached (75)")
    exists = db.query(Ticker).filter(Ticker.list_id == list_id, Ticker.symbol == symbol).first()
    if exists:
        raise HTTPException(status_code=400, detail="Ticker already exists in this list")
    t = Ticker(list_id=list_id, symbol=symbol)
    db.add(t); db.commit(); db.refresh(t)
    return t


@router.get("/{list_id}/tickers", response_model=list[TickerOut])
def get_tickers(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    return db.query(Ticker).filter(Ticker.list_id == list_id).order_by(Ticker.symbol.asc()).all()


# -------------------------------------------------
# Quotes — served from option_chain_cache with filtering
# -------------------------------------------------

@router.get("/{list_id}/quotes")
def get_list_quotes(
    list_id: int,
    # Expiry controls
    expiry_scope: str = Query("weekly", description="weekly|monthly|near|far|manual"),
    manual_expiry: str | None = Query(None),
    # Side
    option_side: str = Query("calls", description="calls|puts|both"),
    # Target
    target_mode: str = Query("delta", description="delta|percent-otm"),
    target_delta: float = Query(0.30),
    target_percent_otm: float = Query(5.0),
    # Premium mode
    premium_mode: str = Query("mid", description="mid|bid|ask|last"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns best matching option contract per symbol based on user filters.
    All data served from option_chain_cache — no live API calls.
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

    # Fetch all cached contracts for these symbols in one query
    all_contracts = (
        db.query(OptionChainCache)
        .filter(OptionChainCache.symbol.in_(symbols))
        .all()
    )

    # Group by symbol
    by_symbol: dict[str, list[OptionChainCache]] = {}
    for c in all_contracts:
        by_symbol.setdefault(c.symbol, []).append(c)

    quotes = []
    for symbol in symbols:
        contracts = by_symbol.get(symbol, [])

        if not contracts:
            quotes.append({
                "symbol": symbol,
                "last_price": None,
                "updated_at": None,
                "status": "pending",
                "error": "Cache warming up...",
                "strike": None, "expiry": None, "option_side": None,
                "premium": None, "return_percent": None,
                "delta": None, "gamma": None, "theta": None, "vega": None,
                "implied_volatility": None, "open_interest": None,
                "moneyness": None, "percent_otm": None,
                "available_expiries": [],
            })
            continue

        underlying_price = contracts[0].underlying_price
        fetched_at = contracts[0].fetched_at

        # Get available expiries
        available_expiries = sorted(set(c.expiry for c in contracts if c.expiry))

        # Filter by side
        side_lower = option_side.lower()
        if side_lower == "calls":
            filtered = [c for c in contracts if c.option_side == "Call"]
        elif side_lower == "puts":
            filtered = [c for c in contracts if c.option_side == "Put"]
        else:
            filtered = contracts

        # Determine target expiry
        if expiry_scope == "manual" and manual_expiry:
            target_expiry = manual_expiry
        else:
            call_expiries = sorted(set(c.expiry for c in filtered if c.expiry))
            target_expiry = _pick_best_expiry(call_expiries, expiry_scope)

        # Filter to target expiry
        if target_expiry:
            expiry_filtered = [c for c in filtered if c.expiry == target_expiry]
        else:
            expiry_filtered = filtered

        # Pick best contract
        best = _resolve_best_contract(
            contracts=expiry_filtered,
            target_mode=target_mode,
            target_delta=target_delta,
            target_percent_otm=target_percent_otm,
            premium_mode=premium_mode,
        )

        def get_premium(c):
            if premium_mode == "bid": return c.bid
            if premium_mode == "ask": return c.ask
            if premium_mode == "last": return c.last or c.prev_close
            return c.mid or c.last or c.prev_close

        if best:
            premium = get_premium(best)
            return_pct = round((premium / best.strike) * 100, 4) if premium and best.strike else best.return_percent
            quotes.append({
                "symbol": symbol,
                "last_price": underlying_price,
                "updated_at": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ") if fetched_at else None,
                "status": "ok",
                "error": None,
                "strike": best.strike,
                "expiry": best.expiry,
                "option_side": best.option_side,
                "premium": premium,
                "return_percent": return_pct,
                "delta": best.delta,
                "gamma": best.gamma,
                "theta": best.theta,
                "vega": best.vega,
                "implied_volatility": best.implied_volatility,
                "open_interest": best.open_interest,
                "moneyness": best.moneyness,
                "percent_otm": best.percent_otm,
                "available_expiries": available_expiries,
            })
        else:
            quotes.append({
                "symbol": symbol,
                "last_price": underlying_price,
                "updated_at": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ") if fetched_at else None,
                "status": "ok",
                "error": None,
                "strike": None, "expiry": None, "option_side": None,
                "premium": None, "return_percent": None,
                "delta": None, "gamma": None, "theta": None, "vega": None,
                "implied_volatility": None, "open_interest": None,
                "moneyness": None, "percent_otm": None,
                "available_expiries": available_expiries,
            })

    return {"list_id": list_id, "count": len(quotes), "quotes": quotes}


# -------------------------------------------------
# Available expiries endpoint
# -------------------------------------------------

@router.get("/{list_id}/expiries")
def get_available_expiries(
    list_id: int,
    option_side: str = Query("calls"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns all available expiry dates for a watchlist."""
    _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    tickers = db.query(Ticker).filter(Ticker.list_id == list_id).all()
    symbols = [t.symbol.upper() for t in tickers]

    side_filter = "Call" if option_side.lower() == "calls" else "Put" if option_side.lower() == "puts" else None

    query = db.query(OptionChainCache.expiry).filter(OptionChainCache.symbol.in_(symbols))
    if side_filter:
        query = query.filter(OptionChainCache.option_side == side_filter)

    expiries = sorted(set(row[0] for row in query.distinct().all() if row[0]))
    return {"expiries": expiries}


# -------------------------------------------------
# Scan
# -------------------------------------------------

@router.post("/{list_id}/scan/run", response_model=ScanRunResponse)
async def run_scan(list_id: int, payload: ScanRunRequest, preset_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
    tickers = db.query(Ticker).filter(Ticker.list_id == list_id).order_by(Ticker.symbol.asc()).all()
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
    return ScanRunResponse(ok=True, list_id=list_id, run_at=run_at, inserted=len(rows), errors=error_count, results=rows)


@router.get("/{list_id}/scan/results/latest", response_model=list[ScanResultLatestOut])
def get_latest_scan_results(list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    latest_run_at = db.query(func.max(ScanResult.run_at)).filter(ScanResult.list_id == list_id).scalar()
    if latest_run_at is None:
        return []
    rows = (
        db.query(ScanResult, Ticker).join(Ticker, Ticker.id == ScanResult.ticker_id)
        .filter(ScanResult.list_id == list_id, ScanResult.run_at == latest_run_at)
        .order_by(case((ScanResult.status == "error", 1), else_=0).asc(), ScanResult.return_pct.desc().nullslast(), Ticker.symbol.asc())
        .all()
    )
    out = []
    for sr, t in rows:
        is_below = sr.underlying_price is not None and sr.ma30 is not None and sr.underlying_price < sr.ma30
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
def get_scan_history_runs(list_id: int, limit: int = 20, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    limit = max(1, min(limit, 100))
    rows = (
        db.query(ScanResult.run_at.label("run_at"), func.count(ScanResult.id).label("total"),
                 func.sum(case((ScanResult.status == "error", 0), else_=1)).label("ok"),
                 func.sum(case((ScanResult.status == "error", 1), else_=0)).label("errors"))
        .filter(ScanResult.list_id == list_id).group_by(ScanResult.run_at)
        .order_by(ScanResult.run_at.desc()).limit(limit).all()
    )
    return [ScanHistoryRunSummaryOut(run_at=r.run_at, total=int(r.total or 0), ok=int(r.ok or 0), errors=int(r.errors or 0)) for r in rows]


@router.get("/{list_id}/scan/history/{run_at}", response_model=list[ScanResultHistoryOut])
def get_scan_history_for_run(list_id: int, run_at: datetime, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _ = _get_list_owned(db, list_id=list_id, user_id=current_user.id)
    rows = (
        db.query(ScanResult, Ticker).join(Ticker, Ticker.id == ScanResult.ticker_id)
        .filter(ScanResult.list_id == list_id, ScanResult.run_at == run_at)
        .order_by(case((ScanResult.status == "error", 1), else_=0).asc(), ScanResult.return_pct.desc().nullslast(), Ticker.symbol.asc())
        .all()
    )
    return [_to_scan_result_out(sr, t.symbol) for sr, t in rows]
