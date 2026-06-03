from dataclasses import dataclass, field
from functools import lru_cache
import os


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("QUANT_APP_NAME", "AlphaAgent"))
    api_v1_prefix: str = "/api/v1"
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

    # 鉴权（默认关闭，生产环境开启）
    auth_enabled: bool = field(default_factory=lambda: _bool("QUANT_AUTH_ENABLED", False))
    admin_api_key: str = field(default_factory=lambda: os.getenv("QUANT_ADMIN_API_KEY", "dev-admin-key"))
    trader_api_key: str = field(default_factory=lambda: os.getenv("QUANT_TRADER_API_KEY", "dev-trader-key"))
    viewer_api_key: str = field(default_factory=lambda: os.getenv("QUANT_VIEWER_API_KEY", "dev-viewer-key"))

    # 行情刷新间隔（秒）
    quote_interval: int = field(default_factory=lambda: int(os.getenv("QUANT_QUOTE_INTERVAL", "5")))
    # Agent 扫描间隔（秒）
    scan_interval: int = field(default_factory=lambda: int(os.getenv("QUANT_SCAN_INTERVAL", "300")))

    # 模型进化：到期预测自动验证。默认每天跑一次，设 0 可关闭。
    evolution_validate_interval_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_INTERVAL_SECONDS", "86400")))
    evolution_validate_initial_delay_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_INITIAL_DELAY_SECONDS", "60")))
    evolution_validate_limit: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_VALIDATE_LIMIT", "200")))
    evolution_auto_evolve_enabled: bool = field(default_factory=lambda: _bool("QUANT_EVOLUTION_AUTO_EVOLVE_ENABLED", True))
    evolution_auto_evolve_min_samples: int = field(default_factory=lambda: int(os.getenv("QUANT_EVOLUTION_AUTO_EVOLVE_MIN_SAMPLES", "60")))
    evolution_auto_promote_min_success_rate: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_SUCCESS_RATE", "0.52")))
    evolution_auto_promote_min_avg_return_pct: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MIN_AVG_RETURN_PCT", "0.0")))
    evolution_auto_promote_max_brier_score: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_BRIER_SCORE", "0.28")))
    evolution_auto_promote_max_calibration_error: float = field(default_factory=lambda: float(os.getenv("QUANT_EVOLUTION_AUTO_PROMOTE_MAX_CALIBRATION_ERROR", "0.18")))
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
    trading_single_stock_max_weight: float = field(default_factory=lambda: float(os.getenv("QUANT_TRADING_SINGLE_STOCK_MAX_WEIGHT", "0.30")))
    trading_daily_turnover_limit: float = field(default_factory=lambda: float(os.getenv("QUANT_TRADING_DAILY_TURNOVER_LIMIT", "0.50")))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Clear cached settings after tests or env changes."""
    get_settings.cache_clear()
