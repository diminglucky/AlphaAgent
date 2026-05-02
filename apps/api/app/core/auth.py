"""API key authentication and role-based access control."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from typing import Optional

from apps.api.app.core.config import get_settings
from libs.quant_core.enums import UserRole


class AuthenticatedUser:
    def __init__(self, api_key: str, role: UserRole) -> None:
        self.api_key = api_key
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_trader(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.TRADER)


def _resolve_role(api_key: str) -> Optional[UserRole]:
    settings = get_settings()
    if api_key == settings.admin_api_key:
        return UserRole.ADMIN
    if api_key == settings.trader_api_key:
        return UserRole.TRADER
    if api_key == settings.viewer_api_key:
        return UserRole.VIEWER
    return None


def get_current_user(x_api_key: Optional[str] = Header(default=None)) -> AuthenticatedUser:
    settings = get_settings()
    if not settings.auth_enabled:
        return AuthenticatedUser(api_key="anonymous", role=UserRole.ADMIN)

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_API_KEY", "message": "X-Api-Key header is required"},
        )

    role = _resolve_role(x_api_key)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INVALID_API_KEY", "message": "Invalid or expired API key"},
        )

    return AuthenticatedUser(api_key=x_api_key, role=role)


def require_trader(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not user.is_trader:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_ROLE", "message": "Trader or Admin role required"},
        )
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INSUFFICIENT_ROLE", "message": "Admin role required"},
        )
    return user
