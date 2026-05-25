from apps.api.app.services import scanner_service


def test_market_status_shape(monkeypatch) -> None:
    monkeypatch.setattr(scanner_service.market_service, "get_realtime_quotes", lambda symbols: [])
    status = scanner_service._compute_market_status([
        {"symbol": "A.SH", "price": 10, "change_pct": 5.0, "limit_pct": 0.10},
        {"symbol": "B.SZ", "price": 10, "change_pct": -2.0, "limit_pct": 0.10},
    ])
    assert status["total"] == 2
    assert status["up"] == 1
    assert status["down"] == 1


def test_clear_cache_resets_timestamp() -> None:
    scanner_service._scan_cache["x"] = {"ok": True}
    scanner_service._scan_ts = 123.0
    scanner_service.clear_cache()
    assert scanner_service._scan_cache == {}
    assert scanner_service._scan_ts == 0.0
