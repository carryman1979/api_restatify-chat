from fastapi import APIRouter
from pydantic import BaseModel, EmailStr


router = APIRouter()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    mfa_required: bool = True


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    # Placeholder implementation for implementation start.
    # Full MFA flow and secure token issuance come next.
    return LoginResponse(
        access_token=f"dev-access-{payload.email}",
        refresh_token=f"dev-refresh-{payload.email}",
    )
