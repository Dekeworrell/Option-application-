from pydantic import BaseModel


class ListBase(BaseModel):
    name: str


class ListCreate(ListBase):
    pass


class ListUpdate(ListBase):
    pass


class ListOut(ListBase):
    id: int
    user_id: int

    class Config:
        from_attributes = True