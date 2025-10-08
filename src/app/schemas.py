from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr


class Health(BaseModel):
    status: str = "ok"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str

    model_config = ConfigDict(from_attributes=True)
