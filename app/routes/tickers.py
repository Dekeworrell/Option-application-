from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.deps import get_current_user
from app.models.user import User
from app.models.list import List as ListModel
from app.models.ticker import Ticker
from app.schemas.tickers import TickerCreate, TickerOut

router = APIRouter(prefix="/lists/{list_id}/tickers", tags=["tickers"])

MAX_TICKERS_PER_LIST = 75


def _get_user_list(db: Session, user_id: int, list_id: int) -> ListModel:
    lst = (
        db.query(ListModel)
        .filter(ListModel.id == list_id, ListModel.user_id == user_id)
        .first()
    )

    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    return lst


@router.get("", response_model=list[TickerOut])
def get_tickers(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_list(db, current_user.id, list_id)

    return (
        db.query(Ticker)
        .filter(Ticker.list_id == list_id)
        .order_by(Ticker.symbol.asc())
        .all()
    )


@router.post("", response_model=TickerOut, status_code=201)
def add_ticker(
    list_id: int,
    payload: TickerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_list(db, current_user.id, list_id)

    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    # enforce 75 ticker limit per list
    count = db.query(Ticker).filter(Ticker.list_id == list_id).count()
    if count >= MAX_TICKERS_PER_LIST:
        raise HTTPException(status_code=400, detail=f"Max {MAX_TICKERS_PER_LIST} tickers per list")

    existing = db.query(Ticker).filter(Ticker.list_id == list_id, Ticker.symbol == symbol).first()
    if existing:
        return existing

    t = Ticker(list_id=list_id, symbol=symbol)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

@router.delete("/{ticker_id}")
def delete_ticker(
    ticker_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticker = (
        db.query(Ticker)
        .join(ListModel, Ticker.list_id == ListModel.id)
        .filter(
            Ticker.id == ticker_id,
            ListModel.user_id == current_user.id,
        )
        .first()
    )

    if not ticker:
        raise HTTPException(status_code=404, detail="Ticker not found")

    db.delete(ticker)
    db.commit()

    return {"message": "Ticker deleted"}