from apps.api.app.services import scanner_service


def test_scanner_cache_key_is_clearable() -> None:
    scanner_service._scan_cache["test"] = {"items": []}
    scanner_service.clear_cache()
    assert scanner_service._scan_cache == {}


def test_strategy_list_contains_classic_names() -> None:
    strategies = scanner_service.get_strategy_list()
    names = {item["name"] for item in strategies}
    assert "放量上涨" in names
    assert "海龟交易" in names
