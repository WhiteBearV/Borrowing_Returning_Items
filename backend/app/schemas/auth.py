from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    full_name: str
    student_id: str
    email: EmailStr
    password: str
    major: str  # comp_eng / digital_design


class LoginRequest(BaseModel):
    identifier: str  # student_id, username, or email
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
