from apps.api.app.services import scanner_service


def test_scanner_cache_key_is_clearable() -> None:
    scanner_service._scan_cache["test"] = {"items": []}
    scanner_service.clear_cache()
    assert scanner_service._scan_cache == {}


def test_scanner_cache_ttl_is_per_key(monkeypatch) -> None:
    scanner_service.clear_cache()
    monkeypatch.setattr(scanner_service, "_CACHE_TTL", 300)
    clock = {"now": 1_000.0}
    monkeypatch.setattr(scanner_service.time, "monotonic", lambda: clock["now"])

    old_key = "old"
    new_key = "new"
    scanner_service._scan_cache[old_key] = {"ts": 600.0, "value": {"results": ["old"]}}
    scanner_service._scan_cache[new_key] = {"ts": 995.0, "value": {"results": ["new"]}}

    assert scanner_service._get_cached_scan_result(new_key) == {"results": ["new"]}
    assert scanner_service._get_cached_scan_result(old_key) is None


def test_strategy_list_contains_classic_names() -> None:
    strategies = scanner_service.get_strategy_list()
    names = {item["name"] for item in strategies}
    assert "放量上涨" in names
    assert "海龟交易" in names


def test_evolution_ranking_runs_before_top_n_truncation(monkeypatch) -> None:
    def fake_enrich(results, db=None, target_horizon_days=None):
        assert target_horizon_days is None
        probabilities = {
            "LOW.SZ": (0.51, 0.4),
            "BEST.SZ": (0.83, 2.6),
            "MID.SZ": (0.62, 1.1),
        }
        enriched = []
        for item in results:
            probability, expected_return = probabilities[item["symbol"]]
            stock = dict(item)
            stock["evolution"] = {
                "probability": probability,
                "expected_return_pct": expected_return,
            }
            enriched.append(stock)
        return {"model_version_id": 7, "model_version": "rule-v7", "results": enriched}

    from apps.api.app.services import evolution_service

    monkeypatch.setattr(evolution_service, "enrich_scan_results_with_model", fake_enrich)
    ranked, meta = scanner_service._rank_recommendations_with_evolution([
        {"symbol": "LOW.SZ", "score": 95, "ai_analysis": {"action": "BUY"}},
        {"symbol": "BEST.SZ", "score": 60, "ai_analysis": {"action": "BUY"}},
        {"symbol": "MID.SZ", "score": 80, "ai_analysis": {"action": "BUY"}},
    ], top_n=1)

    assert [item["symbol"] for item in ranked] == ["BEST.SZ"]
    assert meta == {"model_version_id": 7, "model_version": "rule-v7"}


def test_evolution_ranking_can_target_specific_horizon(monkeypatch) -> None:
    seen = {}

    def fake_enrich(results, db=None, target_horizon_days=None):
        seen["target_horizon_days"] = target_horizon_days
        table = {
            "SHORT.SZ": {"probability": 0.82, "expected_return_pct": 1.2},
            "MID.SZ": {"probability": 0.55, "expected_return_pct": 3.5},
        }
        enriched = []
        for item in results:
            stock = dict(item)
            stock["evolution"] = table[item["symbol"]]
            enriched.append(stock)
        return {"model_version_id": 8, "model_version": "rule-v8", "results": enriched}

    from apps.api.app.services import evolution_service

    monkeypatch.setattr(evolution_service, "enrich_scan_results_with_model", fake_enrich)
    ranked, meta = scanner_service._rank_recommendations_with_evolution([
        {"symbol": "MID.SZ", "score": 90, "ai_analysis": {"action": "BUY"}},
        {"symbol": "SHORT.SZ", "score": 70, "ai_analysis": {"action": "BUY"}},
    ], top_n=1, target_horizon_days=5)

    assert seen["target_horizon_days"] == 5
    assert [item["symbol"] for item in ranked] == ["SHORT.SZ"]
    assert meta == {"model_version_id": 8, "model_version": "rule-v8"}
