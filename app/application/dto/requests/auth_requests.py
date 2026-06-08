"""Auth request DTOs."""

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False
