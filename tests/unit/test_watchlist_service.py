from apps.api.app.api.routes.watchlist import _normalize_symbol


def test_watchlist_normalize_suffix_case() -> None:
    assert _normalize_symbol("600519.sh") == "600519.SH"
    assert _normalize_symbol("000001.sz") == "000001.SZ"


def test_watchlist_normalize_without_suffix_preserves_uppercase() -> None:
    assert _normalize_symbol("abc") == "ABC"
