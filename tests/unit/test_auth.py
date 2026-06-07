"""Unit tests for core/auth.py RBAC logic."""

import pytest
from fastapi import HTTPException

from apps.api.app.core.auth import (
    AuthenticatedUser,
    UserRole,
    _resolve_role,
    authenticate_api_key,
    get_current_user,
    require_admin,
    require_trader,
)
from apps.api.app.core.config import Settings


def _settings_auth_on(**kwargs) -> Settings:
    return Settings(
        auth_enabled=True,
        admin_api_key="admin-key",
        trader_api_key="trader-key",
        viewer_api_key="viewer-key",
        **kwargs,
    )


def test_authenticated_user_roles() -> None:
    admin = AuthenticatedUser("k", UserRole.ADMIN)
    trader = AuthenticatedUser("k", UserRole.TRADER)
    viewer = AuthenticatedUser("k", UserRole.VIEWER)

    assert admin.is_admin is True
    assert admin.is_trader is True
    assert trader.is_admin is False
    assert trader.is_trader is True
    assert viewer.is_admin is False
    assert viewer.is_trader is False


def test_resolve_role(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())

    assert _resolve_role("admin-key") == UserRole.ADMIN
    assert _resolve_role("trader-key") == UserRole.TRADER
    assert _resolve_role("viewer-key") == UserRole.VIEWER
    assert _resolve_role("wrong-key") is None


def test_get_current_user_auth_disabled(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_settings", lambda: Settings(auth_enabled=False))
    user = get_current_user(x_api_key=None)
    assert user.role == UserRole.ADMIN


def test_get_current_user_missing_key_raises(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(x_api_key=None)
    assert exc_info.value.status_code == 401


def test_get_current_user_invalid_key_raises(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(x_api_key="wrong-key")
    assert exc_info.value.status_code == 403


def test_settings_defaults_to_auth_enabled_when_env_absent(monkeypatch) -> None:
    monkeypatch.delenv("QUANT_AUTH_ENABLED", raising=False)
    settings = Settings()
    assert settings.auth_enabled is True


def test_authenticate_api_key_ignores_empty_default_keys(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod

    monkeypatch.setattr(auth_mod, "get_settings", lambda: Settings(auth_enabled=True))
    with pytest.raises(HTTPException) as exc_info:
        authenticate_api_key("")
    assert exc_info.value.status_code == 401


def test_require_trader_and_admin_guards() -> None:
    admin = AuthenticatedUser("k", UserRole.ADMIN)
    trader = AuthenticatedUser("k", UserRole.TRADER)
    viewer = AuthenticatedUser("k", UserRole.VIEWER)

    assert require_trader(user=admin) is admin
    assert require_trader(user=trader) is trader
    assert require_admin(user=admin) is admin

    with pytest.raises(HTTPException):
        require_trader(user=viewer)
    with pytest.raises(HTTPException):
        require_admin(user=trader)
    with pytest.raises(HTTPException):
        require_admin(user=viewer)
