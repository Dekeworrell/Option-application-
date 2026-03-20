from sqlalchemy.orm import Session

from app.models.scan_preset import ScanPreset


def create_preset(db: Session, user_id: int, payload):
    preset = ScanPreset(
        user_id=user_id,
        name=payload.name,
        option_type=payload.option_type,
        delta_target=payload.delta_target,
        use_rsi_filter=payload.use_rsi_filter,
        rsi_max=payload.rsi_max,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


def list_presets(db: Session, user_id: int):
    return (
        db.query(ScanPreset)
        .filter(ScanPreset.user_id == user_id)
        .order_by(ScanPreset.id.desc())
        .all()
    )


def get_preset(db: Session, user_id: int, preset_id: int):
    return (
        db.query(ScanPreset)
        .filter(ScanPreset.id == preset_id, ScanPreset.user_id == user_id)
        .first()
    )


def update_preset(db: Session, user_id: int, preset_id: int, payload):
    preset = get_preset(db, user_id, preset_id)
    if not preset:
        return None

    preset.name = payload.name
    preset.option_type = payload.option_type
    preset.delta_target = payload.delta_target
    preset.use_rsi_filter = payload.use_rsi_filter
    preset.rsi_max = payload.rsi_max

    db.commit()
    db.refresh(preset)
    return preset


def delete_preset(db: Session, user_id: int, preset_id: int):
    preset = get_preset(db, user_id, preset_id)
    if not preset:
        return None

    db.delete(preset)
    db.commit()
    return preset
