from dataclasses import dataclass
from functools import lru_cache
import os


def _read_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("QUANT_APP_NAME", "A股智能量化交易平台")
    app_env: str = os.getenv("QUANT_APP_ENV", "dev")
    api_v1_prefix: str = os.getenv("QUANT_API_V1_PREFIX", "/api/v1")
    default_currency: str = os.getenv("QUANT_DEFAULT_CURRENCY", "CNY")
    simulated_trading: bool = _read_bool("QUANT_SIMULATED_TRADING", True)
    require_order_confirmation: bool = _read_bool("QUANT_REQUIRE_ORDER_CONFIRMATION", False)
    market_data_provider: str = os.getenv("QUANT_MARKET_DATA_PROVIDER", "mock")
    database_url: str = os.getenv("QUANT_DATABASE_URL", "sqlite:///./var/quant.db")
    database_echo: bool = _read_bool("QUANT_DATABASE_ECHO", False)
    seed_demo_data: bool = _read_bool("QUANT_SEED_DEMO_DATA", True)
    auth_enabled: bool = _read_bool("QUANT_AUTH_ENABLED", False)
    admin_api_key: str = os.getenv("QUANT_ADMIN_API_KEY", "dev-admin-key")
    trader_api_key: str = os.getenv("QUANT_TRADER_API_KEY", "dev-trader-key")
    viewer_api_key: str = os.getenv("QUANT_VIEWER_API_KEY", "dev-viewer-key")
    signal_model_version: str = os.getenv("QUANT_SIGNAL_MODEL_VERSION", "technical_v1")
    default_account_id: str = os.getenv("QUANT_DEFAULT_ACCOUNT_ID", "acct-demo-001")
    llm_provider: str = os.getenv("QUANT_LLM_PROVIDER", "keyword")
    llm_model: str = os.getenv("QUANT_LLM_MODEL", "")
    llm_api_key: str = os.getenv("QUANT_LLM_API_KEY", "")
    llm_base_url: str = os.getenv("QUANT_LLM_BASE_URL", "")
    llm_temperature: float = float(os.getenv("QUANT_LLM_TEMPERATURE", "0.2"))
    llm_timeout: int = int(os.getenv("QUANT_LLM_TIMEOUT", "30"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
