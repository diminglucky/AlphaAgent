from libs.market_data.symbols import (
    infer_exchange,
    normalize_provider_code,
    to_internal_symbol,
    to_provider_symbol,
)


def test_infer_exchange() -> None:
    assert infer_exchange("600519") == "SH"
    assert infer_exchange("300750") == "SZ"


def test_symbol_conversion() -> None:
    assert to_internal_symbol("600519") == "600519.SH"
    assert to_internal_symbol("sh600519") == "600519.SH"
    assert to_provider_symbol("600519.SH") == "600519"
    assert normalize_provider_code("sz000001") == "000001"
