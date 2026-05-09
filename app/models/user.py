from sqlmodel import SQLModel, Field
from typing import Optional
from pydantic import EmailStr, field_validator

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str
    password: str

class UserRequest(SQLModel):
    email: EmailStr
    password: str

    @field_validator("password")
    def password_must_be_strong(cls, v):
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v