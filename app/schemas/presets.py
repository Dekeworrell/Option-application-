from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict


class ScanPresetBase(BaseModel):
    name: str
    option_type: Literal["call", "put"]
    delta_target: float
    use_rsi_filter: bool = False
    rsi_max: float = 0

    use_ma30_filter: Optional[bool] = None
    trend_sma_length: Optional[int] = None
    trend_type: Optional[str] = None
    rsi_length: Optional[int] = None
    rsi_min: Optional[float] = None


class ScanPresetCreate(ScanPresetBase):
    pass


class ScanPresetUpdate(ScanPresetBase):
    pass


class ScanPresetOut(ScanPresetBase):
    id: int
    user_id: int

    model_config = ConfigDict(from_attributes=True)
