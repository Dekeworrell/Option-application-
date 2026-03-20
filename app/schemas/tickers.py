from pydantic import BaseModel, Field, ConfigDict

class TickerCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)

class TickerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str