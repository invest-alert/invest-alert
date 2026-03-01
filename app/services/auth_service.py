import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    get_password_hash,
    hash_token,
    verify_password,
)
from app.crud import refresh_tokens as refresh_token_crud
from app.crud import users as user_crud
from app.models.user import User
from app.schemas.auth import TokenPairResponse


def normalize_email(email: str) -> str:
    return email.strip().lower()


def issue_token_pair(db: Session, user: User) -> TokenPairResponse:
    access_token = create_access_token(str(user.id))
    refresh_token, refresh_expires_at = create_refresh_token(str(user.id))
    refresh_token_crud.create_refresh_token(
        db,
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=refresh_expires_at,
    )
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


def register_user(db: Session, *, email: str, password: str) -> TokenPairResponse:
    normalized_email = normalize_email(email)
    if user_crud.get_user_by_email(db, normalized_email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = user_crud.create_user(
        db,
        email=normalized_email,
        password_hash=get_password_hash(password),
    )
    return issue_token_pair(db, user)


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    normalized_email = normalize_email(email)
    user = user_crud.get_user_by_email(db, normalized_email)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return user


def login_user(db: Session, *, email: str, password: str) -> TokenPairResponse:
    user = authenticate_user(db, email=email, password=password)
    return issue_token_pair(db, user)


def refresh_user_tokens(db: Session, *, refresh_token: str) -> TokenPairResponse:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )

    try:
        decoded = decode_refresh_token(refresh_token)
        if decoded.get("type") != "refresh":
            raise unauthorized
        subject = decoded.get("sub")
        if not subject:
            raise unauthorized
    except JWTError:
        raise unauthorized

    now = datetime.now(timezone.utc)
    stored_token = refresh_token_crud.get_active_refresh_token(
        db,
        token_hash=hash_token(refresh_token),
        now=now,
    )
    if stored_token is None:
        raise unauthorized

    user = user_crud.get_user_by_id(db, stored_token.user_id)
    if user is None:
        raise unauthorized

    refresh_token_crud.revoke_refresh_token(db, token=stored_token, revoked_at=now)
    return issue_token_pair(db, user)


def logout_user(db: Session, *, refresh_token: str) -> None:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    try:
        decoded = decode_refresh_token(refresh_token)
        if decoded.get("type") != "refresh":
            raise unauthorized
    except JWTError:
        raise unauthorized

    token = refresh_token_crud.get_unrevoked_refresh_token(
        db,
        token_hash=hash_token(refresh_token),
    )
    if token is None:
        raise unauthorized

    refresh_token_crud.revoke_refresh_token(
        db,
        token=token,
        revoked_at=datetime.now(timezone.utc),
    )


def get_current_user_from_token(db: Session, *, token: str) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        subject = payload.get("sub")
        if not subject:
            raise credentials_exception
        user_id = uuid.UUID(subject)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = user_crud.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception
    return user
