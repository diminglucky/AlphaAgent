from apps.api.app.services import llm_service


def test_calc_indicators_standard_macd_has_values() -> None:
    bars = [
        {"close": float(i), "high": float(i + 1), "low": float(i - 1), "amount": 1000}
        for i in range(1, 40)
    ]

    indicators = llm_service._calc_indicators(bars)
    assert indicators["macd_dif"] is not None
    assert indicators["macd_dea"] is not None
    assert indicators["macd_hist"] is not None


def test_calc_indicators_position_flat_range() -> None:
    bars = [
        {"close": 10.0, "high": 10.0, "low": 10.0, "amount": 1000}
        for _ in range(30)
    ]

    indicators = llm_service._calc_indicators(bars)
    assert indicators["pos_in_20d"] == 50
