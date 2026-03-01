from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.responses import success_response
from app.models.user import User
from app.schemas.auth import (
    AuthLoginRequest,
    AuthRegisterRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenPairResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: AuthRegisterRequest, db: Session = Depends(get_db)):
    token_pair = auth_service.register_user(db, email=payload.email, password=payload.password)
    return success_response(data=token_pair, message="User registered successfully")


@router.post("/login")
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)):
    token_pair = auth_service.login_user(db, email=payload.email, password=payload.password)
    return success_response(data=token_pair, message="Login successful")


@router.post("/token", response_model=TokenPairResponse)
def token_login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenPairResponse:
    # Swagger OAuth2 popup sends username/password as form-data.
    return auth_service.login_user(db, email=form_data.username, password=form_data.password)


@router.post("/refresh")
def refresh_tokens(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_pair = auth_service.refresh_user_tokens(db, refresh_token=payload.refresh_token)
    return success_response(data=token_pair, message="Token refreshed successfully")


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    auth_service.logout_user(db, refresh_token=payload.refresh_token)
    return success_response(message="Logout successful")


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return success_response(data=current_user, message="User profile fetched successfully")
