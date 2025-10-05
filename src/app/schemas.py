from __future__ import annotations
from pydantic import BaseModel, EmailStr

class Health(BaseModel):
    status: str = "ok"

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str

class UserRead(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    class Config:
        from_attributes = True
