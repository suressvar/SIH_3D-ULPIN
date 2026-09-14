from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppUser

bearer = HTTPBearer(auto_error=False)


@lru_cache
def jwks_client() -> PyJWKClient:
    url = get_settings().supabase_url.rstrip("/")
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", lifespan=300, timeout=5)


def verify_token(token: str) -> UUID:
    settings = get_settings()
    if not settings.supabase_url:
        raise HTTPException(503, "Supabase Auth is not configured")
    try:
        key = jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["ES256", "RS256"],
            audience=settings.jwt_audience,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        return UUID(claims["sub"])
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Authentication key service unavailable") from exc
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise HTTPException(
            401,
            "Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AppUser:
    if credentials is None:
        raise HTTPException(
            401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
        )
    subject = verify_token(credentials.credentials)
    user = db.get(AppUser, subject)
    if not user or not user.active:
        raise HTTPException(403, "No active project membership")
    return user


def roles(*allowed: str):
    def dependency(user: AppUser = Depends(current_user)):
        if user.role not in allowed:
            raise HTTPException(403, "Insufficient project role")
        return user

    return dependency
