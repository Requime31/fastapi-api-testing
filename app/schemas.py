# app/schemas.py

from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def password_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password must not consist of whitespace only")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):          # ← חדש
    access_token: str
    token_type: str = "bearer"


class ItemCreate(BaseModel):
    title: str
    description: str


class ItemResponse(BaseModel):
    id: int
    title: str
    description: str

    model_config = ConfigDict(from_attributes=True)