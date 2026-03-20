# app/schemas/scan.py

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


# -------------------------
# Request: Run Scan
# -------------------------
class ScanRunRequest(BaseModel):
    option_type: str = Field(default="call", pattern="^(call|put)$")
    delta_target: float = Field(default=0.30, ge=0.01, le=0.99)
    use_ma30_filter: bool = True
    indicators: list[dict] = Field(default_factory=lambda: [{"type": "sma", "length": 30}])
    trend_sma_length: int = 30
    trend_type: str = Field(default="sma", pattern="^(sma|ema)$")
    use_rsi_filter: bool = False
    rsi_length: int = 14
    rsi_min: float = 0.0
    rsi_max: float = 100.0


# -------------------------
# Response: Scan Run Summary
# -------------------------
class ScanRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    list_id: int
    run_at: datetime
    inserted: int
    ok: int
    errors: int


# -------------------------
# Shared scan result output
# -------------------------
class ScanResultBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    list_id: int
    ticker_id: int
    symbol: str

    run_at: datetime
    underlying_price: Optional[float] = None

    # Keep internal DB column (hidden in API)
    ma30: Optional[float] = Field(default=None, exclude=True)

    option_type: Optional[str] = None
    expiry: Optional[date] = None
    strike: Optional[float] = None
    delta: Optional[float] = None
    premium: Optional[float] = None
    return_pct: Optional[float] = None

    status: str
    error: Optional[str] = None

    is_below_ma30: bool
    raw_json: Optional[dict] = None

    @computed_field
    @property
    def trend_value(self) -> Optional[float]:
        return self.ma30

    @computed_field
    @property
    def passes_ma30_filter(self) -> bool:
        if isinstance(self.raw_json, dict):
            if self.raw_json.get("use_ma30_filter") is False:
                return True

        if self.underlying_price is None or self.ma30 is None:
            return True

        if self.option_type == "call":
            return self.underlying_price >= self.ma30
        if self.option_type == "put":
            return self.underlying_price <= self.ma30

        return True

    @computed_field
    @property
    def passes_rsi_filter(self) -> bool:
        if isinstance(self.raw_json, dict):
            if self.raw_json.get("use_rsi_filter") is False:
                return True

        if self.error and "Blocked by RSI filter" in self.error:
            return False

        return True

    @computed_field
    @property
    def passes_all_filters(self) -> bool:
        return bool(self.passes_ma30_filter and self.passes_rsi_filter)

    @computed_field
    @property
    def filter_reason(self) -> Optional[str]:
        if not self.passes_ma30_filter:
            return "trend_filter_failed"
        if not self.passes_rsi_filter:
            return "rsi_filter_failed"
        return None

    @computed_field
    @property
    def recommended_action(self) -> Optional[str]:
        if self.filter_reason == "trend_filter_failed":
            return "consider_disabling_trend_filter_or_using_shorter_trend_length"
        if self.filter_reason == "rsi_filter_failed":
            return "consider_adjusting_rsi_thresholds_or_disabling_rsi_filter"
        return None


# -------------------------
# Response: Latest Scan Results
# -------------------------
class ScanResultLatestOut(ScanResultBaseOut):
    pass


# -------------------------
# Response: Scan History Row
# -------------------------
class ScanResultHistoryOut(ScanResultBaseOut):
    pass


# -------------------------
# Response: Scan Run History Summary
# -------------------------
class ScanHistoryRunSummaryOut(BaseModel):
    run_at: datetime
    total: int
    ok: int
    errors: int