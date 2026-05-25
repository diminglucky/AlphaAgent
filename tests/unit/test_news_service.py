from apps.api.app.services import market_service


def test_get_stock_news_returns_empty_on_provider_error(monkeypatch) -> None:
    class FakeAk:
        def stock_news_em(self, symbol):
            raise RuntimeError("network down")

    monkeypatch.setattr(market_service, "_ak", lambda: FakeAk())
    assert market_service.get_stock_news("600519.SH") == []


def test_search_stocks_returns_empty_on_provider_error(monkeypatch) -> None:
    class FakeAk:
        def stock_info_a_code_name(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(market_service, "_ak", lambda: FakeAk())
    assert market_service.search_stocks("茅台") == []
