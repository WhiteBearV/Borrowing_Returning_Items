from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    full_name: str
    student_id: str | None = None
    email: EmailStr
    password: str
    major: str | None = None  # comp_eng / digital_design


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    token: str
