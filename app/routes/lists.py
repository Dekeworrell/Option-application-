from __future__ import annotations

from datetime import datetime

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
QUOTE_CACHE_TTL_SECONDS = 60
_quote_cache: dict[int, dict] = {}


# -------------------------------------------------
# Helpers
# -------------------------------------------------

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

    lst = Watchlist(
        user_id=current_user.id,
        name=name,
        default_preset_id=None,
    )
    db.add(lst)
    db.commit()
    db.refresh(lst)

    return lst


@router.get("", response_model=list[ListOut], summary="Get my lists")
def get_lists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lists = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id)
        .order_by(Watchlist.id.asc())
        .all()
    )
    return lists


@router.put(
    "/{list_id}/default-preset/{preset_id}",
    response_model=ListOut,
    summary="Set default preset for list",
)
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


@router.delete(
    "/{list_id}/default-preset",
    response_model=ListOut,
    summary="Clear default preset for list",
)
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

    preset = get_preset(db, current_user.id, lst.default_preset_id)
    return preset



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

    tickers = (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )
    return tickers


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

@router.get(
    "/{list_id}/scan/results/latest",
    response_model=list[ScanResultLatestOut],
    summary="Get latest scan results for list",
)
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
        .filter(
            ScanResult.list_id == list_id,
            ScanResult.run_at == latest_run_at,
        )
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

        out.append(
            ScanResultLatestOut(
                id=sr.id,
                list_id=sr.list_id,
                ticker_id=sr.ticker_id,
                symbol=t.symbol,
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
        )

    return out


@router.get(
    "/{list_id}/scan/history/runs",
    response_model=list[ScanHistoryRunSummaryOut],
    summary="Get scan run history summaries for list",
)
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


@router.get(
    "/{list_id}/scan/history/{run_at}",
    response_model=list[ScanResultHistoryOut],
    summary="Get scan results for a specific run timestamp",
)
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
        .filter(
            ScanResult.list_id == list_id,
            ScanResult.run_at == run_at,
        )
        .order_by(
            case((ScanResult.status == "error", 1), else_=0).asc(),
            ScanResult.return_pct.desc().nullslast(),
            Ticker.symbol.asc(),
        )
        .all()
    )

    return [_to_scan_result_out(sr, t.symbol) for sr, t in rows]

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

    preset = get_preset(db, current_user.id, lst.default_preset_id)
    return preset

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

    client = RESTClient(settings.polygon_api_key)
    results = []

    for ticker in tickers:
        symbol = ticker.symbol.upper()

        try:
            last_price = None
            change = None
            change_percent = None
            updated_at = None
            status = "ok"
            error = None

            try:
                snapshot = await run_in_threadpool(
                    client.get_snapshot_ticker,
                    "stocks",
                    symbol,
                )

                if snapshot and getattr(snapshot, "day", None):
                    day = snapshot.day
                    prev_close = getattr(day, "prev_close", None)
                    close = getattr(day, "close", None)

                    if close is not None:
                        last_price = float(close)

                    if close is not None and prev_close not in (None, 0):
                        change = float(close) - float(prev_close)
                        change_percent = (
                            (float(close) - float(prev_close)) / float(prev_close)
                        ) * 100

                if snapshot and getattr(snapshot, "updated", None):
                    updated_at = str(snapshot.updated)

            except Exception as snapshot_error:
                snapshot_text = str(snapshot_error)

                if "429" in snapshot_text:
                    status = "error"
                    error = "Rate limited"
                elif "NOT_AUTHORIZED" in snapshot_text or "not entitled" in snapshot_text.lower():
                    try:
                        aggs = await run_in_threadpool(
                            client.get_aggs,
                            symbol,
                            1,
                            "day",
                            "2026-03-13",
                            "2026-03-14",
                            adjusted=True,
                            sort="desc",
                            limit=2,
                        )

                        bars = list(aggs or [])

                        if bars:
                            latest_bar = bars[-1]
                            prev_bar = bars[-2] if len(bars) >= 2 else None

                            latest_close = getattr(latest_bar, "close", None)
                            if latest_close is None:
                                latest_close = getattr(latest_bar, "c", None)

                            if latest_close is not None:
                                last_price = float(latest_close)

                            prev_close = None
                            if prev_bar is not None:
                                prev_close = getattr(prev_bar, "close", None)
                                if prev_close is None:
                                    prev_close = getattr(prev_bar, "c", None)

                            if last_price is not None and prev_close not in (None, 0):
                                change = float(last_price) - float(prev_close)
                                change_percent = (
                                    (float(last_price) - float(prev_close)) / float(prev_close)
                                ) * 100

                            bar_ts = getattr(latest_bar, "timestamp", None)
                            if bar_ts is None:
                                bar_ts = getattr(latest_bar, "t", None)

                            if bar_ts is not None:
                                try:
                                    updated_at = datetime.fromtimestamp(bar_ts / 1000).isoformat()
                                except Exception:
                                    updated_at = str(bar_ts)

                            status = "delayed"
                            error = "Fallback daily data"
                        else:
                            status = "error"
                            error = "No fallback quote data available"
                    except Exception as agg_error:
                        agg_text = str(agg_error)
                        if "429" in agg_text:
                            status = "error"
                            error = "Rate limited"
                        else:
                            status = "error"
                            error = agg_text
                else:
                    status = "error"
                    error = snapshot_text

            results.append(
                {
                    "symbol": symbol,
                    "last_price": last_price,
                    "change": change,
                    "change_percent": change_percent,
                    "updated_at": updated_at,
                    "status": status,
                    "error": error,
                }
            )

        except Exception as e:
            results.append(
                {
                    "symbol": symbol,
                    "last_price": None,
                    "change": None,
                    "change_percent": None,
                    "updated_at": None,
                    "status": "error",
                    "error": str(e),
                }
            )

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
        _quote_cache[list_id] = {
            "timestamp": now_ts,
            "data": deepcopy(response_data),
        }
        return response_data

    if cached:
        stale_data = deepcopy(cached["data"])
        for row in stale_data.get("quotes", []):
            if row.get("status") == "ok":
                row["status"] = "cached"
                row["error"] = "Using cached data"
            elif row.get("status") == "delayed":
                row["error"] = "Using cached fallback data"
            else:
                row["error"] = "Using cached data"
        return stale_data

    return response_data
