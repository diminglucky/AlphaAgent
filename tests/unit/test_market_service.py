from apps.api.app.services import market_service


def _clear_market_caches() -> None:
    with market_service._precise_lock:
        market_service._precise_cache.clear()
        market_service._precise_symbols.clear()
    with market_service._market_lock:
        market_service._market_cache.clear()


def test_realtime_quotes_prefers_precise_cache(monkeypatch) -> None:
    monkeypatch.setattr(market_service, "register_symbols", lambda symbols, persistent=True: None)
    with market_service._precise_lock:
        market_service._precise_cache.clear()
        market_service._precise_cache["600519.SH"] = {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "price": 100.0,
        }
    with market_service._market_lock:
        market_service._market_cache.clear()

    quotes = market_service.get_realtime_quotes(["600519.SH"])
    assert quotes == [{"symbol": "600519.SH", "name": "贵州茅台", "price": 100.0}]


def test_realtime_quotes_falls_back_to_market_cache(monkeypatch) -> None:
    monkeypatch.setattr(market_service, "register_symbols", lambda symbols, persistent=True: None)
    with market_service._precise_lock:
        market_service._precise_cache.clear()
    with market_service._market_lock:
        market_service._market_cache.clear()
        market_service._market_cache["000001"] = {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "price": 10.0,
        }

    quotes = market_service.get_realtime_quotes(["000001.SZ"])
    assert quotes[0]["symbol"] == "000001.SZ"
    assert quotes[0]["name"] == "平安银行"


def test_get_single_quote_fetches_on_cache_miss(monkeypatch) -> None:
    with market_service._precise_lock:
        market_service._precise_cache.clear()
    with market_service._market_lock:
        market_service._market_cache.clear()

    monkeypatch.setattr(
        market_service,
        "_fetch_precise",
        lambda symbols: {"300750.SZ": {"symbol": "300750.SZ", "name": "宁德时代", "price": 200.0}},
    )

    quote = market_service.get_single_quote("300750.SZ")
    assert quote["price"] == 200.0


def test_limit_pct_by_board_and_st_name() -> None:
    assert market_service._limit_pct("600519", "贵州茅台") == 0.10
    assert market_service._limit_pct("300750", "宁德时代") == 0.20
    assert market_service._limit_pct("688001", "华兴源创") == 0.20
    assert market_service._limit_pct("830000", "北交所样本") == 0.30
    assert market_service._limit_pct("600000", "*ST样本") == 0.05


def test_mock_provider_loads_market_cache_without_external_fetch(monkeypatch) -> None:
    _clear_market_caches()
    monkeypatch.setattr(market_service, "_provider_name", lambda: "mock")
    monkeypatch.setattr(
        market_service,
        "_fetch_market_all",
        lambda: (_ for _ in ()).throw(AssertionError("external fetch should not run")),
    )

    market_service.ensure_cache_running()

    snapshot = market_service.get_all_quotes_snapshot()
    assert len(snapshot) >= 30
    assert any(q["symbol"] == "300750.SZ" for q in snapshot)


def test_mock_provider_serves_quote_kline_search_and_news(monkeypatch) -> None:
    _clear_market_caches()
    monkeypatch.setattr(market_service, "_provider_name", lambda: "mock")
    monkeypatch.setattr(
        market_service,
        "_ak",
        lambda: (_ for _ in ()).throw(AssertionError("akshare should not be used in mock mode")),
    )

    quote = market_service.get_single_quote("300750.SZ")
    assert quote["name"] == "宁德时代"
    assert quote["price"] > 0
    assert market_service.get_realtime_quotes(["300750.SZ"])[0]["symbol"] == "300750.SZ"
    assert len(market_service.get_kline("300750.SZ", count=20)) == 20
    assert market_service.search_stocks("宁德")
    assert market_service.get_stock_news("300750.SZ", count=2)[0]["source"] == "AlphaAgent Mock"
