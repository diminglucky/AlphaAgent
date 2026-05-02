"""Unit tests for core/auth.py RBAC logic."""

import pytest
from fastapi import HTTPException

from apps.api.app.core.auth import (
    AuthenticatedUser,
    _resolve_role,
    get_current_user,
    require_admin,
    require_trader,
)
from apps.api.app.core.config import Settings, reset_settings_cache
from libs.quant_core.enums import UserRole


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


def test_get_current_user_admin_key(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())
    user = get_current_user(x_api_key="admin-key")
    assert user.role == UserRole.ADMIN


def test_get_current_user_trader_key(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())
    user = get_current_user(x_api_key="trader-key")
    assert user.role == UserRole.TRADER


def test_get_current_user_viewer_key(monkeypatch) -> None:
    from apps.api.app.core import auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_settings", lambda: _settings_auth_on())
    user = get_current_user(x_api_key="viewer-key")
    assert user.role == UserRole.VIEWER


def test_require_trader_allows_trader() -> None:
    trader = AuthenticatedUser("k", UserRole.TRADER)
    result = require_trader(user=trader)
    assert result is trader


def test_require_trader_allows_admin() -> None:
    admin = AuthenticatedUser("k", UserRole.ADMIN)
    result = require_trader(user=admin)
    assert result is admin


def test_require_trader_blocks_viewer() -> None:
    viewer = AuthenticatedUser("k", UserRole.VIEWER)
    with pytest.raises(HTTPException) as exc_info:
        require_trader(user=viewer)
    assert exc_info.value.status_code == 403


def test_require_admin_allows_admin() -> None:
    admin = AuthenticatedUser("k", UserRole.ADMIN)
    result = require_admin(user=admin)
    assert result is admin


def test_require_admin_blocks_trader() -> None:
    trader = AuthenticatedUser("k", UserRole.TRADER)
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=trader)
    assert exc_info.value.status_code == 403


def test_require_admin_blocks_viewer() -> None:
    viewer = AuthenticatedUser("k", UserRole.VIEWER)
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=viewer)
    assert exc_info.value.status_code == 403
