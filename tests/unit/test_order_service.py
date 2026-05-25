from apps.api.app.api.routes.positions import _normalize_symbol


def test_position_normalize_plain_code() -> None:
    assert _normalize_symbol("600519") == "600519.SH"
    assert _normalize_symbol("000001") == "000001.SZ"


def test_position_normalize_exchange_suffix() -> None:
    assert _normalize_symbol("600519.sh") == "600519.SH"
    assert _normalize_symbol("000001.sz") == "000001.SZ"


def test_position_normalize_exchange_prefix() -> None:
    assert _normalize_symbol("sh600519") == "600519.SH"
    assert _normalize_symbol("sz000001") == "000001.SZ"
