from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.deps import get_current_user
from app.schemas.presets import ScanPresetCreate, ScanPresetUpdate, ScanPresetOut
from app.services.preset_service import (
    create_preset,
    list_presets,
    update_preset,
    delete_preset,
)

router = APIRouter(prefix="/presets", tags=["presets"])


@router.post("", response_model=ScanPresetOut, status_code=status.HTTP_201_CREATED)
def create_scan_preset(
    payload: ScanPresetCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return create_preset(db=db, user_id=current_user.id, payload=payload)


@router.get("", response_model=list[ScanPresetOut])
def list_scan_presets(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return list_presets(db=db, user_id=current_user.id)


@router.put("/{preset_id}", response_model=ScanPresetOut)
def update_scan_preset(
    preset_id: int,
    payload: ScanPresetUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    preset = update_preset(db=db, user_id=current_user.id, preset_id=preset_id, payload=payload)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan_preset(
    preset_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ok = delete_preset(db=db, user_id=current_user.id, preset_id=preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found")
    return None