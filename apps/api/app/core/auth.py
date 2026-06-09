"""API key authentication and role-based access control."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from typing import Optional

from enum import Enum

from apps.api.app.core.config import get_settings


class UserRole(str, Enum):
    """用户角色（内联定义，避免依赖 legacy libs.quant_core）"""
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"


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
    if settings.admin_api_key and api_key == settings.admin_api_key:
        return UserRole.ADMIN
    if settings.trader_api_key and api_key == settings.trader_api_key:
        return UserRole.TRADER
    if settings.viewer_api_key and api_key == settings.viewer_api_key:
        return UserRole.VIEWER
    return None


def is_auth_configured() -> bool:
    settings = get_settings()
    return bool(settings.admin_api_key or settings.trader_api_key or settings.viewer_api_key)


def authenticate_api_key(api_key: Optional[str], *, source: str = "X-Api-Key") -> AuthenticatedUser:
    settings = get_settings()
    if not settings.auth_enabled:
        return AuthenticatedUser(api_key="anonymous", role=UserRole.ADMIN)

    if not is_auth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "QUANT_AUTH_ENABLED=true but no QUANT_*_API_KEY is configured",
            },
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "MISSING_API_KEY", "message": f"{source} is required"},
        )

    role = _resolve_role(api_key)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "INVALID_API_KEY", "message": "Invalid or expired API key"},
        )

    return AuthenticatedUser(api_key=api_key, role=role)


def get_current_user(x_api_key: Optional[str] = Header(default=None)) -> AuthenticatedUser:
    return authenticate_api_key(x_api_key)


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
