from dataclasses import dataclass, field, replace
from functools import lru_cache
import os
from typing import Any


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _coerce_runtime_value(value: Any, caster: type) -> Any:
    if caster is bool:
        return _coerce_bool(value)
    if caster is str:
        return str(value).strip()
    return caster(value)


def _csv(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _runtime_section(name: str) -> dict[str, Any]:
    try:
        from apps.api.app.core.runtime_config import get_runtime_config

        section = get_runtime_config().get(name) or {}
        return section if isinstance(section, dict) else {}
    except Exception:
        return {}


def get_feishu_webhook_url() -> str:
    runtime_url = str(_runtime_section("feishu").get("webhook_url") or "").strip()
    if runtime_url:
        return runtime_url
    return get_settings().feishu_webhook_url


def get_evolution_settings() -> "Settings":
    settings = get_settings()
    runtime = _runtime_section("evolution")
    if not runtime:
        return settings

    fields: dict[str, type] = {
        "evolution_validate_interval_seconds": int,
        "evolution_validate_initial_delay_seconds": int,
        "evolution_validate_limit": int,
        "evolution_validate_time": str,
        "evolution_failure_alert_enabled": bool,
        "evolution_failure_alert_cooldown_seconds": int,
        "evolution_auto_scan_enabled": bool,
        "evolution_auto_scan_interval_seconds": int,
        "evolution_auto_scan_top_n": int,
        "evolution_auto_scan_min_score": int,
        "evolution_auto_scan_candidate_pool": int,
        "evolution_auto_scan_enable_fundamental": bool,
        "evolution_auto_scan_enable_llm": bool,
        "evolution_auto_scan_llm_top_n": int,
        "evolution_auto_scan_target_horizon_days": int,
        "evolution_auto_evolve_enabled": bool,
        "evolution_auto_evolve_min_samples": int,
        "evolution_auto_evolve_min_live_samples": int,
        "evolution_auto_promote_min_success_rate": float,
        "evolution_auto_promote_min_avg_return_pct": float,
        "evolution_auto_promote_max_brier_score": float,
        "evolution_auto_promote_max_calibration_error": float,
        "evolution_auto_walk_forward_min_samples": int,
        "evolution_auto_walk_forward_min_dates": int,
        "evolution_auto_walk_forward_min_profitable_folds": float,
        "evolution_auto_walk_forward_return_tolerance": float,
        "evolution_auto_walk_forward_consistency_tolerance": float,
        "evolution_auto_walk_forward_drawdown_tolerance": float,
        "evolution_auto_rollback_enabled": bool,
        "evolution_auto_rollback_min_samples": int,
        "evolution_auto_rollback_min_success_rate": float,
        "evolution_auto_rollback_min_avg_return_pct": float,
        "evolution_auto_rollback_max_brier_score": float,
    }
    updates: dict[str, Any] = {}
    for key, caster in fields.items():
        if key not in runtime:
            continue
        try:
            updates[key] = _coerce_runtime_value(runtime[key], caster)
        except (TypeError, ValueError):
            continue
    return replace(settings, **updates)


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("QUANT_APP_NAME", "AlphaAgent"))
    app_env: str = field(default_factory=lambda: os.getenv("QUANT_APP_ENV", "production").lower())
    api_v1_prefix: str = field(default_factory=lambda: os.getenv("QUANT_API_V1_PREFIX", "/api/v1"))
    database_url: str = field(default_factory=lambda: os.getenv("QUANT_DATABASE_URL", "sqlite:///./var/quant.db"))

    # 市场数据
    market_data_provider: str = field(default_factory=lambda: os.getenv("QUANT_MARKET_DATA_PROVIDER", "akshare"))

    # LLM — 支持任意 OpenAI 兼容接口
    llm_api_key: str = field(default_factory=lambda: os.getenv("QUANT_LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("QUANT_LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("QUANT_LLM_MODEL", "gpt-4o-mini"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("QUANT_LLM_TEMPERATURE", "0.3")))
    llm_timeout: int = field(default_factory=lambda: int(os.getenv("QUANT_LLM_TIMEOUT", "60")))

    # 飞书机器人
    feishu_webhook_url: str = field(default_factory=lambda: os.getenv("QUANT_FEISHU_WEBHOOK_URL", ""))

    # 默认账户
    default_account_id: str = field(default_factory=lambda: os.getenv("QUANT_DEFAULT_ACCOUNT_ID", "acct-001"))

    # 鉴权默认开启；本地开发必须显式 QUANT_AUTH_ENABLED=false。
    auth_enabled: bool = field(default_factory=lambda: _bool("QUANT_AUTH_ENABLED", True))
    admin_api_key: str = field(default_factory=lambda: os.getenv("QUANT_ADMIN_API_KEY", ""))
    trader_api_key: str = field(default_factory=lambda: os.getenv("QUANT_TRADER_API_KEY", ""))
    viewer_api_key: str = field(default_factory=lambda: os.getenv("QUANT_VIEWER_API_KEY", ""))

    # CORS 默认只允许本地前端/后端；如需开放必须显式 QUANT_CORS_ORIGINS=*。
    cors_origins: list[str] = field(default_factory=lambda: _csv(
        "QUANT_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000",
    ))

    # 行情刷新间隔（秒）
    quote_interval: int = field(default_factory=lambda: int(os.getenv("QUANT_QUOTE_INTERVAL", "5")))
    # Agent 扫描间隔（秒）
    scan_interval: int = field(default_factory=lambda: int(os.getenv("QUANT_SCAN_INTERVAL", "300")))

    # 模型进化：到期预测自动验证。默认每天跑一次，设 0 可关闭。
    evolution_validate_interval_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_INTERVAL_SECONDS", "86400")))
    evolution_validate_initial_delay_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_INITIAL_DELAY_SECONDS", "60")))
    evolution_validate_limit: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_LIMIT", "200")))
    evolution_validate_time: str = field(default_factory=lambda: os.getenv("QUANT_EVOLUTION_VALIDATE_TIME", "").strip())
    evolution_failure_alert_enabled: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_FAILURE_ALERT_ENABLED", True))
    evolution_failure_alert_cooldown_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_FAILURE_ALERT_COOLDOWN_SECONDS", "3600")))
    evolution_auto_scan_enabled: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_SCAN_ENABLED", False))
    evolution_auto_scan_interval_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_INTERVAL_SECONDS", "86400")))
    evolution_auto_scan_top_n: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_TOP_N", "20")))
    evolution_auto_scan_min_score: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_MIN_SCORE", "50")))
    evolution_auto_scan_candidate_pool: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_CANDIDATE_POOL", "100")))
    evolution_auto_scan_enable_fundamental: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_SCAN_ENABLE_FUNDAMENTAL", True))
    evolution_auto_scan_enable_llm: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_SCAN_ENABLE_LLM", False))
    evolution_auto_scan_llm_top_n: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_LLM_TOP_N", "8")))
    evolution_auto_scan_target_horizon_days: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_SCAN_TARGET_HORIZON_DAYS", "0")))
    evolution_auto_evolve_enabled: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_EVOLVE_ENABLED", True))
    evolution_auto_evolve_min_samples: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "60")))
    evolution_auto_evolve_min_live_samples: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_LIVE_SAMPLES", "20")))
    evolution_auto_promote_min_success_rate: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.52")))
    evolution_auto_promote_min_avg_return_pct: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0.0")))
    evolution_auto_promote_max_brier_score: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.28")))
    evolution_auto_promote_max_calibration_error: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.18")))
    evolution_auto_walk_forward_min_samples: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_MIN_SAMPLES", "12")))
    evolution_auto_walk_forward_min_dates: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_MIN_DATES", "12")))
    evolution_auto_walk_forward_min_profitable_folds: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_MIN_PROFITABLE_FOLDS", "0.50")))
    evolution_auto_walk_forward_return_tolerance: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_RETURN_TOLERANCE", "0.001")))
    evolution_auto_walk_forward_consistency_tolerance: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_CONSISTENCY_TOLERANCE", "0.02")))
    evolution_auto_walk_forward_drawdown_tolerance: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_WALK_FORWARD_DRAWDOWN_TOLERANCE", "0.03")))
    evolution_auto_rollback_enabled: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_ROLLBACK_ENABLED", True))
    evolution_auto_rollback_min_samples: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SAMPLES", "30")))
    evolution_auto_rollback_min_success_rate: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_SUCCESS_RATE", "0.40")))
    evolution_auto_rollback_min_avg_return_pct: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MIN_AVG_RETURN_PCT", "-2.0")))
    evolution_auto_rollback_max_brier_score: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_ROLLBACK_MAX_BRIER_SCORE", "0.40")))

    # LLM 成本估算：按每 100 万 token 价格配置，默认 0 表示只记录 token 不估算金额。
    llm_input_cost_per_million_tokens: float = field(default_factory=lambda: float(os.getenv("QUANT_LLM_INPUT_COST_PER_MILLION_TOKENS", "0")))
    llm_output_cost_per_million_tokens: float = field(default_factory=lambda: float(os.getenv("QUANT_LLM_OUTPUT_COST_PER_MILLION_TOKENS", "0")))

    # 交易闭环：paper=本地模拟盘立即成交；qmt=转发到 Windows QMT Gateway。
    trading_mode: str = field(default_factory=lambda: os.getenv("QUANT_TRADING_MODE", "paper"))
    paper_initial_cash: float = field(default_factory=lambda: float(os.getenv("QUANT_PAPER_INITIAL_CASH", "1000000")))
    qmt_gateway_url: str = field(default_factory=lambda: os.getenv("QUANT_QMT_GATEWAY_URL", "http://127.0.0.1:8788"))
    qmt_gateway_api_key: str = field(default_factory=lambda: os.getenv("QUANT_QMT_GATEWAY_API_KEY", ""))
    trading_block_st_buy: bool = field(default_factory=lambda: _bool("QUANT_TRADING_BLOCK_ST_BUY", True))
    trading_enforce_hours: bool = field(default_factory=lambda: _bool("QUANT_TRADING_ENFORCE_HOURS", False))
    trading_single_stock_max_weight: float = field(default_factory=lambda: float(os.getenv("QUANT_TRADING_SINGLE_STOCK_MAX_WEIGHT", "0.15")))
    trading_daily_turnover_limit: float = field(default_factory=lambda: float(os.getenv("QUANT_TRADING_DAILY_TURNOVER_LIMIT", "0.50")))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Clear cached settings after tests or env changes."""
    get_settings.cache_clear()
