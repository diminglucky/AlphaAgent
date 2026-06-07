from apps.api.app.core import runtime_config
from apps.api.app.core.config import get_evolution_settings, get_feishu_webhook_url


def test_feishu_webhook_runtime_override_masks_env(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_FEISHU_WEBHOOK_URL", "https://env.example/hook")

    assert get_feishu_webhook_url() == "https://env.example/hook"

    runtime_config.update_runtime_section("feishu", {"webhook_url": "https://runtime.example/hook"})

    assert get_feishu_webhook_url() == "https://runtime.example/hook"


def test_evolution_settings_use_runtime_override_and_string_bool(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_VALIDATE_INTERVAL_SECONDS", "86400")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_EVOLVE_ENABLED", "true")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_SCAN_ENABLED", "false")

    runtime_config.update_runtime_section(
        "evolution",
        {
            "evolution_validate_interval_seconds": 0,
            "evolution_validate_time": " 15:30 ",
            "evolution_failure_alert_enabled": "false",
            "evolution_failure_alert_cooldown_seconds": "120",
            "evolution_auto_scan_enabled": "true",
            "evolution_auto_scan_top_n": "15",
            "evolution_auto_scan_enable_llm": "false",
            "evolution_auto_scan_target_horizon_days": "5",
            "evolution_auto_evolve_enabled": "false",
            "evolution_auto_promote_min_success_rate": 0.7,
            "evolution_auto_walk_forward_min_samples": "18",
            "evolution_auto_walk_forward_min_dates": 21,
            "evolution_auto_walk_forward_min_profitable_folds": "0.65",
            "evolution_auto_walk_forward_return_tolerance": 0.002,
            "evolution_auto_walk_forward_consistency_tolerance": "0.03",
            "evolution_auto_walk_forward_drawdown_tolerance": 0.04,
        },
    )

    settings = get_evolution_settings()

    assert settings.evolution_validate_interval_seconds == 0
    assert settings.evolution_validate_time == "15:30"
    assert settings.evolution_failure_alert_enabled is False
    assert settings.evolution_failure_alert_cooldown_seconds == 120
    assert settings.evolution_auto_scan_enabled is True
    assert settings.evolution_auto_scan_top_n == 15
    assert settings.evolution_auto_scan_enable_llm is False
    assert settings.evolution_auto_scan_target_horizon_days == 5
    assert settings.evolution_auto_evolve_enabled is False
    assert settings.evolution_auto_promote_min_success_rate == 0.7
    assert settings.evolution_auto_walk_forward_min_samples == 18
    assert settings.evolution_auto_walk_forward_min_dates == 21
    assert settings.evolution_auto_walk_forward_min_profitable_folds == 0.65
    assert settings.evolution_auto_walk_forward_return_tolerance == 0.002
    assert settings.evolution_auto_walk_forward_consistency_tolerance == 0.03
    assert settings.evolution_auto_walk_forward_drawdown_tolerance == 0.04


def test_evolution_settings_ignore_invalid_runtime_values(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_SCAN_TOP_N", "20")
    monkeypatch.setenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_RETURN_TOLERANCE", "0.005")
    monkeypatch.setenv("QUANT_EVOLUTION_FAILURE_ALERT_COOLDOWN_SECONDS", "3600")

    runtime_config.update_runtime_section(
        "evolution",
        {
            "evolution_auto_scan_enabled": "true",
            "evolution_auto_scan_top_n": "not-an-int",
            "evolution_auto_walk_forward_return_tolerance": "bad-float",
            "evolution_failure_alert_cooldown_seconds": "bad-int",
        },
    )

    settings = get_evolution_settings()

    assert settings.evolution_auto_scan_enabled is True
    assert settings.evolution_auto_scan_top_n == 20
    assert settings.evolution_auto_walk_forward_return_tolerance == 0.005
    assert settings.evolution_failure_alert_cooldown_seconds == 3600
