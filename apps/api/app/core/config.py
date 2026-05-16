from dataclasses import dataclass
from functools import lru_cache
import os


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("QUANT_APP_NAME", "A股智能助手")
    api_v1_prefix: str = "/api/v1"
    database_url: str = os.getenv("QUANT_DATABASE_URL", "sqlite:///./var/quant.db")

    # 市场数据
    market_data_provider: str = os.getenv("QUANT_MARKET_DATA_PROVIDER", "akshare")

    # LLM — 支持任意 OpenAI 兼容接口
    llm_api_key: str = os.getenv("QUANT_LLM_API_KEY", "")
    llm_base_url: str = os.getenv("QUANT_LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("QUANT_LLM_MODEL", "gpt-4o-mini")
    llm_temperature: float = float(os.getenv("QUANT_LLM_TEMPERATURE", "0.3"))
    llm_timeout: int = int(os.getenv("QUANT_LLM_TIMEOUT", "60"))

    # 飞书机器人
    feishu_webhook_url: str = os.getenv("QUANT_FEISHU_WEBHOOK_URL", "")

    # 默认账户
    default_account_id: str = os.getenv("QUANT_DEFAULT_ACCOUNT_ID", "acct-001")

    # 鉴权（默认关闭，生产环境开启）
    auth_enabled: bool = _bool("QUANT_AUTH_ENABLED", False)
    admin_api_key: str = os.getenv("QUANT_ADMIN_API_KEY", "dev-admin-key")
    trader_api_key: str = os.getenv("QUANT_TRADER_API_KEY", "dev-trader-key")
    viewer_api_key: str = os.getenv("QUANT_VIEWER_API_KEY", "dev-viewer-key")

    # 行情刷新间隔（秒）
    quote_interval: int = int(os.getenv("QUANT_QUOTE_INTERVAL", "5"))
    # Agent 扫描间隔（秒）
    scan_interval: int = int(os.getenv("QUANT_SCAN_INTERVAL", "300"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
