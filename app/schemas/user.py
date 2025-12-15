from typing import List, Optional

from pydantic import BaseModel, EmailStr

from app.schemas.auth import UserBase


class UserResponse(UserBase):
    id: int
    is_superuser: bool
    
    class Config:
        from_attributes = True


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class UserInDB(UserResponse):
    hashed_password: str